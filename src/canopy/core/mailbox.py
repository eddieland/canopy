"""Messages kept for mailbox sinks (DESIGN §20), for `canopy-notify-relay` to collect from another machine.

A mailbox sink runs no command: delivering to it keeps the rendered message in the journal. `canopy notify read`
(over SSH) and the web UI's `GET /api/mailbox/{sink}` (over HTTP) both read it here, so the two give the same answer.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from canopy.core import db

# Kept messages go once they are this old, read or not.
KEEP = timedelta(days=7)
# The most messages one read returns, oldest first; a reader asks again from the last one it got.
READ_LIMIT = 50


@dataclass(frozen=True)
class Kept:
    """One kept message: its id, when it was kept, and the message as its sink's format rendered it."""

    id: int
    at: str
    message: str

    def as_json(self) -> dict[str, object]:
        """The message as a reader receives it."""
        return {"id": self.id, "at": self.at, "message": self.message}


def put(conn: sqlite3.Connection, sink: str, message: str) -> int:
    """Keep `message` for sink `sink`. Returns its id."""
    cur = conn.execute("INSERT INTO notify_mailbox (sink, at, message) VALUES (?, ?, ?)", (sink, db.now(), message))
    return int(cur.lastrowid or 0)


def after(conn: sqlite3.Connection, sink: str, cursor: int | None, *, limit: int = READ_LIMIT) -> list[Kept]:
    """Return sink `sink`'s messages after id `cursor`, oldest first, at most `limit`.

    With no cursor, a reader that has never read, only the newest message: it shows what is current, with no backlog.
    """
    if cursor is None:
        sql = "SELECT id, at, message FROM notify_mailbox WHERE sink = ? ORDER BY id DESC LIMIT 1"
        rows = conn.execute(sql, (sink,)).fetchall()
    else:
        sql = "SELECT id, at, message FROM notify_mailbox WHERE sink = ? AND id > ? ORDER BY id LIMIT ?"
        rows = conn.execute(sql, (sink, cursor, limit)).fetchall()
    return [Kept(int(r[0]), str(r[1]), str(r[2])) for r in rows]


def count(conn: sqlite3.Connection, sink: str) -> int:
    """How many messages sink `sink` has kept."""
    return int(conn.execute("SELECT count(*) FROM notify_mailbox WHERE sink = ?", (sink,)).fetchone()[0])


def forget(conn: sqlite3.Connection, sink: str) -> None:
    """Delete every message kept for sink `sink`."""
    conn.execute("DELETE FROM notify_mailbox WHERE sink = ?", (sink,))


def sinks(conn: sqlite3.Connection) -> set[str]:
    """The sinks with messages kept."""
    return {str(r[0]) for r in conn.execute("SELECT DISTINCT sink FROM notify_mailbox")}


def prune(conn: sqlite3.Connection, now: datetime) -> int:
    """Delete messages older than `KEEP`. Returns how many were deleted."""
    cur = conn.execute("DELETE FROM notify_mailbox WHERE at < ?", (db.format_time(now - KEEP),))
    return cur.rowcount
