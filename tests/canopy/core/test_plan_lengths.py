"""Each plan's measurements, cached in the journal: kept when recorded, filled by the tick, read by the report."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest import mock

from canopy.core import plan_lengths, plan_metrics, plans, records
from canopy.core.plan_metrics import Metrics
from canopy.core.vocab import RunKind
from tests.canopy.helpers import earlier, worker_ran

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from tests.conftest import CanopyEnv

TEXT = "# Plan\n\nOne step, then another.\n"
MEASURED = Metrics(words=5, lines=3, code_blocks=0, tables=0, diagrams=0)


def test_a_kept_plan_is_read_from_the_journal_not_its_file(conn: sqlite3.Connection, canopy_env: CanopyEnv) -> None:
    """A row kept when the plan is recorded is what the report reads, even once its file is gone."""
    state = canopy_env.state_dir
    plan = recorded(conn, state, "PROJ-1", TEXT)
    assert plan_lengths.keep(conn, plan.id, TEXT) == MEASURED
    original(state, plan).unlink()

    assert plan_lengths.read(conn, state, [plan]) == {plan.id: MEASURED}


def test_a_plan_with_no_row_is_measured_from_its_file_and_nothing_is_written(
    conn: sqlite3.Connection,
    canopy_env: CanopyEnv,
) -> None:
    """Before the tick catches up, the report measures a plan itself, and leaves the journal as it was."""
    state = canopy_env.state_dir
    plan = recorded(conn, state, "PROJ-1", TEXT)

    assert plan_lengths.read(conn, state, [plan]) == {plan.id: MEASURED}
    assert rows(conn) == []


def test_the_tick_fills_the_newest_first_and_keeps_why_a_plan_could_not_be_measured(
    conn: sqlite3.Connection,
    canopy_env: CanopyEnv,
) -> None:
    """A fill measures up to its limit, newest first; a plan whose original is gone or changed is not tried again."""
    state = canopy_env.state_dir
    oldest = recorded(conn, state, "PROJ-1", TEXT)
    gone = recorded(conn, state, "PROJ-2", TEXT)
    changed = recorded(conn, state, "PROJ-3", TEXT)
    original(state, gone).unlink()
    original(state, changed).write_text("# Not the plan written\n")

    assert plan_lengths.fill(conn, state, limit=2) == 2
    assert [(r.plan_id, r.problem) for r in rows(conn)] == [(gone.id, "missing"), (changed.id, plan_lengths.CHANGED)]
    assert plan_lengths.fill(conn, state, limit=2) == 1
    assert plan_lengths.fill(conn, state, limit=2) == 0

    assert {r.plan_id: r.lines for r in rows(conn)} == {oldest.id: MEASURED.lines, gone.id: None, changed.id: None}
    # A plan that could not be measured has no measurements, from the journal or its file.
    assert plan_lengths.read(conn, state, [oldest, gone, changed]) == {oldest.id: MEASURED}


def test_a_row_of_an_older_model_is_measured_again(conn: sqlite3.Connection, canopy_env: CanopyEnv) -> None:
    """Raising the model's version makes every row stale: not read, and measured again by the next fill."""
    state = canopy_env.state_dir
    plan = recorded(conn, state, "PROJ-1", TEXT)
    plan_lengths.keep(conn, plan.id, TEXT)

    with mock.patch.object(plan_metrics, "VERSION", plan_metrics.VERSION + 1):
        original(state, plan).unlink()
        assert plan_lengths.read(conn, state, [plan]) == {}
        assert plan_lengths.fill(conn, state) == 1
        [row] = rows(conn)
        assert (row.version, row.problem) == (plan_metrics.VERSION, "missing")


def recorded(conn: sqlite3.Connection, state: Path, key: str, text: str) -> records.Plan:
    """A plan a plan run on `key` wrote, its files written and its row recorded as a run records it."""
    run_id = worker_ran(conn, RunKind.PLAN, earlier(datetime.now(UTC), 1), key=key)
    return plans.record(conn, key, run_id, plans.write(state, key, run_id, text))


def original(state: Path, plan: records.Plan) -> Path:
    """The copy of `plan` kept as its planner wrote it."""
    return plans.path_for(state, plan.ticket_key, plan.run_id).with_name(plans.original_name(plan.run_id))


def rows(conn: sqlite3.Connection) -> list[records.PlanMetric]:
    """Every plan's cached measurements, by plan."""
    return records.select(records.PlanMetric).order_by("plan_id").all(conn)
