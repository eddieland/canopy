"""Every session the agent runtime keeps, canopy's and not, as the journal records it (DESIGN §13).

The runtime's record is read a page at a time, from where the last read stopped (`read_next`), by the loop while it
waits between ticks (`canopy.loop.sessions`), and each session read is recorded as the runtime last saw it, in place of
any row before (`record`). A session is canopy's when one of this journal's agent runs names it, or when it ran, as a
subagent, for one that is, however deep; every other session is spend outside canopy (`spend`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from canopy.core import db, records, sql
from canopy.core.vocab import SessionsRead
from canopy.runtime import sessions
from canopy.runtime.report import MAX_SESSIONS

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

    from canopy.core.run_models import RunTable
    from canopy.runtime.report import SessionCursor, SessionPage, SessionSpend

#: How many directories `spend` lists of the sessions outside canopy, the costliest first.
DIRECTORIES = 10
#: The tables of this journal's agent runs, each with the session its run ran in.
_RUN_TABLES: tuple[RunTable, ...] = ("ticks", "runs", "chore_runs", "review_runs", "task_runs")


@dataclass(frozen=True)
class Share:
    """What a set of the runtime's sessions cost: how many there were, and their cost in US dollars."""

    sessions: int
    cost_usd: float


@dataclass(frozen=True)
class DirectorySpend:
    """What the sessions outside canopy that ran in one directory cost."""

    directory: str
    sessions: int
    cost_usd: float


@dataclass(frozen=True)
class SessionsSpend:
    """What the runtime's sessions that started in a window cost, canopy's apart from the rest.

    `canopy` counts this journal's runs' sessions and their subagents'; `outside`, every other session, among them
    another workspace's canopy runs, whose journal is not this one. `directories` is where `outside` ran, the costliest
    first, at most `DIRECTORIES`. `read_at` is when the record was last read, and `status` how that read ended; both
    None when it never was, and then the window's sessions are not known, only none recorded.
    """

    canopy: Share
    outside: Share
    directories: Sequence[DirectorySpend]
    read_at: str | None
    status: SessionsRead | None


def read_next(conn: sqlite3.Connection, *, limit: int = MAX_SESSIONS) -> SessionPage:
    """Read the runtime's sessions updated after the journal's cursor, and record them.

    Returns:
        The page the runtime returned; a full one means more may wait to be read.
    """
    page = sessions.updated_after(cursor(conn), limit=limit)
    record(conn, page)
    return page


def cursor(conn: sqlite3.Connection) -> SessionCursor | None:
    """Where the next read of the runtime's sessions starts.

    Returns:
        The last session read's update and id; None before any session was read.
    """
    read = last_read(conn)
    if read is None or read.cursor_updated_ms is None or read.cursor_session_id is None:
        return None
    return (read.cursor_updated_ms, read.cursor_session_id)


def last_read(conn: sqlite3.Connection) -> records.RuntimeSessionRead | None:
    """How reading the runtime's sessions stands.

    Returns:
        Its one row; None before the first read.
    """
    return records.fetch_one(conn, records.RuntimeSessionRead, sql.select("*").from_("runtime_session_reads"))


def record(conn: sqlite3.Connection, page: SessionPage, *, now: str | None = None) -> None:
    """Record a page the runtime returned: each session in it in place of any row before, and how the read ended.

    A read that did not find the record leaves the cursor where it was, so the next read starts there again.
    """
    at = now or db.now()
    was = last_read(conn)
    status = SessionsRead(page.outcome)
    found = status is SessionsRead.FOUND and page.cursor is not None
    updated_ms, session_id = page.cursor if found and page.cursor is not None else _kept(was)
    with db.transaction(conn):
        for session in page.sessions:
            _record_session(conn, session, at)
        sql.execute(
            conn,
            sql.insert(
                "runtime_session_reads",
                id=1,
                cursor_updated_ms=updated_ms,
                cursor_session_id=session_id,
                status=status,
                error=page.error if status is SessionsRead.FAILED else None,
                skipped=(was.skipped if was is not None else 0) + page.skipped,
                read_at=at,
            ).or_replace(),
        )


def spend(conn: sqlite3.Connection, since: str, until: str) -> SessionsSpend:
    """What the runtime's sessions that started in `[since, until)`, each a journal time, cost, canopy's apart.

    Returns:
        Canopy's sessions, the rest, and where the rest ran.
    """
    shares = {
        bool(ours): Share(sessions=int(count), cost_usd=float(cost))
        for ours, count, cost in sql.execute(
            conn,
            _classified(since, until).group_by("ours"),
        )
    }
    directories = [
        DirectorySpend(directory=str(directory), sessions=int(count), cost_usd=float(cost))
        for directory, count, cost in sql.execute(
            conn,
            sql.select("directory, count(*), total(cost_usd)")
            .from_("({}) AS c", _sessions_in(since, until))
            .where("NOT ours")
            .group_by("directory")
            .order_by("total(cost_usd) DESC, directory")
            .limit(DIRECTORIES),
        )
    ]
    read = last_read(conn)
    return SessionsSpend(
        canopy=shares.get(True, Share(0, 0.0)),
        outside=shares.get(False, Share(0, 0.0)),
        directories=directories,
        read_at=read.read_at if read is not None else None,
        status=read.status if read is not None else None,
    )


def of_session(conn: sqlite3.Connection, session_id: str) -> records.RuntimeSession | None:
    """The journal's row of one of the runtime's sessions.

    Returns:
        The session as the runtime last recorded it; None when none was read.
    """
    query = sql.select("*").from_("runtime_sessions").where("session_id = ?", session_id)
    return records.fetch_one(conn, records.RuntimeSession, query)


def models_of(conn: sqlite3.Connection, session_id: str) -> list[records.RuntimeSessionModel]:
    """The models one of the runtime's sessions names, the most costly first.

    Returns:
        A row per model; empty for a session not read, or that made no model call.
    """
    query = (
        sql.select("*")
        .from_("runtime_session_models")
        .where("session_id = ?", session_id)
        .order_by("cost_usd DESC, model")
    )
    return records.fetch_all(conn, records.RuntimeSessionModel, query)


def _kept(was: records.RuntimeSessionRead | None) -> tuple[int | None, str | None]:
    return (was.cursor_updated_ms, was.cursor_session_id) if was is not None else (None, None)


def _record_session(conn: sqlite3.Connection, session: SessionSpend, at: str) -> None:
    sql.execute(conn, sql.delete("runtime_sessions").where("session_id = ?", session.session_id))
    sql.execute(
        conn,
        sql.insert(
            "runtime_sessions",
            session_id=session.session_id,
            parent_id=session.parent_id,
            directory=session.directory,
            started_at=_journal_time(session.created_ms),
            updated_at=_journal_time(session.updated_ms),
            updated_ms=session.updated_ms,
            cost_usd=session.cost_usd,
            tokens_input=session.input,
            tokens_output=session.output,
            tokens_reasoning=session.reasoning,
            tokens_cache_read=session.cache_read,
            tokens_cache_write=session.cache_write,
            read_at=at,
        ),
    )
    sql.execute_many(
        conn,
        sql.insert_rows("runtime_session_models", ("session_id", "model", "replies", "cost_usd")),
        [(session.session_id, m.model, m.replies, m.cost_usd) for m in session.models],
    )


def _journal_time(ms: int) -> str:
    return db.format_time(datetime.fromtimestamp(ms / 1000, UTC))


# Each session that started in the window, its directory and cost, and whether it is canopy's.
def _sessions_in(since: str, until: str) -> sql.Select:
    ran = sql.union(
        *(sql.select("session_id").from_("{}", sql.name(t)).where("session_id IS NOT NULL") for t in _RUN_TABLES),
    )
    return (
        sql.select("s.directory, s.cost_usd, s.session_id IN (SELECT session_id FROM ours) AS ours")
        .with_("ran(session_id) AS ({})", ran)
        .with_(
            "ours(session_id) AS (SELECT session_id FROM ran UNION SELECT s.session_id FROM runtime_sessions s"
            " JOIN ours o ON s.parent_id = o.session_id)",
            recursive=True,
        )
        .from_("runtime_sessions s")
        .where("s.started_at >= ? AND s.started_at < ?", since, until)
    )


# The window's sessions, as `_sessions_in` reads them, to be grouped by whether each is canopy's.
def _classified(since: str, until: str) -> sql.Select:
    return sql.select("ours, count(*), total(cost_usd)").from_("({}) AS c", _sessions_in(since, until))
