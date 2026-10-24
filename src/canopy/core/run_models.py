"""Which models served each agent run, as its session's own record says (DESIGN §13, Each agent's model).

The runtime prints no event naming the model a call went to, so a run's session is read once the run has ended: by the
process that ran it, as it closes the run (`read_ended`), and for a run that leaves it unread, by the loop while it
waits between ticks (`canopy.loop.models`). What a read found is recorded here: each model's replies and their cost
(`run_models`), the model of each reply of a run more than one model served (`run_reply_models`), and how the read
ended (`run_model_reads`). `due` is what to read next: runs never read, the newest first, then failed ones again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from canopy.core import db, records, sql
from canopy.core.vocab import ModelsRead
from canopy.runtime import session_models

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Mapping, Sequence

    from canopy.core.context import Context
    from canopy.infra import logs
    from canopy.runtime.report import ModelUse

#: A table of agent runs, each with a session: a tick's overseer, a worker or plan run, a chore run, a review run, a
#: task's run.
type RunTable = Literal["ticks", "runs", "chore_runs", "review_runs", "task_runs"]
_TABLES: tuple[RunTable, ...] = ("ticks", "runs", "chore_runs", "review_runs", "task_runs")
#: No reply's model, for a read that found none, or that did not find the session.
_NO_REPLIES: Mapping[str, str] = MappingProxyType({})
#: How long a failed read waits before it is tried again, and how many reads a run gets in all.
RETRY_AFTER = timedelta(days=1)
MAX_ATTEMPTS = 3


#: The tables of a ticket's runs whose cost is its own: its worker and plan runs, and the review runs naming it.
_TICKET_TABLES: tuple[Literal["runs", "review_runs"], ...] = ("runs", "review_runs")


@dataclass(frozen=True)
class Due:
    """A run whose session is due to be read: never read, or failed and due again."""

    run_table: RunTable
    run_id: int
    session_id: str
    #: The reads it has had: 0 for one never read.
    attempts: int


@dataclass(frozen=True)
class ModelTotal:
    """What one model cost over a subject's runs, as their sessions say."""

    #: As `provider/model`.
    model: str
    #: How many of the runs it wrote a reply of: a run on two models counts under each.
    runs: int
    #: What the sessions priced its replies at, in US dollars.
    cost_usd: float


def due(conn: sqlite3.Connection, *, limit: int, now: datetime | None = None) -> list[Due]:
    """The runs whose sessions are due to be read, at most `limit` of them.

    A run is due once it has ended with a session id: never read, the newest first, so a run that just ended goes
    before history; then one whose last read failed `RETRY_AFTER` ago, with fewer than `MAX_ATTEMPTS` reads.

    Returns:
        The runs, in the order to read them.
    """
    retry_before = _retry_before(now)
    candidates = sql.union(*(_due_in(table, retry_before) for table in _TABLES), every=True)
    return _dues(conn, candidates, limit=limit)


def read_ended(ctx: Context, table: RunTable, run_id: int, log: logs.TickAdapter) -> None:
    """Read which models served run `run_id` of `table`, just closed, if its session is due to be read.

    The process that ran it calls this once it has closed the run's row. What it raises is logged, never the run's
    outcome: the run is closed, and a run left unread is read while the loop waits.
    """
    try:
        for run in _dues(ctx.conn, _due_in(table, _retry_before()).where("r.id = ?", run_id), limit=1):
            read(ctx, run, log)
    except Exception as e:
        log.exception(
            "reading which models served a run raised",
            extra={"run_table": table, "run_id": run_id, "error": str(e)},
        )


def read(ctx: Context, run: Due, log: logs.TickAdapter) -> ModelsRead:
    """Read `run`'s session from the runtime's own record, and record which models served it.

    Returns:
        How the read ended. A failed one is logged, and due again `RETRY_AFTER` later.
    """
    found = session_models.read(ctx.runner, cwd=ctx.repo_root, session_id=run.session_id)
    status = ModelsRead(found.outcome)
    record(ctx.conn, run, status, found.models, error=found.error, replies=found.replies)
    if status is ModelsRead.FAILED:
        log.warning(
            "could not read which models served a run",
            extra={"run_table": run.run_table, "run_id": run.run_id, "error": found.error},
        )
    return status


def record(
    conn: sqlite3.Connection,
    run: Due,
    status: ModelsRead,
    models: Sequence[ModelUse] = (),
    *,
    error: str | None = None,
    replies: Mapping[str, str] = _NO_REPLIES,
) -> None:
    """Record how reading `run`'s session ended, and the models it found, in place of any read before.

    `replies` is the model of each reply, by its message, of a session more than one model served.

    Only a read that found the session replaces the models a read before found, and their replies'. One that finds it
    missing keeps them, as found, since the runtime dropped what canopy read; one that fails keeps them till a read
    again finds it.
    """
    with db.transaction(conn):
        kept = status is not ModelsRead.FOUND and bool(of_run(conn, run.run_table, run.run_id))
        if kept and status is ModelsRead.MISSING:
            status = ModelsRead.FOUND
        if not kept:
            for table in ("run_models", "run_reply_models"):
                sql.execute(conn, sql.delete(table).where("run_table = ? AND run_id = ?", run.run_table, run.run_id))
            sql.execute_many(
                conn,
                sql.insert_rows("run_models", ("run_table", "run_id", "model", "replies", "cost_usd")),
                [(run.run_table, run.run_id, m.model, m.replies, m.cost_usd) for m in models],
            )
            sql.execute_many(
                conn,
                sql.insert_rows("run_reply_models", ("run_table", "run_id", "message", "model")),
                [(run.run_table, run.run_id, message, model) for message, model in replies.items()],
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
    return of_runs(conn, table, [run_id])[run_id]


def of_runs(conn: sqlite3.Connection, table: RunTable, run_ids: Collection[int]) -> dict[int, list[records.RunModel]]:
    """The models each of a table's runs' sessions named, as `of_run` gives them, in one read.

    Returns:
        Each run's models by its id, every one of `run_ids` included.
    """
    found: dict[int, list[records.RunModel]] = {i: [] for i in run_ids}
    if not run_ids:
        return found
    query = (
        sql.select("*")
        .from_("run_models")
        .where("run_table = ?", table)
        .where_in("run_id", run_ids)
        .order_by("run_id, cost_usd DESC, model")
    )
    for row in records.fetch_all(conn, records.RunModel, query):
        found[row.run_id].append(row)
    return found


def replies_of(conn: sqlite3.Connection, table: RunTable, run_id: int) -> dict[str, str]:
    """The model that wrote each reply of a run more than one model served, by the reply's message.

    Returns:
        Each reply's model; empty for a run one model served, and for one not read yet or read before canopy kept them.
    """
    query = sql.select("*").from_("run_reply_models").where("run_table = ? AND run_id = ?", table, run_id)
    return {row.message: row.model for row in records.fetch_all(conn, records.RunReplyModel, query)}


def reads_of(conn: sqlite3.Connection, table: RunTable, run_ids: Collection[int]) -> dict[int, records.RunModelRead]:
    """How canopy's last read of each of a table's runs' sessions ended, in one read.

    Returns:
        Each read run's last read by its id; a run never read is not among them.
    """
    if not run_ids:
        return {}
    query = sql.select("*").from_("run_model_reads").where("run_table = ?", table).where_in("run_id", run_ids)
    return {row.run_id: row for row in records.fetch_all(conn, records.RunModelRead, query)}


def of_ticket(conn: sqlite3.Connection, key: str) -> list[ModelTotal]:
    """What each model cost over a ticket's runs and the review runs naming it, as `db.ticket_cost` counts them.

    Returns:
        A total per model their sessions named, the most costly first; what the rest of the ticket's cost is, no
        session named a model for.
    """
    named = sql.union(*(_ticket_models(table, key) for table in _TICKET_TABLES), every=True)
    query = (
        sql.select("model, count(*), SUM(cost_usd)")
        .from_("({}) AS m", named)
        .group_by("model")
        .order_by("SUM(cost_usd) DESC, model")
    )
    return [
        ModelTotal(model=str(model), runs=int(runs), cost_usd=float(cost))
        for model, runs, cost in sql.execute(conn, query)
    ]


def _retry_before(now: datetime | None = None) -> str:
    return db.format_time((now or datetime.now(UTC)) - RETRY_AFTER)


# The runs `candidates` selects, as `_due_in` selects them, in the order to read them.
def _dues(conn: sqlite3.Connection, candidates: sql.Composable, *, limit: int) -> list[Due]:
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


# One table's runs that are due: ended with a session, and never read or failed long enough ago to read again.
def _due_in(table: RunTable, retry_before: str) -> sql.Select:
    return (
        sql.select(
            "? AS run_table, r.id AS run_id, r.session_id, r.started_at, coalesce(m.attempts, 0) AS attempts",
            table,
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


# One table's runs of a ticket, a row per model its session named, with that model's cost.
def _ticket_models(table: Literal["runs", "review_runs"], key: str) -> sql.Select:
    return (
        sql.select("m.model, m.cost_usd")
        .from_("{} r CROSS JOIN run_models m ON m.run_table = ? AND m.run_id = r.id", sql.name(table), table)
        .where("r.ticket_key = ?", key)
    )


def _table(name: str) -> RunTable:
    match name:
        case "ticks" | "runs" | "chore_runs" | "review_runs" | "task_runs":
            return name
        case _:
            msg = f"not a run table: {name}"
            raise ValueError(msg)
