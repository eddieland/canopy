"""The tick starts every run the overseer asks for, once its run has ended (DESIGN §40, ROADMAP M40 stage 1)."""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import db, records, sql
from canopy.core.vocab import Decider, RecordedStatus, ResumeReason, RunKind, TickStatus
from canopy.infra import procs
from canopy.loop import harness_dispatches, spawns
from canopy.runs import policy
from tests.canopy.helpers import (
    KEY,
    LABEL,
    Called,
    InlineRunner,
    agent_runs,
    ancestors,
    calls,
    canopy,
    chore_reports,
    in_tick,
    present,
    tracker_holds,
    wait_for_run,
    waits,
)
from tests.canopy.review_helpers import CLEAN, head, reviewer_reports
from tests.canopy.scenario_helpers import chores_ended, dispatches, due_chore, pushes, reviews

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import CanopyEnv, GitPool

#: A chore with no `when`, which the harness runs (DESIGN §37), and one with a `when`, which the overseer decides.
MINE, THEIRS = "deps", "build-health"
#: What the fake overseer runs after its asks: how many runs of each kind the journal holds then, and how many are
#: recorded and not yet started.
COUNTS = (
    "import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); "
    "print(*(c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('runs', 'review_runs', 'chore_runs')), "
    "c.execute(\"SELECT count(*) FROM recorded_runs WHERE status = 'recorded'\").fetchone()[0])"
)


@pytest.mark.usefixtures("git_pool")
@pytest.mark.parametrize("door", ["tool", "command"])
def test_a_dispatch_starts_once_the_overseer_has_exited_in_order_with_the_harnesss(
    scenario: Scenario,
    door: Literal["tool", "command"],
) -> None:
    scenario.run(dispatches("PROJ-2"), worker=pushes())
    due_chore(scenario, MINE)
    implement = {"key": KEY, "kind": "implement", "label": LABEL, "repos": ["repo"]}
    resume = {"key": "PROJ-2", "kind": "resume", "label": LABEL, "repos": ["repo"], "reasons": ["conflict"]}
    asks: list[list[str] | Called] = (
        [calls("canopy_dispatch", **implement), calls("canopy_dispatch", **resume)]
        if door == "tool"
        else [dispatches(), dispatches("PROJ-2", RunKind.RESUME, reasons=[ResumeReason.CONFLICT])]
    )
    with chore_reports({"status": "ok", "summary": "fine", "findings": []}):
        ticked = scenario.tick(*asks, counts(scenario.env), hold=True)
        # While the overseer ran, after its asks, nothing it asked for had started: both were recorded.
        assert overseer_said(scenario.agent_log) == "1 0 0 2"
        # Started after it, in §7's order: the resume, a repair, before the implement asked first, then the
        # harness's chore, after every run.
        started = [(d.ticket_key, d.chore, d.action, d.decider) for d in ticked.decisions if "dispatch:" in d.action]
        assert started == [
            ("PROJ-2", None, "dispatch:resume", Decider.OVERSEER),
            (KEY, None, "dispatch:implement", Decider.OVERSEER),
            (None, MINE, "dispatch:chore", Decider.HARNESS),
        ]
        assert [w.row["ticket_key"] for w in ticked.working] == ["PROJ-2", KEY]
        for working in ticked.working:
            # Each `_run` is the tick's child, not the overseer's descendant, and runs on now the overseer is gone.
            assert ancestors(int(working.row["pid"]))[0] == os.getpid()
            assert procs.alive(int(working.row["pid"]))
        assert [r.status for r in recorded_of(scenario.conn, ticked.tick.id)] == [RecordedStatus.STARTED] * 2
        assert ticked.tick.status == TickStatus.OK
        for working in ticked.working:
            working.finishes()
        chores_ended(scenario.conn)


@pytest.mark.usefixtures("git_pool")
def test_a_review_and_a_chore_the_overseer_starts_run_after_its_run_and_outside_its_tree(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    due_chore(scenario, THEIRS, when="Weekdays only.")
    sha = head(git_pool)
    with (
        reviewer_reports(CLEAN, sleep=60),
        chore_reports({"status": "ok", "summary": "fine", "findings": []}, sleep=60),
    ):
        ticked = scenario.tick(reviews(sha, ticket=KEY), canopy("chore", "run", THEIRS), counts(reviewing))
        assert overseer_said(scenario.agent_log) == "0 0 0 2"
        assert [d.action for d in ticked.decisions if "dispatch:" in d.action] == ["dispatch:review", "dispatch:chore"]
        with alive(scenario.conn, "review_runs") as review, alive(scenario.conn, "chore_runs") as chore:
            for pid in (review, chore):
                assert ancestors(pid)[0] == os.getpid()


@pytest.mark.usefixtures("git_pool")
def test_a_recorded_run_holds_its_ticket_and_its_worker_in_every_count(scenario: Scenario) -> None:
    scenario.configures(capacity={"max_workers": 2})
    with scenario.ticking():
        scenario.overseer(*dispatches()[1:])
        second = scenario.overseer(*dispatches()[1:], code=1)
        assert "refused (running): recorded run 1 is already PROJ-1's one run" in second.err
        # The harness's runs to come hold a worker ahead of this one: with the recorded run, none is left.
        with mock.patch.object(harness_dispatches, "reserved", autospec=True, return_value=1):
            held = scenario.overseer(*dispatches("PROJ-2")[1:], code=1)
        assert "refused (reserved): 1 of 2 workers are free" in held.err
        scenario.configures(capacity={"max_workers": 1})
        full = scenario.overseer(*dispatches("PROJ-2")[1:], code=1)
        assert "1 of 1 workers are running, counting 1 recorded for the tick to start after the overseer" in full.err
        assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    wait_for_run(scenario.conn, 1)


@pytest.mark.usefixtures("git_pool")
@pytest.mark.parametrize(("change", "guard"), [("stop", "stopped"), ("notice", "notice_changed")])
def test_a_recorded_run_whose_ground_moved_before_the_spawn_is_refused_then(
    scenario: Scenario,
    change: str,
    guard: str,
) -> None:
    # A ticket the operator stops is one they started (DESIGN §22).
    label = None if change == "stop" else LABEL
    if label is None:
        scenario.operator("start", KEY)
    scenario.run(dispatches(label=label))
    with scenario.ticking() as tick_id:
        # The tick read the journal before the operator moved.
        scenario.conn.execute("UPDATE ticks SET read_at = ? WHERE id = ?", ("2026-01-01T00:00:00.000Z", tick_id))
        scenario.overseer(*dispatches(kind=RunKind.RESUME, label=label, reasons=[ResumeReason.CI])[1:])
        if change == "stop":
            scenario.operator("stop", KEY)
        else:
            scenario.operator("notice", "CI is down.")
    assert [(d.ticket_key, d.action) for d in db.decisions_for_tick(scenario.conn, tick_id)] == [
        (KEY, f"refused:{guard}"),
    ]
    [recorded] = recorded_of(scenario.conn, tick_id)
    assert (recorded.status, recorded.run_id) == (RecordedStatus.REFUSED, None)
    assert scenario.conn.execute("SELECT count(*) FROM runs WHERE tick_id = ?", (tick_id,)).fetchone()[0] == 0


@pytest.mark.usefixtures("git_pool")
def test_a_run_a_dead_tick_recorded_is_closed_unstarted_by_the_next_and_counts_toward_no_limit(
    scenario: Scenario,
) -> None:
    scenario.configures("workspace", policy={"max_implement_attempts": 1})
    # The tick's process dies after the ask: its row stays running, its run recorded.
    tracker_holds(scenario.conn)
    with in_tick(scenario.conn) as dead:
        assert main(dispatches()[1:], runner=InlineRunner()) == 0
    assert [r.status for r in recorded_of(scenario.conn, dead)] == [RecordedStatus.RECORDED]
    ticked = scenario.tick(dispatches(), worker=pushes())
    assert present(db.get_tick(scenario.conn, dead)).status == TickStatus.ABANDONED
    [unstarted] = recorded_of(scenario.conn, dead)
    assert (unstarted.status, unstarted.run_id) == (RecordedStatus.UNSTARTED, None)
    assert unstarted.closed_at is not None
    # No later tick started it, and it spent no attempt: the next tick's own dispatch, at a limit of one, ran.
    assert scenario.conn.execute("SELECT count(*) FROM runs WHERE tick_id = ?", (dead,)).fetchone()[0] == 0
    [run] = ticked.runs
    assert (run.key, run.status) == (KEY, "done")
    assert policy.attempts(scenario.conn)[policy.unit(KEY, "repo")][RunKind.IMPLEMENT] == 1


def test_a_run_its_tick_did_not_start_is_closed_unstarted_as_the_tick_closes(scenario: Scenario) -> None:
    with mock.patch.object(spawns, "make", autospec=True, side_effect=RuntimeError("no spawns today")):
        # A dispatch's decision is recorded as it starts: the wait is what this tick owes its ticket (DESIGN §40).
        ticked = scenario.tick(*waits(KEY), dispatches())
    # What raised is logged, never the tick's outcome; the next tick decides the ticket again.
    assert ticked.tick.status == TickStatus.OK
    [recorded] = recorded_of(scenario.conn, ticked.tick.id)
    assert recorded.status == RecordedStatus.UNSTARTED
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_a_dry_run_records_no_run(scenario: Scenario) -> None:
    ticked = scenario.tick(dispatches(), dry_run=True)
    assert ticked.actions[-1] == "dispatch:implement"
    assert scenario.conn.execute("SELECT count(*) FROM recorded_runs").fetchone()[0] == 0


def counts(env: CanopyEnv) -> list[str]:
    """The command the fake overseer runs to print `COUNTS` of `env`'s journal."""
    return [sys.executable, "-c", COUNTS, str(env.state_dir / db.DB_FILE_NAME)]


def overseer_said(agent_log: Path) -> str:
    """What the latest fake overseer's last command printed, stripped."""
    overseers = [run for run in agent_runs(agent_log) if run["argv"][:3] == ["run", "--agent", "canopy-overseer"]]
    return str(overseers[-1]["commands"][-1]["stdout"]).strip()


def recorded_of(conn: sqlite3.Connection, tick_id: int) -> list[records.RecordedRun]:
    """Every run tick `tick_id` recorded, whatever became of it."""
    query = sql.select("*").from_("recorded_runs").where("tick_id = ?", tick_id).order_by("id")
    return records.fetch_all(conn, records.RecordedRun, query)


@contextmanager
def alive(conn: sqlite3.Connection, table: Literal["review_runs", "chore_runs"]) -> Iterator[int]:
    """Run 1 of `table` while it runs, its agent started, and then its process and its agent stopped.

    Yields:
        The pid of its own process, `canopy _review` or `canopy _chore`.
    """
    query = sql.select("pid, agent_pid, log_path").from_("{}", sql.name(table)).where("id = 1")
    deadline = time.monotonic() + 30
    row = sql.execute(conn, query).fetchone()
    while (row is None or row["agent_pid"] is None) and time.monotonic() < deadline:
        time.sleep(0.05)
        row = sql.execute(conn, query).fetchone()
    assert row is not None
    assert row["agent_pid"] is not None, f"{table} 1 never started its agent"
    pid, agent = int(row["pid"]), int(row["agent_pid"])
    try:
        assert procs.running(Path(row["log_path"]), pid)
        yield pid
    finally:
        procs.kill_group(agent)
        procs.kill_group(pid)
