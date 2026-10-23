"""Scenarios: a ticket's story told in a few lines, played against the fakes.

A scenario test reads the way an entry in docs/SCENARIOS.md does: the overseer ticks and decides, workers run and push,
the operator replies, and the test checks what canopy did. The `scenario` fixture's `Scenario` tells the story; the
functions below it are the moves in it, the overseer's (`dispatches`, `reviews`, `raises`, `sets_phase`, `skips_tick`,
and `waits` from `helpers.py`) and a worker's (`pushes`, `asks`, `fails`, or any `*_does` helper). Each is a helper of
`helpers.py` with the plumbing folded in: a tick's exit code checked, the runs it started waited for, a dispatch's
flags spelled as keywords.

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

A review is the overseer's move as a dispatch is: `reviews` is its command, and `review` starts it in a tick of its
own and does it in this process, its reviewer reporting what the test gives it:

    def test_a_review_names_its_ticket(scenario: Scenario, git_pool: GitPool) -> None:
        reviewed = scenario.review(reviews(head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))
        assert (reviewed.status, reviewed.row.ticket_key) == ("done", "PROJ-1")

A review is held at work as a run is, with `starts_review`. The overseer's own commands are moves too: `overseer` runs
one in a tick of its own, or in the one `ticking` holds open, so what several raise is the attention list:

    def test_two_items_raised_in_one_tick(scenario: Scenario) -> None:
        with scenario.ticking():
            scenario.overseer("attention", "PROJ-1", "needs_human", "--detail", "one")
            scenario.overseer("attention", "PROJ-2", "needs_human", "--detail", "two")
        assert len(scenario.attention()) == 2

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
from collections import UserList
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Unpack, assert_never
from unittest import mock

from canopy.cli.main import main
from canopy.core import db, feedback_items, records, review_runs
from canopy.core.vocab import Phase, ResumeReason, ReviewRunStatus, RunKind, RunStatus, TickStatus
from canopy.infra import logs, procs
from canopy.loop import attention, poll
from tests.canopy.helpers import (
    DRAFTS_PR,
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
    comment,
    commit_and_push,
    context,
    in_tick,
    last_run,
    last_tick,
    operator,
    overseer_does,
    planner_does,
    present,
    seen,
    state_block,
    wait_for_run,
    worker_does,
)
from tests.canopy.review_helpers import PR
from tests.conftest import CanopyEnv

#: What a worker does: one of the `*_does` helpers' blocks, or `pushes`, `asks`, or `fails`. A `Script` among them,
#: `worker_does`'s and those three, is played by each ticket's run as made for that ticket (`Script.for_ticket`).
type Worker = AbstractContextManager[None]

#: Which of the workspace's config files a test sets keys in (DESIGN §12): the operator's user file, the workspace
#: file, or the workspace's private file.
type ConfigFile = Literal["user", "workspace", "private"]

#: A feedback plan's text, as `feedback_planned`'s planner writes it.
FEEDBACK_TEXT = "# Feedback plan: PROJ-1\n\n## Items\n\n### Item 501: change\n\nRename it.\n"
#: alice's comment, which `with_a_pr` trusts her for, and bob's, on a thread of its own, both on DRAFTS_PR's head.
ALICES_COMMENT = comment(501)
BOBS_COMMENT = comment(502, "PRRT_2", author="bob", body="Drop this argument.")
#: DRAFTS_PR's head in `github_shows`, and the check that is red there.
FEEDBACK_HEAD = "abc1234"
FEEDBACK_RED = {"name": "build", "status": "completed", "conclusion": "failure"}
#: `feedback_planned`'s planner's result: a change for alice's comment, a decline for bob's, and an id it was never
#: given.
FEEDBACK_PLANNED = {
    "status": "done",
    "summary": "planned the round",
    "items": [
        {"id": 501, "proposal": "change", "reply": "Renamed."},
        {"id": 502, "proposal": "decline", "reply": "Kept, since the API needs it."},
        {"id": 999, "proposal": "change"},
    ],
}

#: How many lines of what a command printed to stdout its step in the story keeps; what it printed to stderr, where a
#: refusal says why, the story keeps whole.
TOLD_LINES = 2

#: How long a held worker, or a test waiting on one, waits before it gives up.
HOLD_TIMEOUT = 60

#: The overseer's commands that start a review run: a review, and a revision of a review's draft (DESIGN §34).
REVIEW_COMMANDS = (["canopy", "review", "run"], ["canopy", "review", "revise"])

#: The roles a held run's agent may play, each scripted by its own `FAKE_<ROLE>_*` variables: a worker, a private
#: ticket's, a planner, and a reviewer. The overseer is never held.
HELD_ROLES = ("WORKER", "WORKER_PRIVATE", "PLANNER", "REVIEWER")

#: The command a held agent runs first, with the gates' directory: it says it is at work, in `<run id>.working`, its run
#: id as CANOPY_RUN_ID names it (`7`, or `review-7` for a review), then waits for `<run id>.open` before it goes on to
#: what its script says. It gives up after HOLD_TIMEOUT, failing, so an agent no test lets go of does not outlast its
#: test by much. An agent with no run id is not one a test holds, and goes on at once.
GATE = f"""
import os, pathlib, sys, time
run = os.environ.get("CANOPY_RUN_ID")
if not run:
    sys.exit(0)
gate = pathlib.Path(sys.argv[1], run)
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
        _killed(int(self.row["pid"]), f"run {self.id}'s `canopy _run`")
        self.scenario.story.append(
            f"{_named(self.row, self.reasons)}: its `canopy _run` dies, its worker still at work",
        )

    def __str__(self) -> str:
        """The run in a line, for a failed step's message: what it is for, and that it is at work."""
        return f"{_named(self.row, self.reasons)}: at work"


@dataclass(frozen=True)
class Reviewed:
    """A review run as it ended: its row, the prompt its reviewer was given, and what its `canopy _review` printed."""

    #: The review run's row, closed.
    row: records.ReviewRun
    #: Where the prompt its reviewer was given is.
    prompt_file: Path
    #: What its `canopy _review` printed, the run log among it.
    printed: Printed

    @property
    def id(self) -> int:
        """The review run's id."""
        return self.row.id

    @property
    def status(self) -> ReviewRunStatus:
        """How the review run ended."""
        return self.row.status

    @property
    def prompt(self) -> str:
        """The prompt the review run's reviewer was given."""
        return self.prompt_file.read_text()

    def __str__(self) -> str:
        """The review run in a line, for a failed step's message: what it reviewed, how it ended, and what it said."""
        result: dict[str, Any] = json.loads(self.row.result_json or "{}")
        said = [str(result[k]) for k in ("verdict", "summary", "harness") if result.get(k)]
        return ": ".join([_reviewed(self.row), self.row.status, *said])


@dataclass(frozen=True)
class Reviewing:
    """A review run held at work: its reviewer started and waits there until the test says what becomes of the run."""

    #: The scenario the review run is part of.
    scenario: "Scenario"
    #: The review run's id.
    id: int

    @property
    def row(self) -> records.ReviewRun:
        """The review run's row as it stands."""
        return present(review_runs.get_review_run(self.scenario.conn, self.id))

    def finishes(self) -> Reviewed:
        """Let the reviewer go on to what its script says, and wait for the review run to end.

        Returns:
            The review run, closed, with what its `canopy _review` printed to its log.
        """
        (self.scenario.gates / f"review-{self.id}.open").touch()
        deadline = time.monotonic() + HOLD_TIMEOUT
        while (row := self.row).status == ReviewRunStatus.RUNNING:
            assert time.monotonic() < deadline, f"{self} did not end after {HOLD_TIMEOUT}s"
            time.sleep(0.02)
        log = Path(row.log_path)
        printed = Printed(log.read_text() if log.exists() else "", "")
        reviewed = Reviewed(row, self.scenario.env.state_dir / "reviews" / f"{self.id}.prompt", printed)
        self.scenario.story.append(str(reviewed))
        return reviewed

    def dies(self) -> None:
        """Kill the review run's own process, `canopy _review`, at once, as a crash or a machine's shutdown would.

        Its row stays `running`, and the reviewer it started stays at work, as they would for the next tick's reconcile
        to find.
        """
        _killed(present(self.row.pid), f"review run {self.id}'s `canopy _review`")
        self.scenario.story.append(f"{_reviewed(self.row)}: its `canopy _review` dies, its reviewer still at work")

    def __str__(self) -> str:
        """The review run in a line, for a failed step's message: what it reviews, and that it is at work."""
        return f"{_reviewed(self.row)}: at work"


class Refused(UserList[tuple[str, str]]):
    """What canopy refused: the decisions of the tick it refused in, as (action, rationale), the refusal and the
    attention it raised, if any, and beside them that tick, its decisions whole, and what the refused command printed.
    """

    def __init__(
        self,
        decided: Iterable[tuple[str, str]] = (),
        *,
        tick: int | None = None,
        made: Sequence[records.Decision] = (),
        printed: Printed | None = None,
    ) -> None:
        """Hold what refusing `tick` decided, `made`, and what the refused command printed.

        `decided` is given alone when a list's own methods make a new one, a slice say, which keeps no tick.
        """
        super().__init__([*decided, *((d.action, d.rationale) for d in made)])
        #: The tick canopy refused in.
        self.tick = tick
        #: Its decisions whole, with the ticket, repository, and PR each named.
        self.decisions = list(made)
        #: What the refused command printed, its refusal on stderr.
        self.printed = printed or Printed("", "")


@dataclass(frozen=True)
class Ticked:
    """What a tick did: its row, its decisions in the order it recorded them, and the worker runs it started."""

    #: The tick's row, closed.
    tick: records.Tick
    #: Its decisions, in the order it recorded them.
    decisions: Sequence[records.Decision]
    #: The runs it started, each waited for until it ended.
    runs: Sequence[Ran]
    #: What `canopy tick` printed: the line that says how the tick ended, and what went wrong if it failed.
    printed: Printed
    #: The runs it started and left at work, with `hold=True`.
    working: Sequence[Working] = ()

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


@dataclass
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
    #: Each review run held so far, likewise.
    held_reviews: list[int] = field(default_factory=list, init=False)
    #: The tick `ticking` holds open for the overseer's commands, if one is.
    open_tick: int | None = field(default=None, init=False)

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
        self,
        command: list[str] | None = None,
        *,
        worker: Worker | None = None,
        runner: InlineRunner | None = None,
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

    def review(
        self,
        command: list[str],
        *,
        reviewer: Worker | None = None,
        runner: InlineRunner | None = None,
    ) -> Reviewed:
        """Start the review `command`, a `reviews(...)` or a `revises(...)`, in a tick of its own, and do it in this
        process, its reviewer doing `reviewer`, a `reviewer_reports(...)`, or the fake's default report if None.

        The overseer is not run. `runner` runs the reviewer's processes, one that times it out, say, or a plain
        `InlineRunner` if None.

        Returns:
            The review run, closed, with what its `canopy _review` printed.
        """
        assert command[:3] in REVIEW_COMMANDS, command
        with ExitStack() as stack:
            if reviewer is not None:
                stack.enter_context(reviewer)
            with in_tick(self.conn) as tick_id:
                exited = main(command[1:], runner=InlineRunner())
                if exited != 0:
                    self._tell(f"tick {tick_id} does not start {shlex.join(command)}", tick_id)
                assert exited == 0, db.decisions_for_tick(self.conn, tick_id)
                db.finish_tick(self.conn, tick_id, TickStatus.OK, "test")
                run_id = int(self.conn.execute("SELECT max(id) FROM review_runs").fetchone()[0])
                exited, printed = _printing(lambda: main(["_review", str(run_id)], runner=runner or InlineRunner()))
        row = present(review_runs.get_review_run(self.conn, run_id))
        reviewed = Reviewed(row, self.env.state_dir / "reviews" / f"{run_id}.prompt", printed)
        self.story.append(str(reviewed) if exited == 0 else f"{reviewed}, and `canopy _review` exits {exited}")
        assert exited == 0, reviewed
        return reviewed

    def reviews_each(self, command: list[str], *, reviewer: Worker | None = None) -> list[Reviewed]:
        """Start the reviews `command`, a `reviews(...)`, starts in a tick of its own, one in each persona chosen for
        the PR, side by side, then do each in this process in turn, its reviewer doing `reviewer`.

        Returns:
            The review runs, closed, in the order they started.
        """
        assert command[:3] == ["canopy", "review", "run"], command
        done: list[Reviewed] = []
        with ExitStack() as stack:
            if reviewer is not None:
                stack.enter_context(reviewer)
            with in_tick(self.conn) as tick_id:
                exited = main(command[1:], runner=InlineRunner())
                if exited != 0:
                    self._tell(f"tick {tick_id} does not start {shlex.join(command)}", tick_id)
                assert exited == 0, db.decisions_for_tick(self.conn, tick_id)
                db.finish_tick(self.conn, tick_id, TickStatus.OK, "test")
                started = self.conn.execute("SELECT id FROM review_runs WHERE tick_id = ? ORDER BY id", (tick_id,))
                ids = [int(r[0]) for r in started]
            for run_id in ids:
                argv = ["_review", str(run_id)]
                exited, printed = _printing(lambda argv=argv: main(argv, runner=InlineRunner()))
                row = present(review_runs.get_review_run(self.conn, run_id))
                reviewed = Reviewed(row, self.env.state_dir / "reviews" / f"{run_id}.prompt", printed)
                self.story.append(str(reviewed) if exited == 0 else f"{reviewed}, and `canopy _review` exits {exited}")
                assert exited == 0, reviewed
                done.append(reviewed)
        return done

    def starts_review(self, command: list[str], *, reviewer: Worker | None = None) -> Reviewing:
        """Start the review `command`, a `reviews(...)` or a `revises(...)`, in a tick of its own, and hold its
        reviewer at work, the reviewer set to do `reviewer`, a `reviewer_reports(...)`, once the test lets it go on.

        The review run is detached, as the overseer's is, and the overseer is not run.

        Returns:
            The review run, at work.
        """
        assert command[:3] in REVIEW_COMMANDS, command
        with ExitStack() as stack:
            if reviewer is not None:
                stack.enter_context(reviewer)
            stack.enter_context(self._held())
            with in_tick(self.conn) as tick_id:
                exited = main(command[1:])
                if exited != 0:
                    self._tell(f"tick {tick_id} does not start {shlex.join(command)}", tick_id)
                assert exited == 0, db.decisions_for_tick(self.conn, tick_id)
                db.finish_tick(self.conn, tick_id, TickStatus.OK, "test")
                run_id = int(self.conn.execute("SELECT max(id) FROM review_runs").fetchone()[0])
        reviewing = self._reviewing(run_id)
        self.story.append(str(reviewing))
        return reviewing

    def refuses(self, command: list[str], *, dry_run: bool = False) -> Refused:
        """Dispatch `command`, a `dispatches(...)`, or start the review `command`, a `reviews(...)` or a
        `revises(...)`, in a tick of its own, which canopy must refuse, starting no run.

        Returns:
            The tick's decisions, as (action, rationale): the refusal, and the attention it raised, if any; the tick,
            its decisions whole, and what the command printed ride along.
        """
        review = command[:3] in REVIEW_COMMANDS
        assert review or command[:2] == ["canopy", "dispatch"], command
        with in_tick(self.conn, dry_run=dry_run, ends_ok=True) as tick_id:
            exited, printed = _printing(lambda: main(command[1:], runner=InlineRunner()))
        refused = Refused(tick=tick_id, made=db.decisions_for_tick(self.conn, tick_id), printed=printed)
        self._tell(f"tick {tick_id} {'refuses' if exited == 1 else 'does not refuse'} {shlex.join(command)}", tick_id)
        assert exited == 1, f"{shlex.join(command[:3])} exited {exited}, not refused: {list(refused)} {printed.err}"
        # The table's name is one of two literals.
        runs = "review_runs" if review else "runs"
        started = self.conn.execute(f"SELECT count(*) FROM {runs} WHERE tick_id = ?", (tick_id,)).fetchone()[0]  # noqa: S608
        assert started == 0, list(refused)
        return refused

    def polls(self) -> None:
        """The connectors read the world between ticks, as the loop's poll does (DESIGN §6): a PR a run opened is then
        observed, as the next tick's sources would observe it before its dispatches rest on it (DESIGN §35)."""
        assert poll.run(context(self.env), logs.for_tick(None)) is not None, "a tick holds the lock"
        self.story.append("the connectors poll")

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
            "AND sql NOT LIKE 'CREATE VIRTUAL%'",
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

    def overseer(self, *args: str, code: int = 0, dry_run: bool = False) -> Printed:
        """Run one of the overseer's commands, `canopy ARGS`, in the tick `ticking` holds open, or in a tick of its own
        that ends ok, a dry run with `dry_run`; it must exit `code`.

        Returns:
            What it printed, as the overseer would read it.
        """
        command = shlex.join(["canopy", *args])
        with ExitStack() as stack:
            tick_id = self.open_tick
            if tick_id is None:
                tick_id = stack.enter_context(in_tick(self.conn, dry_run=dry_run, ends_ok=True))
            else:
                assert not dry_run, "a command in the tick `ticking` holds open runs as that tick does"
            exited, printed = _printing(lambda: main(list(args)))
        said = f"the overseer runs {command} in tick {tick_id}, which exits {exited}"
        self.story.append("\n".join([said, *printed.told()]))
        assert exited == code, f"{command} exited {exited}, not {code}: {printed.err or printed.out}"
        return printed

    @contextmanager
    def ticking(self, *, dry_run: bool = False) -> Iterator[int]:
        """Hold a tick open for the overseer's commands, a dry run with `dry_run`: each `overseer` move inside the block
        runs in it, the test may look at the tick while it is still running, and it ends ok as the block does, as one
        whose overseer finished, so what they raised is the attention list.

        Yields:
            The tick's id.
        """
        assert self.open_tick is None, f"tick {self.open_tick} is open already"
        with in_tick(self.conn, dry_run=dry_run, ends_ok=True) as tick_id:
            dry = "dry-run " if dry_run else ""
            self.story.append(f"{dry}tick {tick_id} begins, for the overseer's commands")
            self.open_tick = tick_id
            try:
                yield tick_id
            finally:
                self.open_tick = None
        self.story.append(f"tick {tick_id} ends ok")

    def configures(self, file: ConfigFile = "user", /, **tables: Mapping[str, object]) -> None:
        """Set the keys of each table in `tables`, named as in TOML, in the config `file`; the next command reads them.

        A key set takes the place of the one there, and every other key stays, whatever table it is in, so a test sets
        only what its story is about: `configures(policy={"max_resume_attempts": 2})`, or a table inside another as a
        mapping inside one, `configures(notify={"sinks": {"slack": {"cmd": "true"}}})`. A key set to None is dropped,
        a table with it: `configures(notify={"sinks": {"slack": None}})`.
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
        """Stop what is left of every run held at work, its `canopy _run` and its worker both, and of every review run,
        its `canopy _review` and its reviewer, as the test ends."""
        for run_id in self.held:
            row = present(db.get_run(self.conn, run_id))
            if row["status"] == RunStatus.RUNNING:
                for pid in (row["pid"], row["worker_pid"]):
                    if pid is not None:
                        procs.kill_group(int(pid))
        for run_id in self.held_reviews:
            review = present(review_runs.get_review_run(self.conn, run_id))
            if review.status == ReviewRunStatus.RUNNING:
                for pid in (review.pid, review.agent_pid):
                    if pid is not None:
                        procs.kill_group(pid)

    def _tell(self, step: str, tick_id: int) -> None:
        self.story.append("\n".join([step, *map(_decided, db.decisions_for_tick(self.conn, tick_id))]))

    @contextmanager
    def _held(self) -> Iterator[None]:
        # Each role's script is in its environment by now; GATE goes first in it. A run reads the environment as it
        # starts, so the gate lasts as long as the run does.
        self.gates.mkdir(exist_ok=True)
        gate = [sys.executable, "-c", GATE, str(self.gates)]
        env: dict[str, str] = {}
        for role in HELD_ROLES:
            script = os.environ.get(f"FAKE_{role}_COMMANDS", os.environ.get("FAKE_AGENT_COMMANDS", "[]"))
            env[f"FAKE_{role}_COMMANDS"] = json.dumps([gate, *json.loads(script)])
            # A ticket's own script stands in for the role's, commands and all, so its commands are gated too.
            tickets: dict[str, dict[str, str]] = json.loads(os.environ.get(f"FAKE_{role}_FOR", "{}"))
            for settings in tickets.values():
                if "COMMANDS" in settings:
                    settings["COMMANDS"] = json.dumps([gate, *json.loads(settings["COMMANDS"])])
            if tickets:
                env[f"FAKE_{role}_FOR"] = json.dumps(tickets)
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

    def _reviewing(self, run_id: int) -> Reviewing:
        self.held_reviews.append(run_id)
        working = self.gates / f"review-{run_id}.working"
        deadline = time.monotonic() + HOLD_TIMEOUT
        while True:
            review = present(review_runs.get_review_run(self.conn, run_id))
            # The reviewer's pid too, which `_review` records as it starts the reviewer, so `close` knows what to stop.
            if working.exists() and review.agent_pid is not None:
                break
            assert review.status == ReviewRunStatus.RUNNING, f"{_reviewed(review)}: {review.status} before at work"
            assert time.monotonic() < deadline, f"review run {run_id}'s reviewer was not at work after {HOLD_TIMEOUT}s"
            time.sleep(0.02)
        return Reviewing(self, run_id)


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
) -> list[str]:
    """The overseer dispatches a run of `key` in `repo`, by default an `implement` under the test operator's label.

    `repo` is one repository, or several for a joint run, in `ws_scenario`'s workspace of two. Pass `label=None` for a
    ticket the operator started, which needs none.
    """
    repos = [repo] if isinstance(repo, str) else list(repo)
    flags = [arg for name in repos for arg in ("--repo", name)] + ["--kind", str(kind)]
    flags += _option("--label", label) + _option("--slug", slug) + _option("--base", base)
    flags += _option("--review-run", None if review_run is None else str(review_run))
    for reason in reasons:
        flags += ["--reason", str(reason)]
    for name, value in (cursors or {}).items():
        flags += ["--cursor", f"{name}={value}"]
    flags += _option("--context", context)
    return canopy("dispatch", key, *flags)


def reviews(
    sha: str,
    pr: str = PR,
    *,
    repo: str = "repo",
    ticket: str | None = None,
    context: str | None = None,
) -> list[str]:
    """The overseer starts a review of `pr` at `sha` in `repo`, of `ticket`'s PR if given, with `context` for the
    reviewer."""
    flags = _option("--ticket", ticket) + _option("--context", context)
    return canopy("review", "run", "--pr", pr, "--sha", sha, "--repo", repo, *flags)


def revises(review_run: int) -> list[str]:
    """The overseer starts a revision of review run `review_run`'s draft, which the operator's note asks for."""
    return canopy("review", "revise", "--run", str(review_run))


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
    branch: str | None = None,
    message: str | None = None,
    *,
    repos: Sequence[str] = (),
    **reported: object,
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
        if "prs" in reported:
            # A result names its PRs one way: the joint `prs`, which a test may give for one repository too.
            result.pop("pr", None)
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


def sends_drafts(entries: object, *, pr: str = DRAFTS_PR) -> Script:
    """The worker pushes its ticket's branch and reports it done with `pr` open in `repo`, sending `entries` as its
    drafts, whatever they hold, so a test can send ones canopy refuses."""
    return pushes(prs={"repo": pr}, drafts=entries)


def with_a_pr(scenario: Scenario, *, approve: bool = True) -> None:
    """KEY's implement pushes its branch and opens DRAFTS_PR; with `approve`, feedback plans are on, and alice is
    trusted (DESIGN §32)."""
    scenario.run(dispatches(slug="work"), worker=pushes(prs={"repo": DRAFTS_PR}))
    if approve:
        scenario.configures("private", policy={"feedback_plan": "approve"}, trust={"trusted_reviewers": ["alice"]})


def github_shows(
    state: Path,
    *reviews: dict[str, Any],
    head: str = FEEDBACK_HEAD,
    checks: Sequence[Mapping[str, object]] = (FEEDBACK_RED,),
    mergeable: str = "mergeable",
) -> None:
    """Make the fake GitHub hold DRAFTS_PR at `head`, by `me`, with `reviews` on it, `checks` at its head, and
    `mergeable`."""
    shown = {"pr": {"head_sha": head, "mergeable": mergeable}, "reviews": list(reviews), "checks": list(checks)}
    state.write_text(json.dumps({"prs": {DRAFTS_PR: shown}}))


def feedback_planned(
    scenario: Scenario,
    github_state: Path,
    result: object = None,
    *,
    mergeable: str = "mergeable",
) -> int:
    """A feedback plan run on alice's and bob's comments, `build` red, that writes FEEDBACK_TEXT and reports `result`,
    FEEDBACK_PLANNED by default.

    Returns:
        Its run id.
    """
    github_shows(github_state, ALICES_COMMENT, BOBS_COMMENT, mergeable=mergeable)
    line = FEEDBACK_PLANNED if result is None else result
    assert isinstance(line, dict)
    worker = planner_does(["cat", feedback_items.ITEMS], plan=FEEDBACK_TEXT, result=line)
    run = scenario.run(dispatches(kind=RunKind.FEEDBACK_PLAN), worker=worker)
    assert run.status == RunStatus.DONE, run
    return run.id


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


def _reviewed(row: records.ReviewRun) -> str:
    ticket = f" for {row.ticket_key}" if row.ticket_key else ""
    return f"review run {row.id} of {row.pr_url} at {row.sha[:7]}{ticket}"


def _killed(pid: int, what: str) -> None:
    procs.kill_group(pid)
    deadline = time.monotonic() + HOLD_TIMEOUT
    while procs.alive(pid):
        assert time.monotonic() < deadline, f"{what} outlived its kill"
        time.sleep(0.02)


def _decided(decision: records.Decision) -> str:
    return f"  {decision.ticket_key or '-'} {decision.action}: {decision.rationale}"


def _option(name: str, value: str | None) -> list[str]:
    return [name, value] if value is not None else []


def _shift(conn: sqlite3.Connection, table: str, column: str, modifier: str) -> None:
    # The names come from the journal's own schema; strftime writes the shape `db.format_time` does, and a value it
    # cannot read as a time is left alone.
    moved = f"strftime('%Y-%m-%dT%H:%M:%fZ', {column}, ?)"
    conn.execute(f'UPDATE "{table}" SET {column} = {moved} WHERE {moved} IS NOT NULL', (modifier, modifier))  # noqa: S608
