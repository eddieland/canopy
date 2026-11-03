"""Metrics of canopy's agent runs, read from their journal rows: how many ended, how long, what they cost (D132).

A run's metrics are recorded once, where its row is closed and after the transaction that closes it commits, in
whatever process closes it: the run's own, or a tick's reconcile for a run whose process died. So a run that crashed
is counted as one that ended well is, and what is counted is what the journal holds. A tick's overseer runs are
recorded as the tick closes. The runs at work are a gauge the tick sets as it closes.

    canopy.runs            count     role, status, kind (a worker's)    each run that ended
    canopy.run.duration    seconds   role, status                       how long it ran
    canopy.cost            USD       role, model                        what it cost, as the runtime reported
    canopy.tokens          tokens    role, model, type                  its tokens, by type
    canopy.runs.active     gauge     role                               the runs at work as a tick closes
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from canopy.core import records, sql
from canopy.core.vocab import OverseerRunStatus
from canopy.infra import metrics

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.db import RunTable


class Role(StrEnum):
    """Which of canopy's agents a run is, as a metric's `role` label names it."""

    WORKER = "worker"
    TASK = "task"
    REVIEW = "review"
    CHORE = "chore"
    OVERSEER = "overseer"


class TokenType(StrEnum):
    """A kind of token a run spent, as `canopy.tokens`' `type` label names it, each a column of its row."""

    INPUT = "input"
    OUTPUT = "output"
    REASONING = "reasoning"
    CACHE_READ = "cache_read"
    CACHE_WRITE = "cache_write"


#: Each run table's role.
ROLES: Mapping[RunTable, Role] = {
    "runs": Role.WORKER,
    "task_runs": Role.TASK,
    "review_runs": Role.REVIEW,
    "chore_runs": Role.CHORE,
}


def ended(conn: sqlite3.Connection, table: RunTable, run_id: int) -> None:
    """Record the metrics of run `run_id` of `table`, just closed; nothing while metrics are off."""
    if not metrics.enabled():
        return
    row = records.select(records.of_table(table)).where("id = ?", run_id).one(conn)
    if row is not None:
        _meter(ROLES[table], asdict(row))


def overseer_ended(conn: sqlite3.Connection, tick_id: int) -> None:
    """Record the metrics of tick `tick_id`'s overseer runs, all closed as the tick closes."""
    if not metrics.enabled():
        return
    closed = (
        records.select(records.OverseerRun)
        .where("tick_id = ?", tick_id)
        .where("status != ?", OverseerRunStatus.RUNNING)
        .all(conn)
    )
    for row in closed:
        _meter(Role.OVERSEER, asdict(row))


def active(conn: sqlite3.Connection) -> None:
    """Set `canopy.runs.active` to the runs of each role at work now, as a tick closes."""
    if not metrics.enabled():
        return
    for table, role in ROLES.items():
        running = sql.select("count(*)").from_("{}", sql.name(table)).where("status = 'running'")
        metrics.gauge("canopy.runs.active", int(sql.execute(conn, running).fetchone()[0]), role=role)


#: Each token type, by the column that holds it.
_TOKEN_COLUMNS: Mapping[TokenType, str] = {
    TokenType.INPUT: "tokens_input",
    TokenType.OUTPUT: "tokens_output",
    TokenType.REASONING: "tokens_reasoning",
    TokenType.CACHE_READ: "tokens_cache_read",
    TokenType.CACHE_WRITE: "tokens_cache_write",
}


def _meter(role: Role, row: Mapping[str, Any]) -> None:
    """Record one ended run's metrics, from its row's columns."""
    status = row["status"]
    kind = {"kind": row["kind"]} if role is Role.WORKER else {}
    metrics.count("canopy.runs", role=role, status=status, **kind)
    if row["ended_at"] is not None:
        seconds = (_moment(row["ended_at"]) - _moment(row["started_at"])).total_seconds()
        metrics.record("canopy.run.duration", seconds, unit="s", role=role, status=status)
    model = row["model"]
    if row["cost_usd"] is not None:
        metrics.count("canopy.cost", float(row["cost_usd"]), unit="USD", model=model, role=role)
    for token_type, column in _TOKEN_COLUMNS.items():
        if row[column]:
            metrics.count("canopy.tokens", int(row[column]), unit="{token}", model=model, role=role, type=token_type)


def _moment(stamp: str) -> datetime:
    """A time the journal wrote, read as `db.parse_time` reads it: `db` calls this module, so it cannot import `db`.

    Returns:
        The moment, in UTC.
    """
    return datetime.fromisoformat(stamp).astimezone(UTC)
