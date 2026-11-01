"""Each ticket plan's measurements, cached in the journal's `plan_metrics` (DESIGN §25), for the Plans report.

A plan is measured once, from its original, the copy kept as its planner wrote it (`plans`), by `plan_metrics`: when
its run records it (`keep`), and for any plan without a row of the current model's version, by the live tick, a few
at a time (`fill`): plans recorded before the cache, and every plan again when the model changes. A plan that cannot be
measured, its original gone or not the file written, keeps a row saying why, so it is not tried again.

A read never writes: `read` measures a plan with no current row from its file, as `fill` would, without keeping it, so
the report is right before the tick catches up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, plan_metrics, plans, records

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence
    from pathlib import Path

#: How many plans one live tick measures at most, so a journal of many plans fills over a few ticks, not in one.
FILL_LIMIT = 50
#: Why a plan could not be measured when its original is not the file its planner wrote, by its hash.
CHANGED = "changed"


def read(conn: sqlite3.Connection, state_dir: Path, written: Sequence[records.Plan]) -> dict[int, plan_metrics.Metrics]:
    """The measurements of the plans `written`, by id, from the cache, or from each file where it has none current.

    Returns:
        Each measured plan's measurements; a plan that could not be measured has none.
    """
    cached = {
        m.plan_id: m
        for m in records.select(records.PlanMetric)
        .where_in("plan_id", [p.id for p in written])
        .where("version = ?", plan_metrics.VERSION)
        .all(conn)
    }
    found: dict[int, plan_metrics.Metrics] = {}
    for plan in written:
        row = cached.get(plan.id)
        measured = _measure(state_dir, plan) if row is None else _metrics(row)
        if isinstance(measured, plan_metrics.Metrics):
            found[plan.id] = measured
    return found


def keep(conn: sqlite3.Connection, plan_id: int, text: str) -> plan_metrics.Metrics:
    """Measure the plan `plan_id` from `text`, as its planner wrote it, and keep its row, replacing any it had.

    Returns:
        Its measurements.
    """
    measured = plan_metrics.measure(text)
    with db.transaction(conn):
        _row(plan_id, measured).run(conn)
    return measured


def fill(conn: sqlite3.Connection, state_dir: Path, *, limit: int = FILL_LIMIT) -> int:
    """Measure up to `limit` plans with no row of the current model's version, the newest first, and keep their rows.

    Returns:
        How many it measured, those that could not be measured included.
    """
    due = (
        records.select(records.Plan)
        .where("id NOT IN (SELECT plan_id FROM plan_metrics WHERE version = ?)", plan_metrics.VERSION)
        .order_by("id DESC")
        .limit(limit)
        .all(conn)
    )
    for plan in due:
        measured = _measure(state_dir, plan)
        with db.transaction(conn):
            _row(plan.id, measured).run(conn)
    return len(due)


# A plan measured from its original; else why it could not be: its original's problem, or `CHANGED`.
def _measure(state_dir: Path, plan: records.Plan) -> plan_metrics.Metrics | str:
    path = plans.path_for(state_dir, plan.ticket_key, plan.run_id).with_name(plans.original_name(plan.run_id))
    reading = plans.read(path)
    if reading.text is None:
        return reading.problem or "unreadable"
    if reading.sha256 != plan.sha256:
        return CHANGED
    return plan_metrics.measure(reading.text)


def _row(plan_id: int, measured: plan_metrics.Metrics | str) -> records.Insert[records.PlanMetric]:
    if isinstance(measured, str):
        return records.insert(
            records.PlanMetric,
            plan_id=plan_id,
            version=plan_metrics.VERSION,
            measured_at=db.now(),
            problem=measured,
        ).or_replace()
    return records.insert(
        records.PlanMetric,
        plan_id=plan_id,
        version=plan_metrics.VERSION,
        measured_at=db.now(),
        words=measured.words,
        lines=measured.lines,
        code_blocks=measured.code_blocks,
        tables=measured.tables,
        diagrams=measured.diagrams,
    ).or_replace()


# A row's measurements; its problem when it has one. The table's check keeps every measurement set when it has none.
def _metrics(row: records.PlanMetric) -> plan_metrics.Metrics | str:
    if row.problem is not None:
        return row.problem
    match (row.words, row.lines, row.code_blocks, row.tables, row.diagrams):
        case (int() as words, int() as lines, int() as code_blocks, int() as tables, int() as diagrams):
            return plan_metrics.Metrics(
                words=words,
                lines=lines,
                code_blocks=code_blocks,
                tables=tables,
                diagrams=diagrams,
            )
        case _:
            return "unreadable"
