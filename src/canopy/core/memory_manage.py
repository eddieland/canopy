"""The operator's verbs on agent memory (DESIGN §28, Commands): forgetting and purging, and making lessons.

Each deletes bodies, never rows: a forgotten memory is a tombstone that keeps who wrote it and when. The delete runs
with `PRAGMA secure_delete` on, the search index is merged after it so it keeps no word of the text, and the
write-ahead log is checkpointed, so a purged poison or a leaked secret does not survive in free pages or the log. Only
the operator runs these, from `canopy memory` or the web UI: they refuse inside canopy's ticks and runs. A lesson is
made only here, from a proposal or a ticket's note the operator promotes, or from a lesson they edit: no agent writes
one. Neither changes a lesson's text in place: the new lesson supersedes the one before it, which keeps its text as
the lesson's history.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import conversation, db, memory, records, sql
from canopy.core.memory_text import TextRefused, check_text
from canopy.core.vocab import MemoryAuthor, MemoryMode, MemoryScope, MemoryStatus

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from canopy.core.config import Config

#: The statement that sets `secure_delete` back to each value `PRAGMA secure_delete` reads, which a PRAGMA cannot bind.
_SECURE_DELETE: Mapping[int, sql.Fragment] = {
    0: sql.frag("PRAGMA secure_delete = OFF"),
    1: sql.frag("PRAGMA secure_delete = ON"),
    2: sql.frag("PRAGMA secure_delete = FAST"),
}


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
    found = records.fetch_one(conn, records.Memory, sql.select("*").from_("memories").where("id = ?", memory_id))
    if found is None:
        raise conversation.Refused("unknown", f"no memory has id {memory_id}")
    if found.body is None:
        raise conversation.Refused("forgotten", f"memory {memory_id}'s text is already gone: {found.why}")
    return found, _scrub(conn, sql.frag("id = ?", memory_id), why="forgotten")


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
        return _scrub(conn, sql.frag("ticket_key = ?", ticket), why="purged")
    if run is not None:
        return _scrub(conn, sql.frag("run_id = ?", run), why="purged")
    return _scrub(conn, sql.frag("1"), why="purged")


def _scrub(conn: sqlite3.Connection, where: sql.Composable, *, why: str) -> Scrubbed:
    """Set the body of every memory `where` names to NULL, securely, and checkpoint the log after it.

    Returns:
        How many bodies were deleted, and whether the checkpoint completed: a reader can hold it back, and the next
        checkpoint completes it.
    """
    before = int(sql.execute(conn, sql.frag("PRAGMA secure_delete")).fetchone()[0])
    sql.execute(conn, _SECURE_DELETE[1])
    try:
        with db.transaction(conn):
            cur = sql.execute(
                conn,
                sql.update("memories")
                .set(body=None, status=MemoryStatus.INVALID, why=why)
                .set_to("invalidated_at = coalesce(invalidated_at, ?)", db.now())
                .where("body IS NOT NULL")
                .where("{}", where),
            )
            count = cur.rowcount
            # The index's triggers marked the deleted words; merging its segments drops them, and frees the pages
            # that held them for `secure_delete` to zero.
            sql.execute(conn, sql.insert("memories_fts", memories_fts=sql.frag("'optimize'")))
    finally:
        sql.execute(conn, _SECURE_DELETE[before])
    busy = int(sql.execute(conn, sql.frag("PRAGMA wal_checkpoint(TRUNCATE)")).fetchone()[0])
    return Scrubbed(count=count, checkpointed=busy == 0)


@dataclass(frozen=True)
class Promoted:
    """A lesson the operator promoted: what it came from, the lesson it superseded, and whether runs read it now.

    `private` is whether its text is still a private ticket's run's own words, which may hold what the operator kept
    off the tracker: the source was a private run's and no `text` replaced it.
    """

    lesson: records.Memory
    source: records.Memory
    superseded: int | None
    served: bool
    private: bool


def promote(
    conn: sqlite3.Connection,
    config: Config,
    memory_id: int,
    *,
    text: str | None = None,
    repo: str | None = None,
    repos: Sequence[str] = (),
) -> Promoted:
    """Copy a pending proposal, or a ticket's note, into a new lesson the operator authored.

    The lesson takes `text` in place of the source's own if given, and `repo` in place of a proposal's repository; a
    note names none, so its lesson is for every repository unless `repo` is given. It keeps the source's key,
    supersedes an active lesson under the key, and is due for review `REVIEW_DAYS` on. A proposal is `superseded`; a
    note stays as it was, its ticket's. At `record` the lesson is recorded and served to no run. `repos` are the
    workspace's repositories, which `repo` must be one of.

    Returns:
        The lesson, the memory it came from, the lesson it superseded, and whether runs are served lessons now.

    Raises:
        Refused: (`inside_run`) inside one of canopy's ticks or runs; (`off`) proposals are off; (`unknown`) no
            proposal or note has the id; (`not_pending`) a proposal is not waiting on the operator; (`forgotten`) a
            note's text is gone; (`unknown_repo`) `repo` is not in `repos`; (`bad_text`) the text is outside the
            bounds.
        RuntimeError: The lesson it wrote cannot be read back.
    """
    source = _promotable(conn, config, memory_id)
    if repo is not None and repo not in repos:
        names = ", ".join(repos) or "none yet"
        raise conversation.Refused("unknown_repo", f"{repo!r} is not a repository in this workspace ({names})")
    try:
        body = check_text(text if text is not None else source.body, memory.MAX_PROPOSAL_CHARS)
    except TextRefused as e:
        raise conversation.Refused("bad_text", f"the lesson's {e}") from None
    now = datetime.now(UTC)
    stamp = db.format_time(now)
    with db.transaction(conn):
        old = next((m for m in memory.active_lessons(conn) if m.key == source.key), None)
        if old is not None:
            sql.execute(conn, sql.update("memories").set(status=MemoryStatus.SUPERSEDED).where("id = ?", old.id))
        cur = sql.execute(
            conn,
            sql.insert(
                "memories",
                scope=MemoryScope.LESSON,
                repo=repo if repo is not None else source.repo,
                key=source.key,
                body=body,
                status=MemoryStatus.ACTIVE,
                author=MemoryAuthor.OPERATOR,
                supersedes=old.id if old is not None else None,
                promoted_from=source.id,
                created_at=stamp,
                approved_at=stamp,
                review_at=db.format_time(now + timedelta(days=memory.REVIEW_DAYS)),
            ),
        )
        lesson_id = int(cur.lastrowid or 0)
        if old is not None:
            sql.execute(
                conn,
                sql.update("memories")
                .set(why=f"superseded by lesson {lesson_id}", invalidated_at=stamp)
                .where("id = ?", old.id),
            )
        if source.scope is MemoryScope.PROPOSAL:
            sql.execute(
                conn,
                sql.update("memories")
                .set(status=MemoryStatus.SUPERSEDED, why=f"promoted to lesson {lesson_id}", invalidated_at=stamp)
                .where("id = ?", source.id),
            )
    lesson = memory.get(conn, lesson_id)
    if lesson is None:
        raise RuntimeError(f"lesson {lesson_id} vanished")
    served = config.memory.proposals is MemoryMode.USE
    superseded = old.id if old is not None else None
    private = text is None and from_private_run(conn, source)
    return Promoted(lesson=lesson, source=source, superseded=superseded, served=served, private=private)


def from_private_run(conn: sqlite3.Connection, found: records.Memory) -> bool:
    """Whether a run on a private ticket wrote `found`, so its text may hold what the operator kept off the tracker.

    Returns:
        True for a note or a proposal a private run wrote; False for a lesson, which no run writes.
    """
    run = db.get_run(conn, found.run_id) if found.run_id is not None else None
    return run is not None and bool(run["private"])


def reject(conn: sqlite3.Connection, config: Config, proposal_id: int) -> records.Memory:
    """End a pending proposal: no lesson is made of it.

    Returns:
        The proposal as it was.

    Raises:
        Refused: (`inside_run`), (`off`), (`unknown`), or (`not_pending`), as `promote` does.
    """
    proposal = _pending(conn, config, proposal_id)
    sql.execute(
        conn,
        sql.update("memories")
        .set(status=MemoryStatus.INVALID, why="rejected", invalidated_at=db.now())
        .where("id = ?", proposal.id)
        .where("status = ?", MemoryStatus.PENDING),
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
    sql.execute(
        conn, sql.update("memories").set(review_at=due, wrong_at=None, wrong_run_id=None).where("id = ?", lesson_id)
    )
    return due


@dataclass(frozen=True)
class Edited:
    """A lesson the operator edited: the new version, the one it replaced, and whether runs read it now."""

    #: The new version, in force under the key.
    lesson: records.Memory
    #: The version it replaced, superseded, its text kept as the lesson's history.
    replaced: records.Memory
    #: Which version of the lesson the new one is: 2 for the first edit of a lesson promoted once.
    version: int
    #: Whether runs are served lessons now, rather than recording them.
    served: bool


def edit(
    conn: sqlite3.Connection,
    config: Config,
    lesson_id: int,
    *,
    text: str | None = None,
    repo: str | None = None,
    every_repo: bool = False,
    repos: Sequence[str] = (),
) -> Edited:
    """Write a lesson in force anew: in `text` if given, for `repo` if given, or with `every_repo` for every one.

    The new version keeps the key, supersedes the lesson, and is made from it, so the old one stays, with its text, as
    the lesson's history, and what runs read of it and said of it stays with the words they read. It is due for review
    `REVIEW_DAYS` on, with no run's report that it is wrong: in writing it, the operator vouched for it. `repos` are
    the workspace's repositories, which `repo` must be one of.

    Returns:
        The new version, the one it replaced, which version it is, and whether runs are served lessons now.

    Raises:
        Refused: (`inside_run`) inside one of canopy's ticks or runs; (`off`) proposals are off; (`unknown`) no lesson
            in force has the id; (`unknown_repo`) `repo` is not in `repos`; (`bad_text`) the text is outside the
            bounds; (`unchanged`) it would say the same words to the same repositories.
        ValueError: Both `repo` and `every_repo` are given.
        RuntimeError: The lesson it wrote cannot be read back.
    """
    if repo is not None and every_repo:
        raise ValueError("an edit takes a repository or every repository, not both")
    conversation.check_operator()
    _check_on(config)
    old = memory.get(conn, lesson_id)
    if old is None or old.scope is not MemoryScope.LESSON or old.status is not MemoryStatus.ACTIVE:
        why = f": {old.status}, {old.why}" if old is not None and old.why is not None else ""
        raise conversation.Refused("unknown", f"no lesson in force has id {lesson_id}{why}")
    if repo is not None and repo not in repos:
        names = ", ".join(repos) or "none yet"
        raise conversation.Refused("unknown_repo", f"{repo!r} is not a repository in this workspace ({names})")
    try:
        body = check_text(text if text is not None else old.body or "", memory.MAX_PROPOSAL_CHARS)
    except TextRefused as e:
        raise conversation.Refused("bad_text", f"the lesson's {e}") from None
    serves = None if every_repo else repo if repo is not None else old.repo
    if body == old.body and serves == old.repo:
        where = f"runs in {serves}" if serves is not None else "every run"
        raise conversation.Refused("unchanged", f"lesson {lesson_id} already says that, to {where}")
    now = datetime.now(UTC)
    stamp = db.format_time(now)
    with db.transaction(conn):
        # Out of force first: the journal holds one lesson in force under a key.
        sql.execute(conn, sql.update("memories").set(status=MemoryStatus.SUPERSEDED).where("id = ?", old.id))
        cur = sql.execute(
            conn,
            sql.insert(
                "memories",
                scope=MemoryScope.LESSON,
                repo=serves,
                key=old.key,
                body=body,
                status=MemoryStatus.ACTIVE,
                author=MemoryAuthor.OPERATOR,
                supersedes=old.id,
                promoted_from=old.id,
                created_at=stamp,
                approved_at=stamp,
                review_at=db.format_time(now + timedelta(days=memory.REVIEW_DAYS)),
            ),
        )
        new_id = int(cur.lastrowid or 0)
        sql.execute(
            conn,
            sql.update("memories")
            .set(why=f"edited into lesson {new_id}", invalidated_at=stamp)
            .where("id = ?", old.id),
        )
    lesson = memory.get(conn, new_id)
    if lesson is None:
        raise RuntimeError(f"lesson {new_id} vanished")
    return Edited(
        lesson=lesson,
        replaced=old,
        version=memory.version(conn, lesson),
        served=config.memory.proposals is MemoryMode.USE,
    )


def _promotable(conn: sqlite3.Connection, config: Config, memory_id: int) -> records.Memory:
    # A note is promotable whatever its status: one its ticket's being done invalidated may hold what the work taught.
    conversation.check_operator()
    _check_on(config)
    found = memory.get(conn, memory_id)
    if found is None or found.scope is MemoryScope.LESSON:
        raise conversation.Refused("unknown", f"no proposal or note has id {memory_id}")
    if found.scope is MemoryScope.PROPOSAL and found.status is not MemoryStatus.PENDING:
        raise conversation.Refused("not_pending", f"proposal {memory_id} is {found.status}: {found.why}")
    if found.body is None:
        raise conversation.Refused("forgotten", f"note {memory_id}'s text is gone: {found.why}")
    return found


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
