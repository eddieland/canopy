"""The index of what every session the runtime keeps said, did, and read (ROADMAP M72, stage 2): `sessions.db`.

While `sessions.search` is `text`, the loop's wait between live ticks keeps an index of the words of every session the
runtime keeps, in `sessions.db` in the state directory, beside the journal and private as it is (D053). It is a cache,
never the journal: every row comes from the runtime's record (`canopy.runtime.indexed_text`), so it has no migration.
It is dropped whole and built again when its shape, the cut of the text it indexes, or `sessions.exclude` changes, and
removed when `sessions.search` goes below `text` (`remove`). It holds an index of words and no text of its own, as
memory's index holds none (DESIGN §28): an FTS5 table that keeps no content, a row per message, each with the session's
title beside it, so a session is found when its title and one of its messages hold every word between them, and a row
for the title alone. A hit's snippet is read from the runtime's record when a search is made
(`canopy.core.session_search`).

Of a session outside canopy, every part of the cut is indexed; of one canopy started (`runtime_sessions.canopy_among`),
its title and what its agent wrote, did, and read, never what it was sent: a run's prompt is the journal's text
rendered, which the journal's search finds already. A message and a session are each indexed up to a bound, and a
session past one is marked cut, so no session a run wrote fills the disk (TRUST_MODEL T3).

Each step (`step`) is bounded in time: first what changed since the last read, oldest first, from where it stopped, each
session indexed again whole in place of its rows; then, until the first build is done, the sessions before the oldest
read, newest first, so last week's are found before last year's. Once a day a step drops the sessions the runtime no
longer keeps (`SWEEP_EVERY`). Only the loop writes it, and it is queried through `canopy.core.sql`, as the journal is
(D125). Deleting from an index that keeps no content needs SQLite 3.43; an older one searches titles (`why_titles`).
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from canopy.core import db, records, runtime_sessions, session_sizes, sql
from canopy.runtime import indexed_text

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
    from pathlib import Path

    from canopy.core.config import SessionSearch
    from canopy.core.session_sizes import Cut
    from canopy.runtime.implementation import Version
    from canopy.runtime.report import MessageText, SessionCursor, SessionHead

#: The index's file, in the workspace's state directory.
FILE_NAME: Final = "sessions.db"
#: The index's shape: its tables and how it splits text into words. A new one drops the index, and builds it again.
SHAPE: Final = 1
#: The cut of a session's text the index holds, as the operator chose it from stage 0's measurement (ROADMAP M72).
CUT: Final[Cut] = "read"
#: How many characters of one message are indexed, how many of one session, and how many of its messages: far more than
#: a message or a session holds that a person reads, and few enough that a session a run wrote cannot fill the disk.
MAX_MESSAGE_CHARS: Final = 65_536
MAX_SESSION_CHARS: Final = 4 * 1024 * 1024
MAX_MESSAGES: Final = 10_000
#: How long one step takes new sessions for, in seconds: the session it is indexing when the time runs out is finished,
#: each within its own read's bound, so the wait it runs in still ends when it is due.
STEP_SECONDS: Final = 1.0
#: How many sessions a step reads at once.
BATCH: Final = 50
#: How often a step drops the sessions the runtime no longer keeps.
SWEEP_EVERY: Final = timedelta(days=1)
#: The first SQLite that can delete a row from an index that keeps no content.
CONTENTLESS_DELETE: Final = session_sizes.CONTENTLESS_DELETE
#: What `why_titles` says of a SQLite too old to keep the index.
OLD_SQLITE: Final = (
    f"sessions.search is text, but this Python's SQLite, {sqlite3.sqlite_version}, is older than 3.43, which the "
    "index of sessions' text needs: sessions are found by their titles"
)
#: The index's tables: the step's state, a row for each session indexed, a row for each of its messages, and the words,
#: splitting text into words as memory's index does (DESIGN §28), so a word matches as memory's search matches it.
_SCHEMA: Final[tuple[sql.Fragment, ...]] = (
    sql.frag(
        "CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK (id = 1), setting TEXT NOT NULL, front_ms INTEGER,"
        " front_id TEXT, back_ms INTEGER, back_id TEXT, built INTEGER NOT NULL DEFAULT 0, read_at TEXT,"
        " swept_at TEXT, passed_over INTEGER NOT NULL DEFAULT 0, error TEXT)",
    ),
    sql.frag(
        "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, record TEXT NOT NULL, updated_ms INTEGER NOT NULL,"
        " ours INTEGER NOT NULL, cut INTEGER NOT NULL) WITHOUT ROWID",
    ),
    sql.frag("CREATE TABLE messages (row INTEGER PRIMARY KEY, session_id TEXT NOT NULL, message_id TEXT)"),
    sql.frag("CREATE INDEX messages_session ON messages (session_id)"),
    sql.frag(
        "CREATE VIRTUAL TABLE words USING fts5(title, sent, body, content='', contentless_delete=1,"
        " tokenize='porter unicode61')",
    ),
)
#: The sessions among a JSON array of ids.
_AMONG: Final = "session_id IN (SELECT value FROM json_each(?))"


@dataclass(frozen=True)
class Stepped:
    """What one step of keeping the index in step did."""

    #: How many sessions it indexed, and how many it dropped as ones the runtime no longer keeps.
    indexed: int = 0
    dropped: int = 0
    #: Whether more waits to be read: the first build is not done, or the step stopped before a page's end.
    behind: bool = False
    #: Why the runtime's record could not be read; None when it was.
    error: str | None = None


@dataclass(frozen=True)
class Progress:
    """How far the index has read the runtime's record, and when, as `canopy sessions` and the web UI say it."""

    #: How many sessions it holds.
    sessions: int
    #: The update of the newest session read, as a journal time; None before the first.
    through: str | None
    #: While the first build goes on, the update of the oldest session read so far; None once it is done.
    back_to: str | None
    #: Whether the first build has read every session.
    built: bool
    #: When a step last read the record; None before the first.
    read_at: str | None
    #: Why the last read failed, in canopy's words; None unless it did.
    error: str | None
    #: How many sandbox roles' records the last read could not read, and passed over whole.
    passed_over: int
    #: Whether it was built as `sessions.exclude` now says: False until the loop's next step builds it again.
    current: bool
    #: Its files' size, in bytes.
    size_bytes: int


def why_titles(*, version: Version) -> str | None:
    """Say why `sessions.search = "text"` searches titles: the runtime `version` runs, or SQLite, cannot keep the index.

    Returns:
        Why, in canopy's words; None when the index can be kept.
    """
    unindexed = indexed_text.unindexed(version=version)
    if unindexed is not None:
        return f"sessions.search is text, but {unindexed}: sessions are found by their titles"
    if sqlite3.sqlite_version_info < CONTENTLESS_DELETE:
        return OLD_SQLITE
    return None


def effective(search: SessionSearch, *, version: Version) -> SessionSearch:
    """What `search`, `sessions.search`, comes to: `titles` for `text` when the index cannot be kept (`why_titles`).

    Returns:
        The setting in force.
    """
    return "titles" if search == "text" and why_titles(version=version) is not None else search


def path(state_dir: Path) -> Path:
    """Where the index is: `sessions.db` in the state directory.

    Returns:
        Its path, whether or not it exists.
    """
    return state_dir / FILE_NAME


def size(state_dir: Path) -> int | None:
    """The bytes the index's files take: the database, its WAL, and its shared memory.

    Returns:
        Their size; None when there is no index.
    """
    if not path(state_dir).is_file():
        return None
    return sum(_regular_size(f) for f in _files(state_dir))


def remove(state_dir: Path) -> bool:
    """Remove the index, as a setting below `text` does.

    Returns:
        Whether there was one to remove.
    """
    removed = False
    for each in _files(state_dir):
        with contextlib.suppress(FileNotFoundError):
            each.unlink()
            removed = True
    return removed


def step(
    journal: sqlite3.Connection,
    state_dir: Path,
    *,
    version: Version,
    exclude: Sequence[str],
    clock: Callable[[], float] = time.monotonic,
    seconds: float = STEP_SECONDS,
    now: datetime | None = None,
) -> Stepped:
    """Keep the index in step with the runtime `version` runs: one step, which takes new sessions for `seconds`.

    `journal` says which sessions are canopy's, and `exclude` is `sessions.exclude`, whose directories' sessions are
    never indexed. An index built under another shape, cut, or `exclude` is dropped and built again. Due once a day at
    `now`, the step first drops the sessions the runtime no longer keeps.

    Returns:
        What it did, and whether more waits to be read.
    """
    moment = now or datetime.now(UTC)
    with _opened(state_dir, _setting(exclude)) as idx:
        state = _state(idx)
        dropped = _sweep(idx, version) if _sweep_due(state, moment) else None
        if dropped is not None:
            state.swept_at = db.format_time(moment)
        reading = _Reading(idx, journal, state_dir, version, exclude, clock() + seconds, clock)
        page = None
        caught_up = True
        # What changed since the last read, oldest first, from where it stopped.
        if state.front is not None or state.built:
            page = indexed_text.heads(state.front, newest_first=False, limit=BATCH, version=version)
            state.front = reading.rows(page.rows) or state.front
            caught_up = reading.whole and len(page.rows) < BATCH
        # Then, until the first build is done, the sessions before the oldest read, newest first: at least one, when
        # nothing changed since the last read.
        if (
            not state.built
            and (page is None or page.outcome != "failed")
            and (not reading.indexed or not reading.late())
        ):
            page = indexed_text.heads(state.back, newest_first=True, limit=BATCH, version=version)
            if state.front is None and page.rows:
                state.front = page.rows[0][0]
            state.back = reading.rows(page.rows) or state.back
            state.built = page.outcome != "failed" and reading.whole and len(page.rows) < BATCH
        state.read_at = db.format_time(moment)
        state.error = page.error if page is not None else None
        state.passed_over = page.passed_over if page is not None else 0
        _write_state(idx, state)
        idx.commit()
    return Stepped(
        indexed=reading.indexed,
        dropped=dropped or 0,
        # A read that failed is not behind: the next waits the usual gap, rather than retrying every few seconds.
        behind=state.error is None and (not state.built or not caught_up),
        error=state.error,
    )


def progress(state_dir: Path, exclude: Sequence[str]) -> Progress | None:
    """How far the index has read the runtime's record, with `exclude`, `sessions.exclude`, in force.

    Returns:
        Its progress; None when there is no index, or it cannot be read.
    """
    found = size(state_dir)
    if found is None:
        return None
    try:
        with read_only(state_dir) as idx:
            state = _state(idx)
            count = records.fetch_value(idx, int, sql.select("count(*)").from_("sessions")) or 0
    except sqlite3.Error:
        return None
    return Progress(
        sessions=count,
        through=_journal_time(state.front[0]) if state.front is not None else None,
        back_to=_journal_time(state.back[0]) if state.back is not None and not state.built else None,
        built=state.built,
        read_at=state.read_at,
        error=state.error,
        passed_over=state.passed_over,
        current=state.setting == _setting(exclude),
        size_bytes=found,
    )


@contextlib.contextmanager
def read_only(state_dir: Path) -> Iterator[sqlite3.Connection]:
    """Open the index read-only, for a search: the loop alone writes it.

    Yields:
        The connection, closed when the block ends.

    Raises:
        sqlite3.Error: there is no index, or it cannot be read.
    """
    conn = sqlite3.connect(f"{path(state_dir).absolute().as_uri()}?mode=ro", uri=True, timeout=5.0)
    try:
        yield conn
    finally:
        conn.close()


@dataclass
class _State:
    """The step's state, as `meta` keeps it."""

    setting: str
    #: The newest session read, oldest first from the first, and the oldest read, newest first from the newest.
    front: SessionCursor | None
    back: SessionCursor | None
    built: bool
    read_at: str | None
    swept_at: str | None
    passed_over: int
    error: str | None


@dataclass
class _Reading:
    """One step's reading of sessions: what it reads with, until when, and what it has done."""

    idx: sqlite3.Connection
    journal: sqlite3.Connection
    state_dir: Path
    version: Version
    exclude: Sequence[str]
    deadline: float
    clock: Callable[[], float]
    indexed: int = 0
    #: Whether the last rows given were each read, none left for the next step.
    whole: bool = True

    def late(self) -> bool:
        """Return whether the step's time for new sessions has run out."""
        return self.clock() >= self.deadline

    def rows(self, rows: Sequence[tuple[SessionCursor, SessionHead | None]]) -> SessionCursor | None:
        """Index each session of `rows` in turn, at least one, until the step's time runs out.

        Returns:
            Where the last one read sorts, for the cursor; None when none was.
        """
        heads = [h for _, h in rows if h is not None]
        ours = runtime_sessions.canopy_among(self.journal, heads, self.state_dir) if heads else set()
        excluded = _excluded(self.idx, heads, self.exclude)
        last: SessionCursor | None = None
        for n, (at, head) in enumerate(rows):
            if n and self.late():
                self.whole = False
                return last
            if head is not None and head.session_id in excluded:
                _drop(self.idx, [head.session_id])
            elif head is not None:
                _replace(self.idx, head, ours=head.session_id in ours, version=self.version)
                self.indexed += 1
            last = at
        self.whole = True
        return last


# What the index is built under: its shape, its cut, and `sessions.exclude`, as JSON. A change to any drops it.
def _setting(exclude: Sequence[str]) -> str:
    return json.dumps({"shape": SHAPE, "cut": CUT, "exclude": list(exclude)})


# The index, opened to be written, built anew when it was built under another setting or cannot be read.
@contextlib.contextmanager
def _opened(state_dir: Path, setting: str) -> Iterator[sqlite3.Connection]:
    conn = _current(state_dir, setting)
    if conn is None:
        remove(state_dir)
        conn = _connect(state_dir)
        for statement in _SCHEMA:
            sql.execute(conn, statement)
        sql.execute(conn, sql.frag("INSERT INTO meta (id, setting) VALUES (1, ?)", setting))
        conn.commit()
    try:
        yield conn
    finally:
        conn.close()


# The index, opened, when it is one built under `setting`; else None, nothing left open.
def _current(state_dir: Path, setting: str) -> sqlite3.Connection | None:
    if not path(state_dir).is_file():
        return None
    conn = None
    try:
        conn = _connect(state_dir)
        if _state(conn).setting == setting:
            return conn
    except sqlite3.Error:
        pass
    if conn is not None:
        conn.close()
    return None


def _connect(state_dir: Path) -> sqlite3.Connection:
    at = path(state_dir)
    at.touch(mode=0o600)
    conn = sqlite3.connect(at, timeout=5.0)
    try:
        # A cache: what a crash loses is read again.
        sql.execute(conn, sql.frag("PRAGMA journal_mode = WAL"))
        sql.execute(conn, sql.frag("PRAGMA synchronous = NORMAL"))
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def _state(idx: sqlite3.Connection) -> _State:
    row = sql.execute(
        idx,
        sql.select(
            "setting, front_ms, front_id, back_ms, back_id, built, read_at, swept_at, passed_over, error",
        ).from_("meta"),
    ).fetchone()
    if row is None:
        raise sqlite3.DatabaseError("the index has no state")
    setting, front_ms, front_id, back_ms, back_id, built, read_at, swept_at, passed_over, error = row
    return _State(
        setting=str(setting),
        front=(int(front_ms), str(front_id)) if front_ms is not None and front_id is not None else None,
        back=(int(back_ms), str(back_id)) if back_ms is not None and back_id is not None else None,
        built=bool(built),
        read_at=read_at,
        swept_at=swept_at,
        passed_over=int(passed_over),
        error=error,
    )


def _write_state(idx: sqlite3.Connection, state: _State) -> None:
    front_ms, front_id = state.front or (None, None)
    back_ms, back_id = state.back or (None, None)
    sql.execute(
        idx,
        sql.frag(
            "UPDATE meta SET front_ms = ?, front_id = ?, back_ms = ?, back_id = ?, built = ?, read_at = ?,"
            " swept_at = ?, passed_over = ?, error = ? WHERE id = 1",
            front_ms,
            front_id,
            back_ms,
            back_id,
            state.built,
            state.read_at,
            state.swept_at,
            state.passed_over,
            state.error,
        ),
    )


def _sweep_due(state: _State, now: datetime) -> bool:
    return state.swept_at is None or db.parse_time(state.swept_at) <= now - SWEEP_EVERY


# Drop each session the runtime's records no longer keep: of a record read, those it does not hold; of one that is
# gone, every one. What a record that could not be read holds stays. Returns how many were dropped, or None when the
# runtime's record could not be read, so nothing was.
def _sweep(idx: sqlite3.Connection, version: Version) -> int | None:
    kept = indexed_text.kept(version=version)
    if kept.outcome == "failed":
        return None
    gone = [
        str(session_id)
        for session_id, record in sql.execute(idx, sql.select("session_id, record").from_("sessions"))
        if str(record) not in kept.unread and session_id not in kept.records.get(str(record), frozenset())
    ]
    _drop(idx, gone)
    return len(gone)


# The ids of those of `heads` in a directory one of `exclude`'s globs names, as `runtime_sessions.excluded` reads one.
def _excluded(idx: sqlite3.Connection, heads: Iterable[SessionHead], exclude: Collection[str]) -> set[str]:
    if not exclude:
        return set()
    given = json.dumps([[h.session_id, h.directory] for h in heads])
    query = (
        sql.select("session_id")
        .from_(
            "(SELECT json_extract(value, '$[0]') AS session_id, json_extract(value, '$[1]') AS directory"
            " FROM json_each(?))",
            given,
        )
        .where("{}", runtime_sessions.excluded(exclude))
    )
    return set(records.fetch_values(idx, str, query))


# Index session `head` again whole, in place of its rows: its title, and each of its messages that holds text of the
# cut, a session of canopy's what it was sent left out. One its record no longer keeps is dropped, and one its record
# could not be read is kept by its title, cut.
def _replace(idx: sqlite3.Connection, head: SessionHead, *, ours: bool, version: Version) -> None:
    read = indexed_text.texts(
        head,
        max_messages=MAX_MESSAGES,
        max_chars=MAX_MESSAGE_CHARS,
        max_total=MAX_SESSION_CHARS,
        version=version,
    )
    _drop(idx, [head.session_id])
    if read.outcome == "missing":
        return
    title = head.title or ""
    rows: list[tuple[str | None, str, str]] = [(None, "", "")]
    cut = read.cut or read.outcome == "failed"
    for message_id, parts in _messages(read.parts).items():
        sent = "" if ours else _joined(p for p in parts if p.part == "sent")
        body = _joined(p for p in parts if p.part != "sent")
        if len(sent) + len(body) > MAX_MESSAGE_CHARS:
            cut = True
            sent = sent[:MAX_MESSAGE_CHARS]
            body = body[: MAX_MESSAGE_CHARS - len(sent)]
        if sent or body:
            rows.append((message_id, sent, body))
    sql.execute(
        idx,
        sql.frag(
            "INSERT INTO sessions (session_id, record, updated_ms, ours, cut) VALUES (?, ?, ?, ?, ?)",
            head.session_id,
            head.record,
            head.updated_ms,
            ours,
            cut,
        ),
    )
    for message_id, sent, body in rows:
        row = sql.execute(
            idx,
            sql.frag("INSERT INTO messages (session_id, message_id) VALUES (?, ?)", head.session_id, message_id),
        ).lastrowid
        sql.execute(
            idx,
            sql.frag("INSERT INTO words (rowid, title, sent, body) VALUES (?, ?, ?, ?)", row, title, sent, body),
        )


# Each message's parts of the cut, by its id, in the order of the messages.
def _messages(parts: Iterable[MessageText]) -> dict[str, list[MessageText]]:
    found: dict[str, list[MessageText]] = {}
    for part in parts:
        if part.part in session_sizes.CUTS[CUT]:
            found.setdefault(part.message_id, []).append(part)
    return found


def _joined(parts: Iterable[MessageText]) -> str:
    return "\n".join(p.text for p in parts)


# Every row of the sessions `ids` names, dropped.
def _drop(idx: sqlite3.Connection, ids: Sequence[str]) -> None:
    if not ids:
        return
    among = json.dumps(list(ids))
    sql.execute(
        idx,
        sql.frag("DELETE FROM words WHERE rowid IN (SELECT row FROM messages WHERE {})", sql.frag(_AMONG, among)),
    )
    sql.execute(idx, sql.frag("DELETE FROM messages WHERE {}", sql.frag(_AMONG, among)))
    sql.execute(idx, sql.frag("DELETE FROM sessions WHERE {}", sql.frag(_AMONG, among)))


def _files(state_dir: Path) -> list[Path]:
    at = path(state_dir)
    return [at, at.with_name(f"{at.name}-wal"), at.with_name(f"{at.name}-shm")]


def _regular_size(file: Path) -> int:
    try:
        return file.lstat().st_size if file.is_file() and not file.is_symlink() else 0
    except OSError:
        return 0


def _journal_time(ms: int) -> str:
    return db.format_time(datetime.fromtimestamp(ms / 1000, UTC))
