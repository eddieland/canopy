"""Scenarios: a ticket's story told in a few lines, played against the fakes.

A scenario test reads the way an entry in docs/SCENARIOS.md does: the overseer ticks and decides, workers run and push,
the operator replies, and the test checks what canopy did. The `scenario` fixture's `Scenario` tells the story; the
functions below it are the moves in it, the overseer's (`dispatches`, `raises`, `sets_phase`, `skips_tick`, and `waits`
from `helpers.py`) and a worker's (`pushes`, `asks`, or any `*_does` helper). Each is a helper of `helpers.py` with the
plumbing folded in: a tick's exit code checked, the runs it started waited for, a dispatch's flags spelled as keywords.

    def test_a_red_check_resumes_the_branch(scenario: Scenario, git_pool: GitPool) -> None:
        scenario.run(worker=pushes())
        ticked = scenario.tick(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI]), worker=pushes())
        assert ticked.actions == ["queried", "dispatch:resume"]

The overseer is played whole, not only its commands: what its query found (`queried=`), the line it ends on
(`result=`), and how it runs (`exit_code=`, `says=`, ...), so a tick it fails, or a duty it leaves undone, is a story
too:

    def test_a_ticket_the_query_found_is_owed_a_decision(scenario: Scenario) -> None:
        failed = scenario.tick(queried=["PROJ-9"], code=1)
        assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-9"

A step the verbs do not cover is written as before, in the same test: the verbs are argv lists and context managers, so
they mix with `canopy(...)`, `overseer_does`, and the journal's own queries.
"""

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Unpack

from canopy.cli.main import main
from canopy.core import db, records
from canopy.core.vocab import Phase, ResumeReason, RunKind, TickStatus
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
class Ticked:
    """What a tick did: its row, its decisions in the order it recorded them, and the worker runs it started, ended."""

    tick: records.Tick
    decisions: list[records.Decision]
    runs: list[sqlite3.Row]

    @property
    def actions(self) -> list[str]:
        """Each decision's action, in order: `queried`, `dispatch:resume`, `attention:crashed`, ..."""
        return [d.action for d in self.decisions]

    def __str__(self) -> str:
        """How the tick ended and what it decided, for a failed step's message."""
        lines = [f"{self.tick.status}: {self.tick.summary}"]
        lines += [f"  {d.ticket_key or '-'} {d.action}: {d.rationale}" for d in self.decisions]
        lines += [f"  run {r['id']}, {r['kind']} of {r['ticket_key']}: {r['status']}" for r in self.runs]
        return "\n".join(lines)


@dataclass(frozen=True)
class Scenario:
    """A workspace of one repository, `repo`, where a test plays the overseer, the workers, and the operator in turn."""

    env: CanopyEnv
    conn: sqlite3.Connection
    agent_log: Path

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
            runs = [wait_for_run(self.conn, int(r["id"])) for r in started]
        ticked = Ticked(present(db.get_tick(self.conn, tick.id)), db.decisions_for_tick(self.conn, tick.id), runs)
        assert exited == code, f"tick {tick.id} exited {exited}, not {code}: {ticked}"
        return ticked

    def run(self, command: list[str] | None = None, *, worker: Worker | None = None) -> sqlite3.Row:
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
                assert main(command[1:], runner=runner) == 0, db.decisions_for_tick(self.conn, tick_id)
                db.finish_tick(self.conn, tick_id, TickStatus.OK, "test")
                run_id = int(last_run(self.conn)["id"])
                assert main(["_run", str(run_id)], runner=runner) == 0
        return present(db.get_run(self.conn, run_id))

    def operator(self, *args: str) -> None:
        """Run one of the operator's commands, `canopy ARGS`, from their shell; it must succeed."""
        assert operator(*args) == 0, args

    def seen(self, *keys: str) -> None:
        """Record `keys`, KEY if none, as tickets an earlier tick saw, so the overseer owes each a decision."""
        seen(self.conn, self.env, *keys)

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


def _option(name: str, value: str | None) -> list[str]:
    return [name, value] if value is not None else []
