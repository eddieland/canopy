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

A tick that dispatches several tickets runs a worker for each, and each plays the script it is given as made for its
own ticket: `pushes()` pushes the branch of the ticket it runs for, so one script serves them all. `workers=` gives a
ticket a script of its own, and the scenario's workers are titled, as the default templates title them, so each run
knows its ticket:

    def test_one_ticket_fails_while_the_other_pushes(scenario: Scenario, git_pool: GitPool) -> None:
        ticked = scenario.tick(dispatches(), dispatches("PROJ-2"), worker=pushes(), workers={"PROJ-2": fails()})
        assert [r.status for r in ticked.runs] == ["done", "failed"]
        assert git_pool.remote_head("agent/PROJ-1-work") is not None

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

The config is part of the story too: `configures` sets keys in the user file, by default, or in the workspace file or
the private one, merged into what the file holds, so a key lands in its own table whatever came last in the file, and
the story says what the next command reads:

    def test_a_limit_of_one_stops_the_second_resume(scenario: Scenario, git_pool: GitPool) -> None:
        scenario.configures(policy={"max_resume_attempts": 1})
        scenario.run(worker=pushes())
        scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW]), worker=pushes())
        [(action, _), _] = scenario.refuses(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW]))
        assert action == "refused:attempt_limit"

A run can be left at work while the story goes on around it: `starts`, or a tick with `hold=True`, holds each worker
it starts before it does anything and gives the run back as `Working`. The test then says what becomes of it: it
`finishes`, doing what its script says, or its `canopy _run` `dies`, as a crash or a shutdown would leave it, its worker
still at work, for the next tick to find. A run still held when the test ends is stopped:

    def test_a_run_whose_process_died_is_crashed_on_the_next_tick(scenario: Scenario, git_pool: GitPool) -> None:
        working = scenario.starts(worker=pushes())
        [(action, _)] = scenario.refuses(dispatches())
        assert action == "refused:running"
        working.dies()
        ticked = scenario.tick(*waits("PROJ-1"))
        assert ticked.actions[0] == "attention:crashed"

The overseer is played whole, not only its commands: what its query found (`queried=`), the line it ends on
(`result=`), and how it runs (`exit_code=`, `says=`, ...), so a tick it fails, or a duty it leaves undone, is a story
too:

    def test_a_ticket_the_query_found_is_owed_a_decision(scenario: Scenario) -> None:
        failed = scenario.tick(queried=["PROJ-9"], code=1)
        assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-9"

The operator is played whole too: `operator` runs one of their commands and gives back what canopy printed, `out` and
`err`, as their shell would show them, and a command canopy refuses is a move like any other, the exit it must make
named as `code=`. A tick's `printed` is what `canopy tick` printed, likewise. Neither reaches the test's own output, so
a test reads it from the move, not from `capsys`:

    def test_a_grant_needs_a_ticket_canopy_has_seen(scenario: Scenario, git_pool: GitPool) -> None:
        refused = scenario.operator("grant", "PROJ-1", "resume", code=1)
        assert "grant refused (unknown)" in refused.err
        scenario.run(worker=fails())
        assert "may now have 3." in scenario.operator("grant", "PROJ-1", "implement").out

A story that spans repositories is told in `ws_scenario`, the same `Scenario` in the workspace of two, `api` and
`web`, each pool a slot of its own. A dispatch names the repositories it works in, and a joint run's worker pushes in
each through its desk:

    def test_a_joint_implement_pushes_both_repositories(ws_scenario: Scenario, ws: Ws) -> None:
        both = ("api", "web")
        run = ws_scenario.run(dispatches(repo=both), worker=pushes(repos=both))
        assert ws.remote_head("web", run.branch) is not None

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
    6. the operator runs canopy grant PROJ-1 resume, which exits 0
         PROJ-1 in repo has had 2 resume runs, and may now have 7. The next tick decides whether to dispatch it.
    The attention list now: nothing.
"""

import io
import json
import os
import shlex
import sqlite3
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Unpack, assert_never
from unittest import mock

from canopy.cli.main import main
from canopy.core import db, records
from canopy.core.vocab import Phase, ResumeReason, RunKind, RunStatus, TickStatus
from canopy.infra import procs
from canopy.loop import attention
from tests.canopy.helpers import (
    KEY,
    LABEL,
    QUESTION,
    TICK_DONE,
    WORKER_DONE,
    Behavior,
    InlineRunner,
    Script,
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

#: What a worker does: one of the `*_does` helpers' blocks, or `pushes`, `asks`, or `fails`. A `Script` among them,
#: `worker_does`'s and those three, is played by each ticket's run as made for that ticket (`Script.for_ticket`).
type Worker = AbstractContextManager[None]

#: Which of the workspace's config files a test sets keys in (DESIGN §12): the operator's user file, the workspace
#: file, or the workspace's private file.
type ConfigFile = Literal["user", "workspace", "private"]

#: How many lines of what a command printed to stdout its step in the story keeps; what it printed to stderr, where a
#: refusal says why, the story keeps whole.
TOLD_LINES = 2

#: How long a held worker, or a test waiting on one, waits before it gives up.
HOLD_TIMEOUT = 60

#: The command a held worker runs first, with the gates' directory: it says it is at work, in `<run id>.working`, then
#: waits for `<run id>.open` before it goes on to what its script says. It gives up after HOLD_TIMEOUT, failing, so a
#: worker no test lets go of does not outlast its test by much.
GATE = f"""
import os, pathlib, sys, time
gate = pathlib.Path(sys.argv[1], os.environ["CANOPY_RUN_ID"])
gate.with_suffix(".working").touch()
deadline = time.monotonic() + {HOLD_TIMEOUT}
while not gate.with_suffix(".open").exists():
    if time.monotonic() > deadline:
        sys.exit("held too long")
    time.sleep(0.02)
"""


@dataclass(frozen=True)
class Printed:
    """What a canopy command printed, as the operator's shell would show it."""

    #: What it printed to stdout.
    out: str
    #: What it printed to stderr, where a refusal says why.
    err: str

    def told(self) -> list[str]:
        """What it printed, for its step in the story: the first TOLD_LINES lines of stdout, and stderr whole.

        Returns:
            Each line printed that is not blank, indented, with a line in place of the ones left out.
        """
        out = [line for line in self.out.splitlines() if line.strip()]
        kept = out[:TOLD_LINES]
        if len(out) > len(kept):
            kept.append(f"({len(out) - len(kept)} more lines)")
        kept += [line for line in self.err.splitlines() if line.strip()]
        return [f"  {line}" for line in kept]


@dataclass(frozen=True)
class Ran:
    """A worker run as it ended: its row, why it ran if it is a resume, and the prompt its worker was given."""

    row: sqlite3.Row
    reasons: tuple[ResumeReason, ...]
    prompt_file: Path
    #: What its `canopy _run` printed, the run log among it, when the scenario ran it in this process (`Scenario.run`).
    printed: Printed = Printed("", "")

    @property
    def id(self) -> int:
        """The run's id."""
        return int(self.row["id"])

    @property
    def key(self) -> str:
        """The key of the ticket the run was for."""
        return str(self.row["ticket_key"])

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
        result: dict[str, Any] = json.loads(self.row["result_json"] or "{}")
        said = [str(result[k]) for k in ("summary", "question", "harness") if result.get(k)]
        return ": ".join([_named(self.row, self.reasons), self.status, *said])


@dataclass(frozen=True)
class Working:
    """A worker run held at work: its worker started and waits there until the test says what becomes of the run."""

    #: The scenario the run is part of.
    scenario: "Scenario"
    #: The run's id.
    id: int
    #: Why it runs, if it is a resume.
    reasons: tuple[ResumeReason, ...]

    @property
    def row(self) -> sqlite3.Row:
        """The run's row as it stands."""
        return present(db.get_run(self.scenario.conn, self.id))

    def finishes(self) -> Ran:
        """Let the worker go on to what its script says, and wait for the run to end.

        Returns:
            The run, closed.
        """
        (self.scenario.gates / f"{self.id}.open").touch()
        ran = self.scenario.ran(wait_for_run(self.scenario.conn, self.id, timeout=HOLD_TIMEOUT))
        self.scenario.story.append(str(ran))
        return ran

    def dies(self) -> None:
        """Kill the run's own process, `canopy _run`, at once, as a crash or a machine's shutdown would.

        Its row stays `running`, and the worker it started stays at work, as they would for the next tick's reconcile
        to find.
        """
        pid = int(self.row["pid"])
        procs.kill_group(pid)
        deadline = time.monotonic() + HOLD_TIMEOUT
        while procs.alive(pid):
            assert time.monotonic() < deadline, f"run {self.id}'s `canopy _run` outlived its kill"
            time.sleep(0.02)
        self.scenario.story.append(
            f"{_named(self.row, self.reasons)}: its `canopy _run` dies, its worker still at work"
        )

    def __str__(self) -> str:
        """The run in a line, for a failed step's message: what it is for, and that it is at work."""
        return f"{_named(self.row, self.reasons)}: at work"


@dataclass(frozen=True)
class Ticked:
    """What a tick did: its row, its decisions in the order it recorded them, and the worker runs it started."""

    #: The tick's row, closed.
    tick: records.Tick
    #: Its decisions, in the order it recorded them.
    decisions: list[records.Decision]
    #: The runs it started, each waited for until it ended.
    runs: list[Ran]
    #: What `canopy tick` printed: the line that says how the tick ended, and what went wrong if it failed.
    printed: Printed
    #: The runs it started and left at work, with `hold=True`.
    working: list[Working] = field(default_factory=list)

    @property
    def actions(self) -> list[str]:
        """Each decision's action, in order: `queried`, `dispatch:resume`, `attention:crashed`, ..."""
        return [d.action for d in self.decisions]

    def __str__(self) -> str:
        """How the tick ended, what it decided, and what it printed to stderr, for a failed step's message."""
        lines = [f"{self.tick.status}: {self.tick.summary}"]
        lines += map(_decided, self.decisions)
        lines += [f"  {r}" for r in [*self.runs, *self.working]]
        # What `canopy tick` printed no longer reaches the test's own output, so what went wrong in it is told here.
        lines += [f"  {line}" for line in self.printed.err.splitlines() if line.strip()]
        return "\n".join(lines)


@dataclass(frozen=True)
class Scenario:
    """A workspace of one repository, `repo`, where a test plays the overseer, the workers, and the operator in turn."""

    env: CanopyEnv
    conn: sqlite3.Connection
    agent_log: Path
    #: Where each held worker's gate is, a file per run (GATE).
    gates: Path
    #: Each move made so far, and what canopy did with it, in the order they were made: `told` reads it out.
    story: list[str] = field(default_factory=list, init=False)
    #: Each run held so far, whatever became of it since, for `close` to stop what is left of it.
    held: list[int] = field(default_factory=list, init=False)

    def tick(
        self,
        *commands: list[str],
        worker: Worker | None = None,
        workers: Mapping[str, Script] | None = None,
        dry_run: bool = False,
        hold: bool = False,
        code: int = 0,
        queried: Sequence[str] | None = (),
        result: str = TICK_DONE,
        **overseer: Unpack[Behavior],
    ) -> Ticked:
        """Run one tick, `canopy tick`, its overseer running `commands`, and wait for each run it dispatches to end.

        Each run's worker does `worker`, the fake's default `done` if None, or what `workers` gives for its ticket: a
        script each ticket's run plays as made for that ticket, so `pushes()` pushes the branch of the ticket it runs
        for. With `hold`, each is held at work instead, and the tick's runs are left `working` for the test to finish
        or kill. The overseer records `queried`, the keys its query found, when the query is due, or no query at all if
        None; it ends on `result`, by default the line that ends a tick, and runs as `overseer` says (`exit_code`,
        `says`, ...). The tick must exit `code`, and a failure says how it ended instead.

        Returns:
            What the tick did.
        """
        argv = ["tick", "--dry-run"] if dry_run else ["tick"]
        recorded = "skip" if queried is None else json.dumps(list(queried))
        with ExitStack() as stack:
            stack.enter_context(overseer_does(*commands, result=result, queried=recorded, **overseer))
            if worker is not None:
                stack.enter_context(worker)
            stack.enter_context(_each_ticket(worker, workers or {}, commands))
            if hold:
                stack.enter_context(self._held())
            exited, printed = _printing(lambda: main(argv))
            tick = last_tick(self.conn)
            started = self.conn.execute("SELECT id FROM runs WHERE tick_id = ? ORDER BY id", (tick.id,)).fetchall()
            # A run is detached from the tick, so the worker's script must last until it ends.
            ids = [int(r["id"]) for r in started]
            runs = [] if hold else [self.ran(wait_for_run(self.conn, run_id)) for run_id in ids]
        working = [self._at_work(run_id) for run_id in ids] if hold else []
        made = db.decisions_for_tick(self.conn, tick.id)
        ticked = Ticked(present(db.get_tick(self.conn, tick.id)), made, runs, printed, working)
        self.story.append(f"tick {tick.id}, exits {exited}: {ticked}")
        assert exited == code, f"tick {tick.id} exited {exited}, not {code}: {ticked}"
        return ticked

    def run(
        self, command: list[str] | None = None, *, worker: Worker | None = None, runner: InlineRunner | None = None
    ) -> Ran:
        """Dispatch `command`, a `dispatches(...)`, KEY's `implement` if None, in a tick of its own, and run it in this
        process, its worker doing `worker`, made for the ticket `command` names.

        The overseer is not run, so a run's story can start without a tick's. `runner` runs its processes, one that
        times a worker out, say, or a plain `InlineRunner` if None.

        Returns:
            The run, closed, with what its `canopy _run` printed.
        """
        command = command or dispatches()
        assert command[:2] == ["canopy", "dispatch"], command
        runner = runner or InlineRunner()
        with ExitStack() as stack:
            if worker is not None:
                stack.enter_context(_made_for(worker, command[2]))
            with in_tick(self.conn) as tick_id:
                exited = main(command[1:], runner=runner)
                if exited != 0:
                    self._tell(f"tick {tick_id} does not dispatch {shlex.join(command)}", tick_id)
                assert exited == 0, db.decisions_for_tick(self.conn, tick_id)
                db.finish_tick(self.conn, tick_id, TickStatus.OK, "test")
                run_id = int(last_run(self.conn)["id"])
                exited, printed = _printing(lambda: main(["_run", str(run_id)], runner=runner))
        ran = replace(self.ran(present(db.get_run(self.conn, run_id))), printed=printed)
        self.story.append(str(ran) if exited == 0 else f"{ran}, and `canopy _run` exits {exited}")
        assert exited == 0, ran
        return ran

    def starts(self, command: list[str] | None = None, *, worker: Worker | None = None) -> Working:
        """Dispatch `command`, a `dispatches(...)`, KEY's `implement` if None, in a tick of its own, and hold its worker
        at work, the worker set to do `worker`, made for the ticket `command` names, once the test lets it go on.

        The run is detached, as a tick's is, and the overseer is not run.

        Returns:
            The run, at work.
        """
        command = command or dispatches()
        assert command[:2] == ["canopy", "dispatch"], command
        with ExitStack() as stack:
            if worker is not None:
                stack.enter_context(_made_for(worker, command[2]))
            stack.enter_context(self._held())
            with in_tick(self.conn) as tick_id:
                exited = main(command[1:])
                if exited != 0:
                    self._tell(f"tick {tick_id} does not dispatch {shlex.join(command)}", tick_id)
                assert exited == 0, db.decisions_for_tick(self.conn, tick_id)
                db.finish_tick(self.conn, tick_id, TickStatus.OK, "test")
                run_id = int(last_run(self.conn)["id"])
        working = self._at_work(run_id)
        self.story.append(str(working))
        return working

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
                # An event's, a message's, or a forget's time is its plain `at`.
                if column[0] == "at" or column[0].endswith(("_at", "_since", "_until")):
                    _shift(self.conn, table, column[0], f"-{seconds} seconds")

    def operator(self, *args: str, code: int = 0) -> Printed:
        """Run one of the operator's commands, `canopy ARGS`, from their shell; it must exit `code`.

        What it printed is kept from the test's own output, and told in the story instead.

        Returns:
            What it printed, as the operator would read it.
        """
        exited, printed = _printing(lambda: operator(*args))
        command = shlex.join(["canopy", *args])
        self.story.append("\n".join([f"the operator runs {command}, which exits {exited}", *printed.told()]))
        assert exited == code, f"{command} exited {exited}, not {code}: {printed.err or printed.out}"
        return printed

    def configures(self, file: ConfigFile = "user", /, **tables: Mapping[str, object]) -> None:
        """Set the keys of each table in `tables`, named as in TOML, in the config `file`; the next command reads them.

        A key set takes the place of the one there, and every other key stays, whatever table it is in, so a test sets
        only what its story is about: `configures(policy={"max_resume_attempts": 2})`, or a table inside another as a
        mapping inside one, `configures(notify={"sinks": {"slack": {"cmd": "true"}}})`.
        """
        assert tables, "configures sets at least one table's keys"
        match file:
            case "user":
                path = self.env.user_file
            case "workspace":
                path = self.env.shared_file
            case "private":
                path = self.env.private_file
            case _:
                assert_never(file)
        self.story.append(f"the {file} file sets {', '.join(self.env.configure(path, tables))}")

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

    def ran(self, row: sqlite3.Row) -> Ran:
        """The run `row` as it ended.

        Returns:
            The run, with why it ran and where its prompt is.
        """
        run_id = int(row["id"])
        reasons = db.run_reasons(self.conn, [run_id]).get(run_id, ())
        return Ran(row, reasons, self.env.state_dir / "runs" / f"{run_id}.prompt")

    def close(self) -> None:
        """Stop what is left of every run held at work, its `canopy _run` and its worker both, as the test ends."""
        for run_id in self.held:
            row = present(db.get_run(self.conn, run_id))
            if row["status"] == RunStatus.RUNNING:
                for pid in (row["pid"], row["worker_pid"]):
                    if pid is not None:
                        procs.kill_group(int(pid))

    def _tell(self, step: str, tick_id: int) -> None:
        self.story.append("\n".join([step, *map(_decided, db.decisions_for_tick(self.conn, tick_id))]))

    @contextmanager
    def _held(self) -> Iterator[None]:
        # The worker's script is in its environment by now; GATE goes first in it. A run reads the environment as it
        # starts, so the gate lasts as long as the run does.
        self.gates.mkdir(exist_ok=True)
        gate = [sys.executable, "-c", GATE, str(self.gates)]
        script = os.environ.get("FAKE_WORKER_COMMANDS", os.environ.get("FAKE_AGENT_COMMANDS", "[]"))
        env = {"FAKE_WORKER_COMMANDS": json.dumps([gate, *json.loads(script)])}
        # A ticket's own script stands in for the role's, commands and all, so its commands are gated too.
        tickets: dict[str, dict[str, str]] = json.loads(os.environ.get("FAKE_WORKER_FOR", "{}"))
        for settings in tickets.values():
            if "COMMANDS" in settings:
                settings["COMMANDS"] = json.dumps([gate, *json.loads(settings["COMMANDS"])])
        if tickets:
            env["FAKE_WORKER_FOR"] = json.dumps(tickets)
        with mock.patch.dict(os.environ, env):
            yield

    def _at_work(self, run_id: int) -> Working:
        self.held.append(run_id)
        working = self.gates / f"{run_id}.working"
        deadline = time.monotonic() + HOLD_TIMEOUT
        while True:
            row = present(db.get_run(self.conn, run_id))
            # The worker's pid too, which `_run` records just after it starts the worker, so `close` knows what to stop.
            if working.exists() and row["worker_pid"] is not None:
                break
            assert row["status"] == RunStatus.RUNNING, f"{self.ran(row)}, before its worker was at work"
            assert time.monotonic() < deadline, f"run {run_id}'s worker was not at work after {HOLD_TIMEOUT}s"
            time.sleep(0.02)
        reasons = db.run_reasons(self.conn, [run_id]).get(run_id, ())
        return Working(self, run_id, reasons)


# What the overseer does in a tick: each is the command it runs, for `Scenario.tick`.


def dispatches(
    key: str = KEY,
    kind: RunKind = RunKind.IMPLEMENT,
    *,
    repo: str | Sequence[str] = "repo",
    label: str | None = LABEL,
    slug: str | None = None,
    base: str | None = None,
    reasons: Iterable[ResumeReason] = (),
    cursors: Mapping[str, str] | None = None,
    context: str | None = None,
    review_run: int | None = None,
    request: str | None = None,
) -> list[str]:
    """The overseer dispatches a run of `key` in `repo`, by default an `implement` under the test operator's label.

    `repo` is one repository, or several for a joint run or a split, in `ws_scenario`'s workspace of two. Pass
    `label=None` for a ticket the operator started, which needs none, and `request` for a split, the comment asking for
    it.
    """
    repos = [repo] if isinstance(repo, str) else list(repo)
    flags = [arg for name in repos for arg in ("--repo", name)] + ["--kind", str(kind)]
    flags += _option("--label", label) + _option("--slug", slug) + _option("--base", base)
    flags += _option("--review-run", None if review_run is None else str(review_run))
    for reason in reasons:
        flags += ["--reason", str(reason)]
    for name, value in (cursors or {}).items():
        flags += ["--cursor", f"{name}={value}"]
    flags += _option("--context", context) + _option("--request", request)
    return canopy("dispatch", key, *flags)


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


def pushes(
    branch: str | None = None, message: str | None = None, *, repos: Sequence[str] = (), **reported: object
) -> Script:
    """The worker commits `message`, pushes `branch`, and reports it done with a PR, its result carrying `reported`
    too: `pushes(notes=[...])`.

    What is left out is its ticket's own: the branch an `implement` without a slug pushes, `agent/<KEY>-work`; the
    message `<KEY>: the change`; and the PR, `https://example.test/pr/<the key's number>`. A joint run's worker, in a
    desk, names its `repos`: it commits and pushes in each, and reports a PR for each,
    `https://example.test/<repo>/pr/<the key's number>`. Made for KEY until a run of another ticket plays it.
    """
    assert not isinstance(repos, str), "repos is a sequence of names: repos=('api', 'web')"

    def made(key: str) -> Script:
        pushed, said, number = branch or f"agent/{key}-work", message or f"{key}: the change", key.rpartition("-")[2]
        result = json.loads(WORKER_DONE) | {"branch": pushed, "pr": f"https://example.test/pr/{number}"}
        commands = commit_and_push(pushed, said)
        if repos:
            # In a desk each repository is a link of its own, and the run records a PR per repository, not one.
            del result["pr"]
            result["prs"] = {name: f"https://example.test/{name}/pr/{number}" for name in repos}
            commands = [["git", "-C", name, *command[1:]] for name in repos for command in commands]
        return worker_does(*commands, result=json.dumps(result | reported))

    return replace(made(KEY), per_ticket=made)


def asks(question: str = QUESTION) -> Script:
    """The worker pushes nothing and reports it blocked on its ticket's own branch, asking `question`."""

    def made(key: str) -> Script:
        return worker_does(result=json.dumps(blocked_result() | {"branch": f"agent/{key}-work", "question": question}))

    return replace(made(KEY), per_ticket=made)


def fails(summary: str = "could not build") -> Script:
    """The worker pushes nothing and reports it failed, saying `summary`."""
    return worker_does(result=json.dumps({"status": "failed", "summary": summary}))


@contextmanager
def _each_ticket(worker: Worker | None, workers: Mapping[str, Script], commands: Iterable[list[str]]) -> Iterator[None]:
    # Each ticket a command dispatches, and each `workers` names, gets its script made for it; a run reads its own.
    dispatched = [command[2] for command in commands if command[:2] == ["canopy", "dispatch"]]
    every = worker if isinstance(worker, Script) else None
    made = {
        key: script.for_ticket(key)
        for key in dict.fromkeys([*dispatched, *workers])
        if (script := workers.get(key, every))
    }
    assert all(script.role == "WORKER" for script in made.values()), made
    tickets = {key: dict(script.settings) for key, script in made.items()}
    with mock.patch.dict(os.environ, {"FAKE_WORKER_FOR": json.dumps(tickets)}):
        yield


def _made_for(worker: Worker, key: str) -> Worker:
    return worker.for_ticket(key) if isinstance(worker, Script) else worker


def _printing(command: Callable[[], int]) -> tuple[int, Printed]:
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            exited = command()
    except BaseException:
        # A command that raises makes no move to tell; what it printed goes to the test's own output, for its report.
        sys.stdout.write(out.getvalue())
        sys.stderr.write(err.getvalue())
        raise
    return exited, Printed(out.getvalue(), err.getvalue())


def _named(row: sqlite3.Row, reasons: Sequence[ResumeReason]) -> str:
    why = f" for {', '.join(reasons)}" if reasons else ""
    return f"run {row['id']}, {row['kind']} of {row['ticket_key']}{why}"


def _decided(decision: records.Decision) -> str:
    return f"  {decision.ticket_key or '-'} {decision.action}: {decision.rationale}"


def _option(name: str, value: str | None) -> list[str]:
    return [name, value] if value is not None else []


def _shift(conn: sqlite3.Connection, table: str, column: str, modifier: str) -> None:
    # The names come from the journal's own schema; strftime writes the shape `db.format_time` does, and a value it
    # cannot read as a time is left alone.
    moved = f"strftime('%Y-%m-%dT%H:%M:%fZ', {column}, ?)"
    conn.execute(f'UPDATE "{table}" SET {column} = {moved} WHERE {moved} IS NOT NULL', (modifier, modifier))  # noqa: S608
