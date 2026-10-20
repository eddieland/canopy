"""Which models served each agent run, as its session's own record says (DESIGN §13, Each agent's model).

The runtime prints no event naming the model a call went to, so the loop reads the session after the run ends
(`canopy.loop.models`), and records here what it found: each model's replies and their cost (`run_models`), and how the
read ended (`run_model_reads`). `due` is what to read next: runs never read, the newest first, then failed ones again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from canopy.core import db, records, sql
from canopy.core.vocab import ModelsRead

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

    from canopy.runtime.report import ModelUse

#: A table of agent runs, each with a session: a tick's overseer, a worker or plan run, a chore run, a review run.
type RunTable = Literal["ticks", "runs", "chore_runs", "review_runs"]
_TABLES: tuple[RunTable, ...] = ("ticks", "runs", "chore_runs", "review_runs")
#: How long a failed read waits before it is tried again, and how many reads a run gets in all.
RETRY_AFTER = timedelta(days=1)
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class Due:
    """A run whose session is due to be read: never read, or failed and due again."""

    run_table: RunTable
    run_id: int
    session_id: str
    #: The reads it has had: 0 for one never read.
    attempts: int


def due(conn: sqlite3.Connection, *, limit: int, now: datetime | None = None) -> list[Due]:
    """The runs whose sessions are due to be read, at most `limit` of them.

    A run is due once it has ended with a session id: never read, the newest first, so a run that just ended goes
    before history; then one whose last read failed `RETRY_AFTER` ago, with fewer than `MAX_ATTEMPTS` reads.

    Returns:
        The runs, in the order to read them.
    """
    retry_before = db.format_time((now or datetime.now(UTC)) - RETRY_AFTER)
    candidates = sql.union(*(_due_in(table, retry_before) for table in _TABLES), every=True)
    query = (
        sql.select("run_table, run_id, session_id, attempts")
        .from_("({}) AS due", candidates)
        .order_by("attempts, started_at DESC, run_table, run_id")
        .limit(limit)
    )
    return [
        Due(run_table=_table(str(r[0])), run_id=int(r[1]), session_id=str(r[2]), attempts=int(r[3]))
        for r in sql.execute(conn, query)
    ]


def record(
    conn: sqlite3.Connection,
    run: Due,
    status: ModelsRead,
    models: Sequence[ModelUse] = (),
    *,
    error: str | None = None,
) -> None:
    """Record how reading `run`'s session ended, and the models it found, in place of any read before."""
    with db.transaction(conn):
        sql.execute(conn, sql.delete("run_models").where("run_table = ? AND run_id = ?", run.run_table, run.run_id))
        sql.execute_many(
            conn,
            sql.insert_rows("run_models", ("run_table", "run_id", "model", "replies", "cost_usd")),
            [(run.run_table, run.run_id, m.model, m.replies, m.cost_usd) for m in models],
        )
        sql.execute(
            conn,
            sql.insert(
                "run_model_reads",
                run_table=run.run_table,
                run_id=run.run_id,
                status=status,
                error=error if status is ModelsRead.FAILED else None,
                attempts=run.attempts + 1,
                read_at=db.now(),
            ).or_replace(),
        )


def of_run(conn: sqlite3.Connection, table: RunTable, run_id: int) -> list[records.RunModel]:
    """The models a run's session named, the most costly first.

    Returns:
        A row per model; empty for a run not read yet, whose session is missing, or that made no model call.
    """
    query = (
        sql.select("*")
        .from_("run_models")
        .where("run_table = ? AND run_id = ?", table, run_id)
        .order_by("cost_usd DESC, model")
    )
    return records.fetch_all(conn, records.RunModel, query)


# One table's runs that are due: ended with a session, and never read or failed long enough ago to read again.
def _due_in(table: RunTable, retry_before: str) -> sql.Select:
    return (
        sql.select(
            "? AS run_table, r.id AS run_id, r.session_id, r.started_at, coalesce(m.attempts, 0) AS attempts", table
        )
        .from_("{} r", sql.name(table))
        .left_join("run_model_reads m ON m.run_table = ? AND m.run_id = r.id", table)
        .where("r.session_id IS NOT NULL AND r.ended_at IS NOT NULL")
        .where(
            "m.run_id IS NULL OR (m.status = ? AND m.attempts < ? AND m.read_at < ?)",
            ModelsRead.FAILED,
            MAX_ATTEMPTS,
            retry_before,
        )
    )


def _table(name: str) -> RunTable:
    match name:
        case "ticks" | "runs" | "chore_runs" | "review_runs":
            return name
        case _:
            msg = f"not a run table: {name}"
            raise ValueError(msg)
