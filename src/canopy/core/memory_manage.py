"""The operator's verbs on agent memory (DESIGN §28, Commands): forgetting and purging, and making lessons.

Each deletes bodies, never rows: a forgotten memory is a tombstone that keeps who wrote it and when. The delete runs
with `PRAGMA secure_delete` on, the search index is merged after it so it keeps no word of the text, and the
write-ahead log is checkpointed, so a purged poison or a leaked secret does not survive in free pages or the log. Only
the operator runs these, from `canopy memory` or the web UI: they refuse inside canopy's ticks and runs. The one
delete that runs in a tick is `expire`, garbage collection's (DESIGN §26), which deletes the same way only the text of
notes and proposals that left force before the cutoff the operator's `retention.memory_days` sets. A lesson is
made only here, from a proposal or a ticket's note the operator promotes, or from a lesson they edit: no agent writes
one. Neither changes a lesson's text in place: the new lesson supersedes the one before it, which keeps its text as
the lesson's history. A pin is the operator's too, and stays with the lesson's key through each new version.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import conversation, db, memory, records, sql
from canopy.core.memory_text import TextRefused, check_key, check_text
from canopy.core.vocab import MemoryAuthor, MemoryMode, MemoryScope, MemoryStatus

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from canopy.core.config import Config

#: The notes and proposals no longer in force: a lesson's text, its versions' included, is never expired.
RETIRED = sql.all_of(
    sql.frag("scope != ?", MemoryScope.LESSON),
    sql.in_("status", (MemoryStatus.SUPERSEDED, MemoryStatus.INVALID)),
)
#: When a retired memory left force: when it was invalidated, else when the first memory to supersede it was written.
_LEFT_FORCE_AT = sql.frag(
    "coalesce(invalidated_at, (SELECT min(n.created_at) FROM memories n WHERE n.supersedes = memories.id))",
)
#: What an expiry adds to the reason a memory left force, which it keeps.
EXPIRED_WHY = "text removed after retention.memory_days"
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
    found = records.select(records.Memory).where("id = ?", memory_id).one(conn)
    if found is None:
        raise conversation.Refused("unknown", f"no memory has id {memory_id}")
    if found.body is None:
        raise conversation.Refused("forgotten", f"memory {memory_id}'s text is already gone: {found.why}")
    return found, _scrub(conn, sql.frag("id = ?", memory_id), why="forgotten")


def purge(
    conn: sqlite3.Connection,
    *,
    ticket: str | None = None,
    run: int | None = None,
    every: bool = False,
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


def expire(conn: sqlite3.Connection, cutoff: str) -> Scrubbed:
    """Delete the text of every note and proposal that left force before `cutoff`, as `forget` deletes one.

    Garbage collection's pass runs it inside a tick, so it takes no operator check: the cutoff is the operator's
    `retention.memory_days`, and no memory in force is touched. Each keeps the reason it left force, with
    `EXPIRED_WHY` after it.

    Returns:
        What was deleted.
    """
    why = sql.frag("coalesce(why || '; ', '') || ?", EXPIRED_WHY)
    return _scrub(conn, retired_before(cutoff), why=why)


def retired_before(cutoff: str) -> sql.Fragment:
    """The condition naming the notes and proposals that left force before `cutoff`, a time as the journal stores it.

    It names the `memories` table unaliased, so it serves a query of it and an UPDATE of it alike. A memory with no time
    it left force, and every one for a cutoff of "", is never named.

    Returns:
        The condition, with its values.
    """
    return sql.all_of(RETIRED, sql.frag("{} < ?", _LEFT_FORCE_AT, cutoff))


def _scrub(conn: sqlite3.Connection, where: sql.Composable, *, why: sql.Arg) -> Scrubbed:
    """Set the body of every memory `where` names to NULL, securely, and checkpoint the log after it.

    Returns:
        How many bodies were deleted, and whether the checkpoint completed: a reader can hold it back, and the next
        checkpoint completes it.
    """
    before = int(sql.execute(conn, sql.frag("PRAGMA secure_delete")).fetchone()[0])
    sql.execute(conn, _SECURE_DELETE[1])
    try:
        with db.transaction(conn):
            cur = (
                records.update(records.Memory)
                .set(body=None, status=MemoryStatus.INVALID, why=why)
                .set_to("invalidated_at = coalesce(invalidated_at, ?)", db.now())
                .where("body IS NOT NULL")
                .where("{}", where)
                .run(conn)
            )
            count = cur.rowcount
            # The index's triggers marked the deleted words; merging its segments drops them, and frees the pages
            # that held them for `secure_delete` to zero. FTS5 takes the command as an INSERT: no row type's write.
            sql.execute(conn, sql.insert("memories_fts", memories_fts=sql.frag("'optimize'")))  # noqa: TID251
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
    note stays as it was, its ticket's. A lesson it supersedes that was pinned leaves its pin to the new one, which is
    then never due. At `record` the lesson is recorded and served to no run. `repos` are the workspace's repositories,
    which `repo` must be one of.

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
            records.update(records.Memory).set(status=MemoryStatus.SUPERSEDED).where("id = ?", old.id).run(conn)
        pinned_at = old.pinned_at if old is not None else None
        cur = records.insert(
            records.Memory,
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
            review_at=_review_at(now, pinned_at),
            pinned_at=pinned_at,
        ).run(conn)
        lesson_id = int(cur.lastrowid or 0)
        if old is not None:
            (
                records.update(records.Memory)
                .set(why=f"superseded by lesson {lesson_id}", invalidated_at=stamp)
                .where("id = ?", old.id)
                .run(conn)
            )
        if source.scope is MemoryScope.PROPOSAL:
            (
                records.update(records.Memory)
                .set(status=MemoryStatus.SUPERSEDED, why=f"promoted to lesson {lesson_id}", invalidated_at=stamp)
                .where("id = ?", source.id)
                .run(conn)
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
    (
        records.update(records.Memory)
        .set(status=MemoryStatus.INVALID, why="rejected", invalidated_at=db.now())
        .where("id = ?", proposal.id)
        .where("status = ?", MemoryStatus.PENDING)
        .run(conn)
    )
    return proposal


def renew(conn: sqlite3.Connection, config: Config, lesson_id: int) -> str | None:
    """Keep a lesson: it is due for review `REVIEW_DAYS` from now, and a run's report that it is wrong is cleared.

    A pinned lesson is never due, so renewing one only clears the report.

    Returns:
        When it is next due for review, as the journal stores it; None for a pinned lesson.

    Raises:
        Refused: (`inside_run`) inside one of canopy's ticks or runs; (`off`) proposals are off; (`unknown`) no
            lesson in force has the id.
    """
    found = _in_force(conn, config, lesson_id)
    due = _review_at(datetime.now(UTC), found.pinned_at)
    (
        records.update(records.Memory)
        .set(review_at=due, wrong_at=None, wrong_run_id=None)
        .where("id = ?", lesson_id)
        .run(conn)
    )
    return due


def pin(conn: sqlite3.Connection, config: Config, lesson_id: int) -> str:
    """Pin a lesson: it is never due for review, and a run is served it before every lesson not pinned.

    A run's report that it is wrong still raises `lesson_wrong` until the operator renews or forgets it.

    Returns:
        When it was pinned, as the journal stores it.

    Raises:
        Refused: (`inside_run`) inside one of canopy's ticks or runs; (`off`) proposals are off; (`unknown`) no
            lesson in force has the id; (`pinned`) it is pinned already.
    """
    found = _in_force(conn, config, lesson_id)
    if found.pinned_at is not None:
        raise conversation.Refused("pinned", f"lesson {lesson_id} is pinned already, since {found.pinned_at}")
    stamp = db.now()
    records.update(records.Memory).set(pinned_at=stamp, review_at=None).where("id = ?", lesson_id).run(conn)
    return stamp


def unpin(conn: sqlite3.Connection, config: Config, lesson_id: int) -> str:
    """Unpin a lesson: it is due for review `REVIEW_DAYS` from now, as one just renewed, and served as any other.

    Returns:
        When it is next due for review, as the journal stores it.

    Raises:
        Refused: (`inside_run`) inside one of canopy's ticks or runs; (`off`) proposals are off; (`unknown`) no
            lesson in force has the id; (`not_pinned`) it is not pinned.
    """
    found = _in_force(conn, config, lesson_id)
    if found.pinned_at is None:
        raise conversation.Refused("not_pinned", f"lesson {lesson_id} is not pinned")
    due = db.format_time(datetime.now(UTC) + timedelta(days=memory.REVIEW_DAYS))
    records.update(records.Memory).set(pinned_at=None, review_at=due).where("id = ?", lesson_id).run(conn)
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
    #: Whether the edit changed only the key, so the new version keeps the old one's review date, pin, any run's report
    #: that it is wrong, and its reads and citations.
    renamed_alone: bool
    #: Whether runs are served lessons now, rather than recording them.
    served: bool


def edit(
    conn: sqlite3.Connection,
    config: Config,
    lesson_id: int,
    *,
    text: str | None = None,
    key: str | None = None,
    repo: str | None = None,
    every_repo: bool = False,
    repos: Sequence[str] = (),
) -> Edited:
    """Write a lesson in force anew: in `text`, under `key`, for `repo`, or with `every_repo` for every one, as given.

    The new version takes `key` if given, else the lesson's own, supersedes the lesson, and is made from it, so the old
    one stays, with its text and key, as the lesson's history, and what runs read of it and said of it stays with the
    words they read. It is due for review `REVIEW_DAYS` on, or never while the lesson is pinned, with no run's report
    that it is wrong: in writing it, the operator vouched for it. An edit that changes only the key is the same words
    to the same runs, so the new version keeps the old one's review date, any report that it is wrong, and its
    citations, and counts its reads (`memory.renamed_from`). A key an earlier lesson had is free to take. `repos` are
    the workspace's repositories, which `repo` must be one of.

    Returns:
        The new version, the one it replaced, which version it is, whether only its key changed, and whether runs are
        served lessons now.

    Raises:
        Refused: (`inside_run`) inside one of canopy's ticks or runs; (`off`) proposals are off; (`unknown`) no lesson
            in force has the id; (`bad_key`) `key` is not a key; (`key_taken`) another lesson in force has `key`;
            (`unknown_repo`) `repo` is not in `repos`; (`bad_text`) the text is outside the bounds; (`unchanged`) it
            would say the same words, under the same key, to the same repositories.
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
    named = _new_key(conn, old, key)
    if repo is not None and repo not in repos:
        names = ", ".join(repos) or "none yet"
        raise conversation.Refused("unknown_repo", f"{repo!r} is not a repository in this workspace ({names})")
    try:
        body = check_text(text if text is not None else old.body or "", memory.MAX_PROPOSAL_CHARS)
    except TextRefused as e:
        raise conversation.Refused("bad_text", f"the lesson's {e}") from None
    serves = None if every_repo else repo if repo is not None else old.repo
    same_words = body == old.body and serves == old.repo
    if same_words and named == old.key:
        where = f"runs in {serves}" if serves is not None else "every run"
        raise conversation.Refused("unchanged", f"lesson {lesson_id} already says that, to {where}, as `{named}`")
    now = datetime.now(UTC)
    stamp = db.format_time(now)
    with db.transaction(conn):
        # Out of force first: the journal holds one lesson in force under a key.
        records.update(records.Memory).set(status=MemoryStatus.SUPERSEDED).where("id = ?", old.id).run(conn)
        cur = records.insert(
            records.Memory,
            scope=MemoryScope.LESSON,
            repo=serves,
            key=named,
            body=body,
            status=MemoryStatus.ACTIVE,
            author=MemoryAuthor.OPERATOR,
            supersedes=old.id,
            promoted_from=old.id,
            created_at=stamp,
            approved_at=stamp,
            # A rename alone is no new word from the operator: the review, any report, and the citations stay.
            review_at=old.review_at if same_words else _review_at(now, old.pinned_at),
            pinned_at=old.pinned_at,
            wrong_at=old.wrong_at if same_words else None,
            wrong_run_id=old.wrong_run_id if same_words else None,
            use_count=old.use_count if same_words else 0,
            last_used_at=old.last_used_at if same_words else None,
        ).run(conn)
        new_id = int(cur.lastrowid or 0)
        how = "edited" if named == old.key else "renamed" if same_words else "renamed and edited"
        (
            records.update(records.Memory)
            .set(why=f"{how} into lesson {new_id}", invalidated_at=stamp)
            .where("id = ?", old.id)
            .run(conn)
        )
    lesson = memory.get(conn, new_id)
    if lesson is None:
        raise RuntimeError(f"lesson {new_id} vanished")
    return Edited(
        lesson=lesson,
        replaced=old,
        version=memory.version(conn, lesson),
        renamed_alone=same_words,
        served=config.memory.proposals is MemoryMode.USE,
    )


def _new_key(conn: sqlite3.Connection, old: records.Memory, key: str | None) -> str:
    """The key an edit of `old` writes its new version under: `key`, checked, or the lesson's own.

    Returns:
        The key.

    Raises:
        Refused: (`bad_key`) `key` is not a key; (`key_taken`) another lesson in force has it.
    """
    if key is None:
        return old.key
    try:
        named = check_key(key)
    except TextRefused as e:
        raise conversation.Refused("bad_key", f"the lesson's {e}") from None
    # The journal holds one lesson in force under a key, whichever repositories each serves.
    taken = next((m for m in memory.active_lessons(conn) if m.key == named and m.id != old.id), None)
    if taken is not None:
        raise conversation.Refused("key_taken", f"lesson {taken.id} is in force under `{named}`")
    return named


def _in_force(conn: sqlite3.Connection, config: Config, lesson_id: int) -> records.Memory:
    conversation.check_operator()
    _check_on(config)
    found = memory.get(conn, lesson_id)
    if found is None or found.scope is not MemoryScope.LESSON or found.status is not MemoryStatus.ACTIVE:
        raise conversation.Refused("unknown", f"no lesson in force has id {lesson_id}")
    return found


def _review_at(now: datetime, pinned_at: str | None) -> str | None:
    # A pinned lesson is never due, so it keeps no review date.
    return None if pinned_at is not None else db.format_time(now + timedelta(days=memory.REVIEW_DAYS))


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
            "off",
            "memory.proposals is off: set it to record or use to build lessons up, or to serve them",
        )
