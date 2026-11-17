"""A tick records each run of its overseer (DESIGN §40, ROADMAP M40 stage 2).

A tick makes one run today, given the whole state block, so its run's subject is None, and the run keeps what the tick
keeps of it: its session, the model it asked for, and its cost, with how it ended.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.core import db, overseer_runs, records
from canopy.core.vocab import OverseerRunStatus, TickStatus
from canopy.runtime import stdout
from tests.canopy.helpers import KEY, in_tick, present, waits, with_events

if TYPE_CHECKING:
    import sqlite3

    from tests.canopy.scenario_helpers import Scenario, Ticked


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_tick_that_runs_its_overseer_records_one_run_given_the_whole_block(
    scenario: Scenario,
    dry_run: bool,  # noqa: FBT001
) -> None:
    # A dry run runs its overseer, and keeps what it cost, as a live tick does.
    with_events(scenario.env, "canopy-overseer")
    ticked = scenario.tick(*waits(KEY), session="ses_o1", dry_run=dry_run)
    [run] = runs_of(scenario.conn, ticked)
    assert (run.subject, run.status, run.failure, run.session_id) == (None, OverseerRunStatus.OK, None, "ses_o1")
    assert run.ended_at is not None
    assert (run.cost_usd, run.model) == (0.25, ticked.tick.model)
    assert db.usage_of(run) == db.usage_of(ticked.tick)


def test_a_failed_overseer_run_says_why_and_keeps_what_it_cost(scenario: Scenario) -> None:
    with_events(scenario.env, "canopy-overseer")
    ticked = scenario.tick(*waits(KEY), result="I got distracted", session="ses_o1", code=1)
    assert ticked.tick.status == TickStatus.OVERSEER_FAILED
    [run] = runs_of(scenario.conn, ticked)
    assert (run.status, run.failure) == (
        OverseerRunStatus.FAILED,
        "overseer's final message has no CANOPY_TICK_DONE line",
    )
    assert (run.session_id, run.cost_usd) == ("ses_o1", 0.25)


def test_an_overseer_that_could_not_start_is_a_failed_run(scenario: Scenario) -> None:
    # The runtime would read the workspace's own definition of the overseer, so canopy starts none (D044).
    (scenario.env.root / "opencode.json").write_text('{"agent": {"canopy-overseer": {}}}')
    ticked = scenario.tick(*waits(KEY), code=1)
    assert ticked.tick.overseer_ran == 1
    [run] = runs_of(scenario.conn, ticked)
    assert run.status == OverseerRunStatus.FAILED
    assert "defines one of canopy's agents" in present(run.failure)
    assert (run.session_id, run.cost_usd) == (None, None)


def test_a_run_that_leaves_a_duty_undone_says_which(scenario: Scenario) -> None:
    scenario.seen(KEY)
    ticked = scenario.tick(code=1)
    [run] = runs_of(scenario.conn, ticked)
    assert (run.status, run.failure) == (
        OverseerRunStatus.UNDONE,
        f"overseer left duties undone: no decision for {KEY}",
    )
    assert ticked.tick.summary == run.failure


def test_a_tick_that_runs_no_overseer_records_no_run(scenario: Scenario) -> None:
    # No ticket listed, and the query the `tracker` source's to read: nothing is left to judge (DESIGN §39).
    quiet = scenario.tick()
    assert quiet.tick.overseer_ran == 0
    assert runs_of(scenario.conn, quiet) == []


def test_a_halted_tick_records_no_run(scenario: Scenario) -> None:
    scenario.seen(KEY)
    scenario.configures(loop={"min_free_disk_mib": 2**40})  # more than any disk the tests run on has free
    halted = scenario.tick(code=1)
    assert (halted.tick.status, halted.tick.overseer_ran) == (TickStatus.DISK_LOW, False)
    assert runs_of(scenario.conn, halted) == []


def test_a_run_its_tick_raised_in_fails_with_the_tick(scenario: Scenario) -> None:
    with mock.patch.object(stdout, "read", autospec=True, side_effect=RuntimeError("unreadable")):
        ticked = scenario.tick(*waits(KEY), code=1)
    assert ticked.tick.status == TickStatus.ERROR
    [run] = runs_of(scenario.conn, ticked)
    assert (run.status, run.failure) == (OverseerRunStatus.FAILED, "RuntimeError: unreadable")
    assert run.ended_at is not None


def test_a_run_a_dead_tick_left_running_is_closed_abandoned_by_the_next(scenario: Scenario) -> None:
    with in_tick(scenario.conn) as dead:
        overseer_runs.start(scenario.conn, dead)
    scenario.tick(*waits(KEY))
    [run] = of_tick(scenario.conn, dead)
    assert (run.status, run.failure) == (OverseerRunStatus.ABANDONED, None)
    assert run.ended_at is not None


def runs_of(conn: sqlite3.Connection, ticked: Ticked) -> list[records.OverseerRun]:
    """The overseer runs the tick `ticked` recorded, in the order it started them."""
    return of_tick(conn, ticked.tick.id)


def of_tick(conn: sqlite3.Connection, tick_id: int) -> list[records.OverseerRun]:
    """The overseer runs tick `tick_id` recorded, in the order it started them."""
    return records.select(records.OverseerRun).where("tick_id = ?", tick_id).order_by("id").all(conn)
