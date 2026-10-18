"""Scenarios: a ticket's story told in a few lines, played against the fakes.

A scenario test reads the way an entry in docs/SCENARIOS.md does: the overseer ticks and decides, workers run and push,
the operator replies, and the test checks what canopy did. The `scenario` fixture's `Scenario` tells the story; the
functions below it are the moves in it, the overseer's (`dispatches`, `raises`, `sets_phase`, `skips_tick`, and `waits`
from `helpers.py`) and a worker's (`pushes`, `asks`, `fails`, or any `*_does` helper). Each is a helper of `helpers.py`
with the plumbing folded in: a tick's exit code checked, the runs it started waited for, a dispatch's flags spelled as
keywords.

    def test_a_red_check_resumes_the_branch(scenario: Scenario, git_pool: GitPool) -> None:
        scenario.run(worker=pushes())
        ticked = scenario.tick(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI]), worker=pushes())
        assert ticked.actions == ["queried", "dispatch:resume"]
        [run] = ticked.runs
        assert run.reasons == (ResumeReason.CI,)
        assert "This is attempt 1 of 6." in run.prompt

A dispatch canopy turns down is a move too, and so is the clock: `refuses` says what canopy decided instead of running
it, and `time_passes` moves every time the journal recorded into the past, so a cooldown or a schedule sees it gone by:

    def test_a_second_resume_for_ci_waits_out_the_cooldown(scenario: Scenario, git_pool: GitPool) -> None:
        scenario.run(worker=pushes())
        fix = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI])
        scenario.run(fix, worker=pushes())
        [(action, _)] = scenario.refuses(fix)
        assert action == "refused:cooldown"
        scenario.time_passes(hours=1)
        scenario.run(fix, worker=pushes())

The overseer is played whole, not only its commands: what its query found (`queried=`), the line it ends on
(`result=`), and how it runs (`exit_code=`, `says=`, ...), so a tick it fails, or a duty it leaves undone, is a story
too:

    def test_a_ticket_the_query_found_is_owed_a_decision(scenario: Scenario) -> None:
        failed = scenario.tick(queried=["PROJ-9"], code=1)
        assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-9"

A step the verbs do not cover is written as before, in the same test: the verbs are argv lists and context managers, so
they mix with `canopy(...)`, `overseer_does`, and the journal's own queries.

A scenario keeps the story as it played: each move a `Scenario` method made, and what canopy did with it, failing step
included. When a scenario test fails, its report carries that story in a section of its own, `scenario`, ending on the
attention list as the test left it, so the failure reads in the order the ticket lived it:

    ---------------------------------------- scenario ----------------------------------------
    1. run 1, implement of PROJ-1: done: did it
    2. run 2, resume of PROJ-1 for ci: done: did it
    3. tick 3 refuses canopy dispatch PROJ-1 --repo repo --kind resume --label agent-ready-tester --reason ci
         PROJ-1 refused:cooldown: a resume for CI alone in PROJ-1 in repo may run again after 2026-10-18T23:00:02Z
    4. 1:00:00 passes
    5. run 3, resume of PROJ-1 for ci: done: did it
    The attention list now: nothing.
"""

import json
import shlex
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Unpack

from canopy.cli.main import main
from canopy.core import db, records
from canopy.core.vocab import Phase, ResumeReason, RunKind, RunStatus, TickStatus
from canopy.loop import attention
from tests.canopy.helpers import (
    BRANCH,
    KEY,
    LABEL,
    QUESTION,
    TICK_DONE,
    WORKER_DONE,
    Behavior,
    InlineRunner,
    blocked_result,
    canopy,
    commit_and_push,
    decisions,
    in_tick,
    last_run,
    last_tick,
    operator,
    overseer_does,
    present,
    seen,
    state_block,
    wait_for_run,
    worker_does,
)
from tests.conftest import CanopyEnv

# What a worker does: one of the `*_does` helpers' blocks, or `pushes` or `asks`.
type Worker = AbstractContextManager[None]


@dataclass(frozen=True)
class Ran:
    """A worker run as it ended: its row, why it ran if it is a resume, and the prompt its worker was given."""

    row: sqlite3.Row
    reasons: tuple[ResumeReason, ...]
    prompt_file: Path

    @property
    def id(self) -> int:
        """The run's id."""
        return int(self.row["id"])

    @property
    def kind(self) -> RunKind:
        """What the run was dispatched to do."""
        return RunKind(self.row["kind"])

    @property
    def status(self) -> RunStatus:
        """How the run ended."""
        return RunStatus(self.row["status"])

    @property
    def branch(self) -> str | None:
        """The branch the run worked on."""
        branch: str | None = self.row["branch"]
        return branch

    @property
    def ended_at(self) -> datetime:
        """When the run ended."""
        return db.parse_time(str(self.row["ended_at"]))

    @property
    def prompt(self) -> str:
        """The prompt the run's worker was given."""
        return self.prompt_file.read_text()

    def __str__(self) -> str:
        """The run in a line, for a failed step's message: what it was for, how it ended, and what its result said."""
        why = f" for {', '.join(self.reasons)}" if self.reasons else ""
        result: dict[str, Any] = json.loads(self.row["result_json"] or "{}")
        said = [str(result[k]) for k in ("summary", "question", "harness") if result.get(k)]
        return ": ".join([f"run {self.id}, {self.kind} of {self.row['ticket_key']}{why}", self.status, *said])


@dataclass(frozen=True)
class Ticked:
    """What a tick did: its row, its decisions in the order it recorded them, and the worker runs it started, ended."""

    tick: records.Tick
    decisions: list[records.Decision]
    runs: list[Ran]

    @property
    def actions(self) -> list[str]:
        """Each decision's action, in order: `queried`, `dispatch:resume`, `attention:crashed`, ..."""
        return [d.action for d in self.decisions]

    def __str__(self) -> str:
        """How the tick ended and what it decided, for a failed step's message."""
        lines = [f"{self.tick.status}: {self.tick.summary}"]
        lines += map(_decided, self.decisions)
        lines += [f"  {r}" for r in self.runs]
        return "\n".join(lines)


@dataclass(frozen=True)
class Scenario:
    """A workspace of one repository, `repo`, where a test plays the overseer, the workers, and the operator in turn."""

    env: CanopyEnv
    conn: sqlite3.Connection
    agent_log: Path
    # Each move made so far, and what canopy did with it, in the order they were made: `told` reads it out.
    story: list[str] = field(default_factory=list, init=False)

    def tick(
        self,
        *commands: list[str],
        worker: Worker | None = None,
        dry_run: bool = False,
        code: int = 0,
        queried: Sequence[str] | None = (),
        result: str = TICK_DONE,
        **overseer: Unpack[Behavior],
    ) -> Ticked:
        """Run one tick, `canopy tick`, its overseer running `commands`, and wait for each run it dispatches to end.

        Each run's worker does `worker`, the fake's default `done` if None. The overseer records `queried`, the keys its
        query found, when the query is due, or no query at all if None; it ends on `result`, by default the line that
        ends a tick, and runs as `overseer` says (`exit_code`, `says`, ...). The tick must exit `code`, and a failure
        says how it ended instead.

        Returns:
            What the tick did.
        """
        argv = ["tick", "--dry-run"] if dry_run else ["tick"]
        recorded = "skip" if queried is None else json.dumps(list(queried))
        with ExitStack() as stack:
            stack.enter_context(overseer_does(*commands, result=result, queried=recorded, **overseer))
            if worker is not None:
                stack.enter_context(worker)
            exited = main(argv)
            tick = last_tick(self.conn)
            started = self.conn.execute("SELECT id FROM runs WHERE tick_id = ? ORDER BY id", (tick.id,)).fetchall()
            # A run is detached from the tick, so the worker's script must last until it ends.
            runs = [self._ran(wait_for_run(self.conn, int(r["id"]))) for r in started]
        ticked = Ticked(present(db.get_tick(self.conn, tick.id)), db.decisions_for_tick(self.conn, tick.id), runs)
        self.story.append(f"tick {tick.id}, exits {exited}: {ticked}")
        assert exited == code, f"tick {tick.id} exited {exited}, not {code}: {ticked}"
        return ticked

    def run(self, command: list[str] | None = None, *, worker: Worker | None = None) -> Ran:
        """Dispatch `command`, a `dispatches(...)`, KEY's `implement` if None, in a tick of its own, and run it in this
        process, its worker doing `worker`.

        The overseer is not run, so a run's story can start without a tick's.

        Returns:
            The run, closed.
        """
        command = command or dispatches()
        assert command[:2] == ["canopy", "dispatch"], command
        runner = InlineRunner()
        with ExitStack() as stack:
            if worker is not None:
                stack.enter_context(worker)
            with in_tick(self.conn) as tick_id:
                exited = main(command[1:], runner=runner)
                if exited != 0:
                    self._tell(f"tick {tick_id} does not dispatch {shlex.join(command)}", tick_id)
                assert exited == 0, db.decisions_for_tick(self.conn, tick_id)
                db.finish_tick(self.conn, tick_id, TickStatus.OK, "test")
                run_id = int(last_run(self.conn)["id"])
                exited = main(["_run", str(run_id)], runner=runner)
        ran = self._ran(present(db.get_run(self.conn, run_id)))
        self.story.append(str(ran) if exited == 0 else f"{ran}, and `canopy _run` exits {exited}")
        assert exited == 0, ran
        return ran

    def refuses(self, command: list[str], *, dry_run: bool = False) -> list[tuple[str, str]]:
        """Dispatch `command`, a `dispatches(...)`, in a tick of its own, which canopy must refuse, starting no run.

        Returns:
            The tick's decisions, as (action, rationale): the refusal, and the attention it raised, if any.
        """
        assert command[:2] == ["canopy", "dispatch"], command
        with in_tick(self.conn, dry_run=dry_run, ends_ok=True) as tick_id:
            exited = main(command[1:], runner=InlineRunner())
        made = decisions(self.conn, tick_id)
        self._tell(f"tick {tick_id} {'refuses' if exited == 1 else 'does not refuse'} {shlex.join(command)}", tick_id)
        assert exited == 1, f"dispatch exited {exited}, not refused: {made}"
        started = self.conn.execute("SELECT count(*) FROM runs WHERE tick_id = ?", (tick_id,)).fetchone()[0]
        assert started == 0, made
        return made

    def time_passes(self, *, hours: float = 0, minutes: float = 0) -> None:
        """Move every time the journal recorded, in a column of its own, `hours` and `minutes` into the past.

        A cooldown, an attempt's age, a schedule, or a deadline then sees that much time gone by; times inside a JSON
        field stay as they are.
        """
        passed = timedelta(hours=hours, minutes=minutes)
        seconds = passed.total_seconds()
        assert seconds > 0, "time only passes forward"
        self.story.append(f"{passed} passes")
        tables = self.conn.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "AND sql NOT LIKE 'CREATE VIRTUAL%'"
        ).fetchall()
        for (table,) in tables:
            for column in self.conn.execute("SELECT name FROM pragma_table_info(?)", (table,)).fetchall():
                if column[0].endswith(("_at", "_since", "_until")):
                    _shift(self.conn, table, column[0], f"-{seconds} seconds")

    def operator(self, *args: str) -> None:
        """Run one of the operator's commands, `canopy ARGS`, from their shell; it must succeed."""
        exited = operator(*args)
        self.story.append(f"the operator runs {shlex.join(['canopy', *args])}, which exits {exited}")
        assert exited == 0, args

    def seen(self, *keys: str) -> None:
        """Record `keys`, KEY if none, as tickets an earlier tick saw, so the overseer owes each a decision."""
        seen(self.conn, self.env, *keys)
        self.story.append(f"an earlier tick saw {', '.join(keys or (KEY,))}")

    def attention(self) -> list[tuple[str | None, str]]:
        """The attention list as it stands, each item as (ticket key, reason)."""
        return [(i.ticket_key, i.reason) for i in attention.current(self.conn)]

    def state(self) -> dict[str, Any]:
        """The state block the latest overseer was given."""
        return state_block(self.agent_log)

    def ticket_state(self, key: str = KEY) -> dict[str, Any]:
        """The ticket `key` as the latest overseer's state block carried it."""
        [found] = [t for t in self.state()["tickets"] if t["key"] == key]
        ticket: dict[str, Any] = found
        return ticket

    def told(self) -> str:
        """The story so far, one numbered step for each move, and the attention list as it stands at its end.

        Returns:
            The story, for a failed test's report.
        """
        steps = [f"{n}. " + step.replace("\n", "\n   ") for n, step in enumerate(self.story, start=1)]
        # Read for a failed test's report, so a journal the failure left unreadable still lets the steps be told.
        try:
            items = [f"{key or '-'} {reason}" for key, reason in self.attention()] or ["nothing"]
        except sqlite3.Error as e:
            items = [f"unread ({e})"]
        return "\n".join([*steps, f"The attention list now: {', '.join(items)}."])

    def _tell(self, step: str, tick_id: int) -> None:
        self.story.append("\n".join([step, *map(_decided, db.decisions_for_tick(self.conn, tick_id))]))

    def _ran(self, row: sqlite3.Row) -> Ran:
        run_id = int(row["id"])
        reasons = db.run_reasons(self.conn, [run_id]).get(run_id, ())
        return Ran(row, reasons, self.env.state_dir / "runs" / f"{run_id}.prompt")


# What the overseer does in a tick: each is the command it runs, for `Scenario.tick`.


def dispatches(
    key: str = KEY,
    kind: RunKind = RunKind.IMPLEMENT,
    *,
    repo: str = "repo",
    label: str | None = LABEL,
    slug: str | None = None,
    base: str | None = None,
    reasons: Iterable[ResumeReason] = (),
    cursors: Mapping[str, str] | None = None,
    context: str | None = None,
    review_run: int | None = None,
) -> list[str]:
    """The overseer dispatches a run of `key` in `repo`, by default an `implement` under the test operator's label.

    Pass `label=None` for a ticket the operator started, which needs none.
    """
    flags = ["--kind", str(kind)]
    flags += _option("--label", label) + _option("--slug", slug) + _option("--base", base)
    flags += _option("--review-run", None if review_run is None else str(review_run))
    for reason in reasons:
        flags += ["--reason", str(reason)]
    for name, value in (cursors or {}).items():
        flags += ["--cursor", f"{name}={value}"]
    flags += _option("--context", context)
    return canopy("dispatch", key, "--repo", repo, *flags)


def raises(key: str, reason: str, detail: str | None = None) -> list[str]:
    """The overseer raises `reason` about `key` on the attention list, with `detail`, `<key> detail` by default."""
    return canopy("attention", key, reason, "--detail", detail if detail is not None else f"{key} detail")


def skips_tick(rationale: str) -> list[str]:
    """The overseer skips the whole tick, for `rationale`, one of the tick-wide reasons: `mcp_unavailable: github`."""
    return canopy("decide", "skip", "--rationale", rationale)


def sets_phase(key: str, phase: Phase, *, repo: str | None = None, cursor: str | None = None) -> list[str]:
    """The overseer records `key`'s phase, its unit's in `repo` if given, and a cursor as `name=value`."""
    return canopy("ticket", "set", key, "--phase", str(phase), *_option("--repo", repo), *_option("--cursor", cursor))


# What a worker does in its run: each is a block, for `Scenario.tick` and `Scenario.run`.


def pushes(branch: str = BRANCH, message: str = "PROJ-1: the change") -> Worker:
    """The worker commits `message`, pushes `branch`, and reports it done with a PR."""
    return worker_does(*commit_and_push(branch, message), result=WORKER_DONE.replace(BRANCH, branch))


def asks(question: str = QUESTION) -> Worker:
    """The worker pushes nothing and reports it blocked, asking `question`."""
    return worker_does(result=json.dumps(blocked_result() | {"question": question}))


def fails(summary: str = "could not build") -> Worker:
    """The worker pushes nothing and reports it failed, saying `summary`."""
    return worker_does(result=json.dumps({"status": "failed", "summary": summary}))


def _decided(decision: records.Decision) -> str:
    return f"  {decision.ticket_key or '-'} {decision.action}: {decision.rationale}"


def _option(name: str, value: str | None) -> list[str]:
    return [name, value] if value is not None else []


def _shift(conn: sqlite3.Connection, table: str, column: str, modifier: str) -> None:
    # The names come from the journal's own schema; strftime writes the shape `db.format_time` does, and a value it
    # cannot read as a time is left alone.
    moved = f"strftime('%Y-%m-%dT%H:%M:%fZ', {column}, ?)"
    conn.execute(f'UPDATE "{table}" SET {column} = {moved} WHERE {moved} IS NOT NULL', (modifier, modifier))  # noqa: S608
