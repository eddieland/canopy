"""The operator's verbs on agent memory (DESIGN §28, Commands): forgetting one memory, and purging many.

Each deletes bodies, never rows: a forgotten memory is a tombstone that keeps who wrote it and when. The delete runs
with `PRAGMA secure_delete` on, and the write-ahead log is checkpointed after it, so a purged poison or a leaked
secret does not survive in free pages or the log. Only the operator's shell runs these: they refuse inside canopy's
ticks and runs.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from canopy.core import conversation, db, records
from canopy.core.vocab import MemoryStatus


@dataclass(frozen=True)
class Scrubbed:
    """What a forget or a purge deleted: how many bodies, and whether the write-ahead log was checkpointed after."""

    count: int
    checkpointed: bool


def forget(conn: sqlite3.Connection, memory_id: int) -> tuple[records.Memory, Scrubbed]:
    """Delete one memory's body, a note's, a proposal's, or a lesson's, leaving its tombstone.

    Returns:
        The memory as it was, and what was deleted.

    Raises:
        Refused: (`inside_run`) inside one of canopy's ticks or runs; (`unknown`) no memory has the id; (`forgotten`)
            its body is already gone.
    """
    conversation.check_operator()
    found = records.fetch_one(conn, records.Memory, "SELECT * FROM memories WHERE id = ?", (memory_id,))
    if found is None:
        raise conversation.Refused("unknown", f"no memory has id {memory_id}")
    if found.body is None:
        raise conversation.Refused("forgotten", f"memory {memory_id}'s text is already gone: {found.why}")
    return found, _scrub(conn, "id = ?", (memory_id,), why="forgotten")


def purge(
    conn: sqlite3.Connection, *, ticket: str | None = None, run: int | None = None, every: bool = False
) -> Scrubbed:
    """Delete the bodies of every note and proposal of a ticket's runs, of one run, or with `every`, of every memory.

    A lesson is the operator's own text, so only `every` deletes one.

    Returns:
        What was deleted.

    Raises:
        Refused: (`inside_run`) inside one of canopy's ticks or runs.
        ValueError: Not exactly one of `ticket`, `run`, and `every` is given.
    """
    conversation.check_operator()
    if sum((ticket is not None, run is not None, every)) != 1:
        raise ValueError("purge takes exactly one of a ticket, a run, or every memory")
    if ticket is not None:
        return _scrub(conn, "ticket_key = ?", (ticket,), why="purged")
    if run is not None:
        return _scrub(conn, "run_id = ?", (run,), why="purged")
    return _scrub(conn, "1", (), why="purged")


def _scrub(conn: sqlite3.Connection, where: str, params: tuple[object, ...], *, why: str) -> Scrubbed:
    """Set the body of every memory `where` names to NULL, securely, and checkpoint the log after it.

    Returns:
        How many bodies were deleted, and whether the checkpoint completed: a reader can hold it back, and the next
        checkpoint completes it.
    """
    before = int(conn.execute("PRAGMA secure_delete").fetchone()[0])
    conn.execute("PRAGMA secure_delete = ON")
    try:
        with db.transaction(conn):
            # `where` is one of the fixed clauses above, never input; its values are bound parameters.
            cur = conn.execute(
                f"UPDATE memories SET body = NULL, status = ?, why = ?, "  # noqa: S608
                f"invalidated_at = coalesce(invalidated_at, ?) WHERE body IS NOT NULL AND {where}",
                (MemoryStatus.INVALID, why, db.now(), *params),
            )
            count = cur.rowcount
    finally:
        conn.execute(f"PRAGMA secure_delete = {before}")
    busy = int(conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0])
    return Scrubbed(count=count, checkpointed=busy == 0)
