"""Scenarios: a ticket's story told in a few lines, played against the fakes.

A scenario test reads the way an entry in docs/SCENARIOS.md does: the overseer ticks and decides, workers run and push,
the operator replies, and the test checks what canopy did. The `scenario` fixture's `Scenario` tells the story; the
functions below it are the moves in it, the overseer's (`dispatches`, `raises`, `sets_phase`, and `waits` from
`helpers.py`) and a worker's (`pushes`, `asks`, or any `*_does` helper). Each is a helper of `helpers.py` with the
plumbing folded in: a tick's exit code checked, the runs it started waited for, a dispatch's flags spelled as keywords.

    def test_a_red_check_resumes_the_branch(scenario: Scenario, git_pool: GitPool) -> None:
        scenario.run(worker=pushes())
        ticked = scenario.tick(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI]), worker=pushes())
        assert ticked.actions == ["queried", "dispatch:resume"]

A step the verbs do not cover is written as before, in the same test: the verbs are argv lists and context managers, so
they mix with `canopy(...)`, `overseer_does`, and the journal's own queries.
"""

import json
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from canopy.cli.main import main
from canopy.core import db, records
from canopy.core.vocab import Phase, ResumeReason, RunKind, TickStatus
from tests.canopy.helpers import (
    BRANCH,
    KEY,
    LABEL,
    QUESTION,
    WORKER_DONE,
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


@dataclass(frozen=True)
class Scenario:
    """A workspace of one repository, `repo`, where a test plays the overseer, the workers, and the operator in turn."""

    env: CanopyEnv
    conn: sqlite3.Connection
    agent_log: Path

    def tick(self, *commands: list[str], worker: Worker | None = None, dry_run: bool = False, code: int = 0) -> Ticked:
        """Run one tick, `canopy tick`, its overseer running `commands`, and wait for each run it dispatches to end.

        Each run's worker does `worker`, the fake's default `done` if None. The tick must exit `code`.

        Returns:
            What the tick did.
        """
        argv = ["tick", "--dry-run"] if dry_run else ["tick"]
        with ExitStack() as stack:
            stack.enter_context(overseer_does(*commands))
            if worker is not None:
                stack.enter_context(worker)
            assert main(argv) == code
            tick = last_tick(self.conn)
            started = self.conn.execute("SELECT id FROM runs WHERE tick_id = ? ORDER BY id", (tick.id,)).fetchall()
            # A run is detached from the tick, so the worker's script must last until it ends.
            runs = [wait_for_run(self.conn, int(r["id"])) for r in started]
        return Ticked(present(db.get_tick(self.conn, tick.id)), db.decisions_for_tick(self.conn, tick.id), runs)

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

    def ticket_state(self, key: str = KEY) -> dict[str, Any]:
        """The ticket `key` as the latest overseer's state block carried it."""
        [found] = [t for t in state_block(self.agent_log)["tickets"] if t["key"] == key]
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
