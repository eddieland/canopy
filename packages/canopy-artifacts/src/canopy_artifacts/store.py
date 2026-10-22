"""The local store's artifacts, versions, threads, comments, and the feed of changes to them (DESIGN §38).

One SQLite database, `artifacts.db`, in a directory of the operator's that nobody else can read: canopy's state
directory in use, never the journal, which nothing a worker writes reaches while it runs (§27). Its schema is its own,
versioned by SQLite's `user_version`, and never shared with canopy's.

Every change to a comment or a thread takes the next `seq` of one sequence across the store, inside the write that
makes it. SQLite lets one write at a time commit, so changes commit in `seq` order, and a reader never sees a `seq`
before every lower one is visible: nothing appears below a cursor a reader has passed.

A `Scope` is what a token is to a hosted store: the namespace every call is held to, who writes, the origin pairs set
on every artifact made, and whether it may write at all. The command line sets it, never a tool's caller.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import sqlite3
import stat
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from canopy_artifacts.text import CONTEXT, Anchor, ContentType, locate, visible_text

#: The database's file, in the store's directory.
DATABASE = "artifacts.db"
#: The id of the one person the local store knows, on whose behalf its agents write.
OPERATOR = "operator"
#: How every comment and change written here arrived. The web UI's will be `web`.
VIA = "mcp"
#: The most characters of an artifact's title, a version's content, and a comment's body.
MAX_TITLE = 200
MAX_CONTENT = 2_000_000
MAX_BODY = 4000
#: The most characters of an anchor's passage: a whole section of a page, as a plan's may be.
MAX_EXACT = 4000
#: The most origin pairs an artifact carries, and the most characters of a pair's key and value.
MAX_ORIGIN = 16
MAX_ORIGIN_KEY = 64
MAX_ORIGIN_VALUE = 256
#: How many artifacts a page of `artifacts` holds, and the most changes one of the feed's may.
LIST_PAGE = 50
MAX_FEED = 200
#: The most digits of a cursor `artifacts` gives: a row's number, which SQLite holds in 64 bits.
_CURSOR_DIGITS = 18
#: How long a write waits for another process's to commit before it fails.
_BUSY_SECONDS = 30
#: The schema, in steps: step N takes a database at `user_version` N to N + 1. Never edit a step; add one.
_SCHEMA: Sequence[Sequence[str]] = (
    (
        """CREATE TABLE artifacts (
            n INTEGER PRIMARY KEY,
            id TEXT NOT NULL UNIQUE,
            namespace TEXT NOT NULL,
            title TEXT NOT NULL,
            origin TEXT NOT NULL,
            latest_version INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE versions (
            artifact_id TEXT NOT NULL REFERENCES artifacts (id),
            n INTEGER NOT NULL,
            content_type TEXT NOT NULL CHECK (content_type IN ('text/html', 'text/markdown')),
            sha256 TEXT NOT NULL,
            content TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (artifact_id, n)
        )""",
        """CREATE TABLE authors (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('person', 'agent')),
            on_behalf_of TEXT
        )""",
        """CREATE TABLE threads (
            n INTEGER PRIMARY KEY,
            id TEXT NOT NULL UNIQUE,
            artifact_id TEXT NOT NULL REFERENCES artifacts (id),
            exact TEXT,
            prefix TEXT,
            suffix TEXT,
            anchored_version INTEGER NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('open', 'resolved')),
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE comments (
            n INTEGER PRIMARY KEY,
            id TEXT NOT NULL UNIQUE,
            thread_id TEXT NOT NULL REFERENCES threads (id),
            seq INTEGER NOT NULL,
            author_id TEXT NOT NULL REFERENCES authors (id),
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            edited_at TEXT,
            deleted_at TEXT,
            via TEXT NOT NULL CHECK (via IN ('web', 'mcp'))
        )""",
        """CREATE TABLE changes (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK (
                kind IN ('comment_created', 'comment_edited', 'comment_deleted', 'thread_resolved', 'thread_reopened')
            ),
            thread_id TEXT NOT NULL REFERENCES threads (id),
            comment_id TEXT REFERENCES comments (id),
            author_id TEXT NOT NULL REFERENCES authors (id),
            via TEXT NOT NULL CHECK (via IN ('web', 'mcp')),
            at TEXT NOT NULL
        )""",
        "CREATE INDEX threads_by_artifact ON threads (artifact_id)",
        "CREATE INDEX comments_by_thread ON comments (thread_id)",
    ),
)


class Code(StrEnum):
    """Why a call is refused, the code its tool error carries."""

    #: No artifact, version, or thread has that id.
    NOT_FOUND = "not_found"
    #: It is in another namespace than the scope's.
    OUT_OF_SCOPE = "out_of_scope"
    #: A title, content, body, anchor, or origin is over its bound.
    TOO_LONG = "too_long"
    #: The anchor's words are not in the artifact's latest version.
    ANCHOR_NOT_FOUND = "anchor_not_found"
    #: The scope may not write.
    READ_ONLY = "read_only"
    #: An argument the tool's schema takes, but the store cannot use: a blank body, an unreadable cursor.
    INVALID = "invalid"


class Refused(Exception):  # noqa: N818  (a tool error, not a failure)
    """A call the store refuses, with the code that says why."""

    def __init__(self, code: Code, message: str) -> None:
        """Refuse with `code`, saying why in `message`."""
        super().__init__(message)
        self.code = code


class StoreError(Exception):
    """The store's directory or database cannot be used, so nothing is served."""


@dataclass(frozen=True)
class Author:
    """Who wrote a comment, or resolved a thread."""

    #: Stable for the life of the store.
    id: str
    display_name: str
    kind: Literal["person", "agent"]
    #: For an agent, the person it writes for.
    on_behalf_of: str | None = None


def agent(name: str) -> Author:
    """Name an agent writing on the operator's behalf, as every caller of the local store's tools is.

    Returns:
        The author, `agent:NAME`.
    """
    return Author(f"agent:{name}", name, "agent", OPERATOR)


@dataclass(frozen=True)
class Scope:
    """What every call is held to, as a hosted store's token holds it."""

    #: The namespace an artifact is made in, and the only one a call may read or write.
    namespace: str
    #: Who writes.
    author: Author
    #: Origin pairs set on every artifact made, over the caller's.
    origin: Mapping[str, str] = field(default_factory=dict[str, str])
    #: Whether every write is refused.
    read_only: bool = False


def open_store(directory: Path, scope: Scope) -> Store:
    """Open the store in `directory`, making it if it is not there, held to `scope`.

    Returns:
        The store, to be closed.

    Raises:
        StoreError: The directory is not the operator's alone, or the database cannot be opened.
    """
    _private_dir(directory)
    try:
        conn = sqlite3.connect(directory / DATABASE, isolation_level=None, timeout=_BUSY_SECONDS)
    except sqlite3.Error as e:
        raise StoreError(f"cannot open {directory / DATABASE}: {e}") from e
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        _migrate(conn)
    except sqlite3.Error as e:
        conn.close()
        raise StoreError(f"cannot open {directory / DATABASE}: {e}") from e
    return Store(conn, scope)


class Store:
    """The store, through one connection, every call held to one scope."""

    def __init__(self, conn: sqlite3.Connection, scope: Scope) -> None:
        """Serve `conn`'s database, held to `scope`."""
        self._conn = conn
        self.scope = scope

    def close(self) -> None:
        """Close the connection."""
        self._conn.close()

    def publish(
        self,
        *,
        title: str,
        content_type: ContentType,
        content: str,
        origin: Mapping[str, str] | None = None,
        artifact_id: str | None = None,
    ) -> dict[str, object]:
        """Make an artifact, or with `artifact_id`, add a version to one. Origin is set when an artifact is made.

        Returns:
            Its id, the new version's number, and its url.

        Raises:
            Refused: `read_only`; `too_long` for a title, content, or origin over its bound; `invalid` for a blank
                title, or an origin given with `artifact_id`; `not_found` or `out_of_scope` for `artifact_id`.
        """
        self._writable()
        if not title.strip():
            raise Refused(Code.INVALID, "an artifact's title must not be blank")
        _bounded("title", title, MAX_TITLE)
        _bounded("content", content, MAX_CONTENT)
        if artifact_id is not None and origin:
            raise Refused(Code.INVALID, "an artifact's origin is set when it is made; omit it to add a version")
        pairs: dict[str, str] = _origin({**(origin or {}), **self.scope.origin}) if artifact_id is None else {}
        text = visible_text(content_type, content)
        digest = hashlib.sha256(content.encode()).hexdigest()
        now = _now()
        with self._transaction(write=True):
            if artifact_id is None:
                artifact_id, version = _id("a"), 1
                self._conn.execute(
                    "INSERT INTO artifacts (id, namespace, title, origin, latest_version, created_at)"
                    " VALUES (?, ?, ?, ?, 1, ?)",
                    (artifact_id, self.scope.namespace, title, json.dumps(pairs, ensure_ascii=False), now),
                )
            else:
                version = int(self._artifact(artifact_id)["latest_version"]) + 1
                self._conn.execute(
                    "UPDATE artifacts SET latest_version = ?, title = ? WHERE id = ?",
                    (version, title, artifact_id),
                )
            self._conn.execute(
                "INSERT INTO versions (artifact_id, n, content_type, sha256, content, text, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, version, content_type, digest, content, text, now),
            )
        return {"artifact_id": artifact_id, "version": version, "url": url(artifact_id, version)}

    def read(self, artifact_id: str, version: int | None = None) -> dict[str, object]:
        """Read a version of an artifact, its latest unless `version` names one.

        Returns:
            The artifact, the version, its content, and its text.

        Raises:
            Refused: `not_found` or `out_of_scope` for the artifact, `not_found` for a version it does not have.
        """
        with self._transaction(write=False):
            artifact = self._artifact(artifact_id)
            found = self._version(artifact, version)
        return {
            "artifact": _artifact_json(artifact),
            "version": _version_json(found),
            "content": found["content"],
            "text": found["text"],
        }

    def artifacts(self, origin: Mapping[str, str] | None = None, cursor: str | None = None) -> dict[str, object]:
        """List the scope's artifacts whose origin holds every pair of `origin`, newest first, a page at a time.

        Returns:
            A page of artifacts, and the cursor of the next page, None after the last.

        Raises:
            Refused: `invalid` for a cursor this store did not give.
        """
        before = None
        if cursor is not None:
            if not (cursor.isascii() and cursor.isdigit() and len(cursor) <= _CURSOR_DIGITS):
                raise Refused(Code.INVALID, f"{cursor!r} is not a cursor this store gave")
            before = int(cursor)
        rows = self._conn.execute(
            # The artifact's origin holds every pair of the filter, a JSON object.
            "SELECT a.* FROM artifacts a WHERE a.namespace = :namespace AND (:before IS NULL OR a.n < :before)"
            " AND (SELECT count(*) FROM json_each(a.origin) o JOIN json_each(:filter) f"
            " ON o.key = f.key AND o.value = f.value) = (SELECT count(*) FROM json_each(:filter))"
            " ORDER BY a.n DESC LIMIT :limit",
            {
                "namespace": self.scope.namespace,
                "before": before,
                "filter": json.dumps(dict(origin or {})),
                "limit": LIST_PAGE + 1,
            },
        ).fetchall()
        page = rows[:LIST_PAGE]
        more = len(rows) > LIST_PAGE
        return {
            "artifacts": [_artifact_json(row) for row in page],
            "next_cursor": str(page[-1]["n"]) if more else None,
        }

    def threads(
        self,
        artifact_id: str,
        *,
        state: Literal["open", "resolved"] | None = None,
        version: int | None = None,
    ) -> dict[str, object]:
        """List an artifact's threads, oldest first, each anchor looked for in a version, its latest unless named.

        Returns:
            The threads, each with its comments, oldest first, and its anchor's status there: `found`, or
            `passage_gone` when its words are not in that version; None for a thread on the whole artifact.

        Raises:
            Refused: `not_found` or `out_of_scope` for the artifact, `not_found` for a version it does not have.
        """
        with self._transaction(write=False):
            artifact = self._artifact(artifact_id)
            text = str(self._version(artifact, version)["text"])
            threads = self._conn.execute(
                "SELECT * FROM threads WHERE artifact_id = ? AND (? IS NULL OR state = ?) ORDER BY n",
                (artifact_id, state, state),
            ).fetchall()
            comments = self._conn.execute(
                "SELECT c.*, w.display_name, w.kind, w.on_behalf_of FROM comments c"
                " JOIN threads t ON t.id = c.thread_id JOIN authors w ON w.id = c.author_id"
                " WHERE t.artifact_id = ? ORDER BY c.n",
                (artifact_id,),
            ).fetchall()
        listed: list[dict[str, object]] = []
        for thread in threads:
            anchor = _anchor(thread)
            found = None if anchor is None else "found" if locate(text, anchor) is not None else "passage_gone"
            listed.append(
                {
                    **_thread_json(thread),
                    "anchor_status": found,
                    "comments": [_comment_json(c) for c in comments if c["thread_id"] == thread["id"]],
                },
            )
        return {"artifact_id": artifact_id, "version": version or artifact["latest_version"], "threads": listed}

    def feed(
        self,
        origin: Mapping[str, str] | None = None,
        since: int = 0,
        limit: int = MAX_FEED,
    ) -> list[dict[str, object]]:
        """Read the changes after `since` to the scope's artifacts whose origin holds every pair of `origin`.

        Returns:
            At most `limit` changes, oldest first, then the `end` line naming the `seq` the page covers through: the
            last change's when the page is full, else the store's newest, so the next page starts past changes the
            filter left out. Each change is as the comment and thread are when read: a deleted comment's body is
            empty in every change to it.

        Raises:
            Refused: `invalid` for a limit outside 1 to `MAX_FEED`, or a negative `since`.
        """
        if not 1 <= limit <= MAX_FEED or since < 0:
            raise Refused(Code.INVALID, f"since is a seq from 0, and limit from 1 to {MAX_FEED}")
        with self._transaction(write=False):
            newest = int(self._conn.execute("SELECT coalesce(max(seq), 0) FROM changes").fetchone()[0])
            rows = self._conn.execute(
                "SELECT ch.seq, ch.kind, ch.at, ch.via AS change_via, a.id AS artifact_id, a.origin,"
                " t.id AS thread_id, t.exact, t.prefix, t.suffix, t.anchored_version, t.state,"
                " c.id AS comment_id, c.body, c.created_at, c.edited_at, c.deleted_at,"
                " w.id AS author_id, w.display_name, w.kind AS author_kind, w.on_behalf_of"
                " FROM changes ch JOIN threads t ON t.id = ch.thread_id JOIN artifacts a ON a.id = t.artifact_id"
                " JOIN authors w ON w.id = ch.author_id LEFT JOIN comments c ON c.id = ch.comment_id"
                " WHERE ch.seq > :since AND ch.seq <= :newest AND a.namespace = :namespace"
                " AND (SELECT count(*) FROM json_each(a.origin) o JOIN json_each(:filter) f"
                " ON o.key = f.key AND o.value = f.value) = (SELECT count(*) FROM json_each(:filter))"
                " ORDER BY ch.seq LIMIT :limit",
                {
                    "since": since,
                    "newest": newest,
                    "namespace": self.scope.namespace,
                    "filter": json.dumps(dict(origin or {})),
                    "limit": limit,
                },
            ).fetchall()
        through = int(rows[-1]["seq"]) if len(rows) == limit else max(newest, since)
        return [*(_change_json(row) for row in rows), {"kind": "end", "through": through}]

    def reply(self, thread_id: str, body: str) -> dict[str, object]:
        """Reply in a thread, open or resolved.

        Returns:
            The comment's id and its `seq`.

        Raises:
            Refused: `read_only`; `invalid` or `too_long` for the body; `not_found` or `out_of_scope` for the thread.
        """
        self._writable()
        _check_body(body)
        with self._transaction(write=True):
            self._thread(thread_id)
            comment_id, seq = self._comment(thread_id, body)
        return {"comment_id": comment_id, "seq": seq}

    def comment(self, artifact_id: str, anchor: Anchor | None, body: str) -> dict[str, object]:
        """Open a thread on a passage of an artifact's latest version, or with no anchor on the whole artifact.

        Returns:
            The thread's id, its first comment's, and that comment's `seq`.

        Raises:
            Refused: `read_only`; `invalid` or `too_long` for the body or the anchor; `not_found` or `out_of_scope`
                for the artifact; `anchor_not_found` when the anchor's words are not in its latest version.
        """
        self._writable()
        _check_body(body)
        if anchor is not None:
            _check_anchor(anchor)
        with self._transaction(write=True):
            artifact = self._artifact(artifact_id)
            latest = self._version(artifact, None)
            if anchor is not None and locate(str(latest["text"]), anchor) is None:
                raise Refused(Code.ANCHOR_NOT_FOUND, f"the passage is not in version {latest['n']} of {artifact_id}")
            thread_id = _id("t")
            self._conn.execute(
                "INSERT INTO threads (id, artifact_id, exact, prefix, suffix, anchored_version, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'open', ?)",
                (
                    thread_id,
                    artifact_id,
                    None if anchor is None else anchor.exact,
                    None if anchor is None else anchor.prefix,
                    None if anchor is None else anchor.suffix,
                    latest["n"],
                    _now(),
                ),
            )
            comment_id, seq = self._comment(thread_id, body)
        return {"thread_id": thread_id, "comment_id": comment_id, "seq": seq}

    def resolve(self, thread_id: str, *, resolved: bool) -> dict[str, object]:
        """Resolve a thread, or reopen it. A thread already so is left as it is, and takes no `seq`.

        Returns:
            Its state.

        Raises:
            Refused: `read_only`; `not_found` or `out_of_scope` for the thread.
        """
        self._writable()
        state = "resolved" if resolved else "open"
        with self._transaction(write=True):
            if self._thread(thread_id)["state"] != state:
                self._conn.execute("UPDATE threads SET state = ? WHERE id = ?", (state, thread_id))
                self._change("thread_resolved" if resolved else "thread_reopened", thread_id, None)
        return {"state": state}

    @contextlib.contextmanager
    def _transaction(self, *, write: bool) -> Iterator[None]:
        """Read in one snapshot, or write at once: a write takes SQLite's lock first, so `seq` is in commit order.

        Yields:
            Inside the transaction, which commits when the block ends and rolls back when it raises.
        """
        self._conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _writable(self) -> None:
        if self.scope.read_only:
            raise Refused(Code.READ_ONLY, "this store is served read-only")

    def _artifact(self, artifact_id: str) -> sqlite3.Row:
        """Find an artifact in the scope's namespace.

        Returns:
            Its row.

        Raises:
            Refused: `not_found` for no such artifact, `out_of_scope` for one in another namespace.
        """
        row: sqlite3.Row | None = self._conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise Refused(Code.NOT_FOUND, f"no artifact {artifact_id!r}")
        if row["namespace"] != self.scope.namespace:
            raise Refused(Code.OUT_OF_SCOPE, f"{artifact_id} is outside the namespace {self.scope.namespace!r}")
        return row

    def _version(self, artifact: sqlite3.Row, n: int | None) -> sqlite3.Row:
        """Find a version of `artifact`, its latest when `n` is None.

        Returns:
            Its row.

        Raises:
            Refused: `not_found` for a version it does not have.
        """
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM versions WHERE artifact_id = ? AND n = ?",
            (artifact["id"], artifact["latest_version"] if n is None else n),
        ).fetchone()
        if row is None:
            raise Refused(Code.NOT_FOUND, f"{artifact['id']} has no version {n}")
        return row

    def _thread(self, thread_id: str) -> sqlite3.Row:
        """Find a thread on an artifact in the scope's namespace.

        Returns:
            Its row.

        Raises:
            Refused: `not_found` for no such thread, `out_of_scope` for one on another namespace's artifact.
        """
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT t.*, a.namespace FROM threads t JOIN artifacts a ON a.id = t.artifact_id WHERE t.id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            raise Refused(Code.NOT_FOUND, f"no thread {thread_id!r}")
        if row["namespace"] != self.scope.namespace:
            raise Refused(Code.OUT_OF_SCOPE, f"{thread_id} is outside the namespace {self.scope.namespace!r}")
        return row

    def _comment(self, thread_id: str, body: str) -> tuple[str, int]:
        """Write the scope's author's comment in a thread, and its change, inside a write.

        Returns:
            The comment's id and its `seq`.
        """
        comment_id = _id("c")
        self._conn.execute(
            "INSERT INTO comments (id, thread_id, seq, author_id, body, created_at, via) VALUES (?, ?, 0, ?, ?, ?, ?)",
            (comment_id, thread_id, self._author(), body, _now(), VIA),
        )
        seq = self._change("comment_created", thread_id, comment_id)
        self._conn.execute("UPDATE comments SET seq = ? WHERE id = ?", (seq, comment_id))
        return comment_id, seq

    def _change(self, kind: str, thread_id: str, comment_id: str | None) -> int:
        """Record a change by the scope's author, inside a write.

        Returns:
            Its `seq`.
        """
        # `seq` is the row's id, so the cursor's lastrowid is it.
        written = self._conn.execute(
            "INSERT INTO changes (kind, thread_id, comment_id, author_id, via, at) VALUES (?, ?, ?, ?, ?, ?)",
            (kind, thread_id, comment_id, self._author(), VIA, _now()),
        )
        assert written.lastrowid is not None  # noqa: S101  (an insert into a rowid table always has one)
        return written.lastrowid

    def _author(self) -> str:
        """Record the scope's author as it is now, inside a write.

        Returns:
            Its id.
        """
        author = self.scope.author
        self._conn.execute(
            "INSERT INTO authors (id, display_name, kind, on_behalf_of) VALUES (?, ?, ?, ?) ON CONFLICT (id) DO UPDATE"
            " SET display_name = excluded.display_name, kind = excluded.kind, on_behalf_of = excluded.on_behalf_of",
            (author.id, author.display_name, author.kind, author.on_behalf_of),
        )
        return author.id


def url(artifact_id: str, version: int) -> str:
    """Name a version of an artifact. The local store serves no page yet, so this names it, and opens nothing.

    Returns:
        `canopy-artifacts:ID/N`.
    """
    return f"canopy-artifacts:{artifact_id}/{version}"


def _private_dir(directory: Path) -> None:
    """Make `directory` the operator's alone if it is not there, and check it is (D053).

    Raises:
        StoreError: It is a symlink, not a directory, another's, or open to others.
    """
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = directory.lstat()
    except OSError as e:
        raise StoreError(f"cannot make the store's directory {directory}: {e.strerror}") from e
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise StoreError(f"the store's directory {directory} is not a directory")
    if st.st_uid != os.getuid():
        raise StoreError(f"the store's directory {directory} belongs to someone else; it must be yours")
    if st.st_mode & 0o077:
        raise StoreError(f"the store's directory {directory} is open to others; run: chmod 700 {directory}")


def _migrate(conn: sqlite3.Connection) -> None:
    """Take the database to the newest schema, one step at a time, each in a write of its own."""
    for step, statements in enumerate(_SCHEMA):
        conn.execute("BEGIN IMMEDIATE")
        try:
            if int(conn.execute("PRAGMA user_version").fetchone()[0]) == step:
                for statement in statements:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {step + 1}")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def _bounded(what: str, value: str, most: int) -> None:
    if len(value) > most:
        raise Refused(Code.TOO_LONG, f"the {what} is {len(value)} characters; at most {most}")


def _check_body(body: str) -> None:
    if not body.strip():
        raise Refused(Code.INVALID, "a comment's body must not be blank")
    _bounded("body", body, MAX_BODY)


def _check_anchor(anchor: Anchor) -> None:
    if not anchor.exact:
        raise Refused(Code.INVALID, "an anchor's exact must hold words")
    _bounded("anchor's exact", anchor.exact, MAX_EXACT)
    _bounded("anchor's prefix", anchor.prefix, CONTEXT)
    _bounded("anchor's suffix", anchor.suffix, CONTEXT)


def _origin(pairs: Mapping[str, str]) -> dict[str, str]:
    """Check an artifact's origin against its bounds.

    Returns:
        The pairs.

    Raises:
        Refused: `too_long` for more than `MAX_ORIGIN` pairs, or a key or value over its bound; `invalid` for an
            empty key.
    """
    if len(pairs) > MAX_ORIGIN:
        raise Refused(Code.TOO_LONG, f"the origin has {len(pairs)} pairs; at most {MAX_ORIGIN}")
    for key, value in pairs.items():
        if not key:
            raise Refused(Code.INVALID, "an origin's key must not be empty")
        _bounded("origin key", key, MAX_ORIGIN_KEY)
        _bounded(f"origin value of {key!r}", value, MAX_ORIGIN_VALUE)
    return dict(pairs)


def _anchor(thread: sqlite3.Row) -> Anchor | None:
    exact = thread["exact"]
    return None if exact is None else Anchor(str(exact), str(thread["prefix"]), str(thread["suffix"]))


def _anchor_json(row: sqlite3.Row) -> dict[str, str] | None:
    anchor = _anchor(row)
    return None if anchor is None else {"exact": anchor.exact, "prefix": anchor.prefix, "suffix": anchor.suffix}


def _artifact_json(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "title": row["title"],
        "namespace": row["namespace"],
        "origin": json.loads(row["origin"]),
        "latest_version": row["latest_version"],
        "created_at": row["created_at"],
    }


def _version_json(row: sqlite3.Row) -> dict[str, object]:
    return {
        "artifact_id": row["artifact_id"],
        "n": row["n"],
        "content_type": row["content_type"],
        "sha256": row["sha256"],
        "created_at": row["created_at"],
    }


def _thread_json(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "artifact_id": row["artifact_id"],
        "anchor": _anchor_json(row),
        "anchored_version": row["anchored_version"],
        "state": row["state"],
    }


def _author_json(author_id: object, row: sqlite3.Row, kind: str = "kind") -> dict[str, object]:
    return {
        "id": author_id,
        "display_name": row["display_name"],
        "kind": row[kind],
        "on_behalf_of": row["on_behalf_of"],
    }


def _comment_json(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "seq": row["seq"],
        "author": _author_json(row["author_id"], row),
        "body": row["body"],
        "created_at": row["created_at"],
        "edited_at": row["edited_at"],
        "deleted_at": row["deleted_at"],
        "via": row["via"],
    }


def _change_json(row: sqlite3.Row) -> dict[str, object]:
    return {
        "kind": row["kind"],
        "seq": row["seq"],
        "at": row["at"],
        "artifact_id": row["artifact_id"],
        "origin": json.loads(row["origin"]),
        "thread_id": row["thread_id"],
        "anchor": _anchor_json(row),
        "anchored_version": row["anchored_version"],
        "state": row["state"],
        "comment_id": row["comment_id"],
        "author": _author_json(row["author_id"], row, "author_kind"),
        "via": row["change_via"],
        "body": row["body"],
        "created_at": row["created_at"],
        "edited_at": row["edited_at"],
        "deleted_at": row["deleted_at"],
    }


def _id(kind: str) -> str:
    return f"{kind}_{secrets.token_hex(8)}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
