"""The loop's pause (DESIGN §6, The loop): whether the operator asked `canopy loop` to start no more ticks.

It is a journal fact, so every channel shares it: the `p` key at the loop's terminal, `canopy pause` and `canopy
resume`, and the web UI, which runs on its own connections in the loop's process. The loop reads it at every step of
its wait. A tick already running finishes; a hand-run `canopy tick` and the loop's `t` key still tick, since the
operator asked for that tick. Workers already dispatched are not touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db

if TYPE_CHECKING:
    import sqlite3

# The channel of a pause or resume from the loop's own terminal, beside `cli` and `web` (DESIGN §22).
LOOP = "loop"


@dataclass(frozen=True)
class Paused:
    """The loop is paused: since when, and through which channel."""

    since: str
    channel: str


def paused(conn: sqlite3.Connection) -> Paused | None:
    """The pause in force, or None while the loop ticks.

    Returns:
        When the loop was paused and through which channel, or None if it is not paused.
    """
    row = conn.execute("SELECT paused_at, channel FROM pause WHERE id = 1").fetchone()
    return Paused(str(row["paused_at"]), str(row["channel"])) if row is not None else None


def pause(conn: sqlite3.Connection, *, channel: str) -> bool:
    """Pause the loop.

    Returns:
        Whether it was already paused, which keeps the first pause's time and channel.
    """
    cur = conn.execute(
        "INSERT INTO pause (id, paused_at, channel) VALUES (1, ?, ?) ON CONFLICT (id) DO NOTHING", (db.now(), channel)
    )
    return cur.rowcount == 0


def resume(conn: sqlite3.Connection) -> bool:
    """Lift the pause.

    Returns:
        Whether the loop was already running.
    """
    return conn.execute("DELETE FROM pause WHERE id = 1").rowcount == 0
