"""The operator's verbs on agent memory (DESIGN §28, Commands): forgetting and purging, and making lessons.

Each deletes bodies, never rows: a forgotten memory is a tombstone that keeps who wrote it and when. The delete runs
with `PRAGMA secure_delete` on, and the write-ahead log is checkpointed after it, so a purged poison or a leaked
secret does not survive in free pages or the log. Only the operator's shell runs these: they refuse inside canopy's
ticks and runs. A lesson is made only here, from a proposal the operator promotes: no agent writes one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import conversation, db, memory, records
from canopy.core.memory_text import TextRefused, check_text
from canopy.core.vocab import MemoryAuthor, MemoryMode, MemoryScope, MemoryStatus

if TYPE_CHECKING:
    from canopy.core.config import Config


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


@dataclass(frozen=True)
class Promoted:
    """A lesson the operator promoted: its id, the lesson it superseded under the key, and whether runs read it now."""

    lesson: records.Memory
    superseded: int | None
    served: bool


def promote(conn: sqlite3.Connection, config: Config, proposal_id: int, *, text: str | None = None) -> Promoted:
    """Copy a pending proposal into a new lesson the operator authored, with `text` in place of its own if given.

    The lesson keeps the proposal's key and repository, supersedes an active lesson under the key, and is due for review
    `REVIEW_DAYS` on. The proposal is `superseded`. At `record` the lesson is recorded and served to no run.

    Returns:
        The lesson, the lesson it superseded, and whether runs are served lessons now.

    Raises:
        Refused: (`inside_run`) inside one of canopy's ticks or runs; (`off`) proposals are off; (`unknown`) no
            proposal has the id; (`not_pending`) it is not waiting on the operator; (`bad_text`) the text is outside
            the bounds.
        RuntimeError: The lesson it wrote cannot be read back.
    """
    proposal = _pending(conn, config, proposal_id)
    try:
        body = check_text(text if text is not None else proposal.body, memory.MAX_PROPOSAL_CHARS)
    except TextRefused as e:
        raise conversation.Refused("bad_text", f"the lesson's {e}") from None
    now = datetime.now(UTC)
    stamp = db.format_time(now)
    with db.transaction(conn):
        old = next((m for m in memory.active_lessons(conn) if m.key == proposal.key), None)
        if old is not None:
            conn.execute("UPDATE memories SET status = ? WHERE id = ?", (MemoryStatus.SUPERSEDED, old.id))
        cur = conn.execute(
            "INSERT INTO memories (scope, repo, key, body, status, author, supersedes, promoted_from, created_at, "
            "approved_at, review_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                MemoryScope.LESSON,
                proposal.repo,
                proposal.key,
                body,
                MemoryStatus.ACTIVE,
                MemoryAuthor.OPERATOR,
                old.id if old is not None else None,
                proposal.id,
                stamp,
                stamp,
                db.format_time(now + timedelta(days=memory.REVIEW_DAYS)),
            ),
        )
        lesson_id = int(cur.lastrowid or 0)
        if old is not None:
            conn.execute(
                "UPDATE memories SET why = ?, invalidated_at = ? WHERE id = ?",
                (f"superseded by lesson {lesson_id}", stamp, old.id),
            )
        conn.execute(
            "UPDATE memories SET status = ?, why = ?, invalidated_at = ? WHERE id = ?",
            (MemoryStatus.SUPERSEDED, f"promoted to lesson {lesson_id}", stamp, proposal.id),
        )
    lesson = memory.get(conn, lesson_id)
    if lesson is None:
        raise RuntimeError(f"lesson {lesson_id} vanished")
    served = config.memory.proposals is MemoryMode.USE
    return Promoted(lesson=lesson, superseded=old.id if old is not None else None, served=served)


def reject(conn: sqlite3.Connection, config: Config, proposal_id: int) -> records.Memory:
    """End a pending proposal: no lesson is made of it.

    Returns:
        The proposal as it was.

    Raises:
        Refused: (`inside_run`), (`off`), (`unknown`), or (`not_pending`), as `promote` does.
    """
    proposal = _pending(conn, config, proposal_id)
    conn.execute(
        "UPDATE memories SET status = ?, why = ?, invalidated_at = ? WHERE id = ? AND status = ?",
        (MemoryStatus.INVALID, "rejected", db.now(), proposal.id, MemoryStatus.PENDING),
    )
    return proposal


def renew(conn: sqlite3.Connection, config: Config, lesson_id: int) -> str:
    """Keep a lesson: it is due for review `REVIEW_DAYS` from now, and a run's report that it is wrong is cleared.

    Returns:
        When it is next due for review, as the journal stores it.

    Raises:
        Refused: (`inside_run`) inside one of canopy's ticks or runs; (`off`) proposals are off; (`unknown`) no
            lesson in force has the id.
    """
    conversation.check_operator()
    _check_on(config)
    found = memory.get(conn, lesson_id)
    if found is None or found.scope is not MemoryScope.LESSON or found.status is not MemoryStatus.ACTIVE:
        raise conversation.Refused("unknown", f"no lesson in force has id {lesson_id}")
    due = db.format_time(datetime.now(UTC) + timedelta(days=memory.REVIEW_DAYS))
    conn.execute(
        "UPDATE memories SET review_at = ?, wrong_at = NULL, wrong_run_id = NULL WHERE id = ?", (due, lesson_id)
    )
    return due


def _pending(conn: sqlite3.Connection, config: Config, proposal_id: int) -> records.Memory:
    conversation.check_operator()
    _check_on(config)
    found = memory.get(conn, proposal_id)
    if found is None or found.scope is not MemoryScope.PROPOSAL:
        raise conversation.Refused("unknown", f"no proposal has id {proposal_id}")
    if found.status is not MemoryStatus.PENDING:
        raise conversation.Refused("not_pending", f"proposal {proposal_id} is {found.status}: {found.why}")
    return found


def _check_on(config: Config) -> None:
    if config.memory.proposals is MemoryMode.OFF:
        raise conversation.Refused(
            "off", "memory.proposals is off: set it to record or use to build lessons up, or to serve them"
        )
