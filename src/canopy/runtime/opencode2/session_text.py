"""The text of every OpenCode 2 session (ROADMAP M72), read from OpenCode 2.1.4's database for `canopy sessions`.

OpenCode 2 keeps every session in `session_v2`, with its title, directory, the session it ran for, and when it was
archived, and each of its messages in `session_message`, a row of one `type` whose `data` is the message as JSON,
as 2.1.4's schema `Session.Message.Info` shapes it (read from the build npm ships, 2026-11-10):

- `user`, `synthetic`, `system`, and `skill` hold a `text` the session was sent: a prompt, or a message OpenCode or a
  skill put in.
- `assistant` holds its `content`, an array of parts: `text` and `reasoning`, each a `text`, and `tool`, whose `state`
  holds the call's `input`, an object, and, once it ended, its `content`, an array of `{type: "text", text}` and
  `{type: "file", ...}`, or its `error`, `{type, message}`.
- `shell` holds a `command` the operator ran, and its `output`, `{output, cursor, size, truncated}`.
- `compaction` holds the `summary` that took the place of what the session said before.
- `agent-switched`, `model-switched`, `location-switched`, and `idle` hold no text.

Each database is read as `canopy.runtime.opencode.sessions` reads it for spend, the operator's and each sandbox role's,
opened read-only as one a run may have written to harm its reader (`opened`): SQLite takes each part out of the JSON,
and each row it gives is validated (D026), so a row canopy cannot read is passed over and counted. The tables OpenCode
1 left beside OpenCode 2's are counted, never read: whatever sessions only they hold.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from typing import TYPE_CHECKING, cast

from canopy.runtime.opencode import sessions
from canopy.runtime.report import (
    MAX_DIRECTORY,
    TEXT_PARTS,
    KeptSession,
    SessionRecord,
    TextPart,
    TextRow,
    session_id,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Generator, Sequence
    from pathlib import Path

#: How long a read of a database's whole text may take, in seconds: a measurement the operator runs by hand, over every
#: session, which may be long; a database a run wrote to answer never is still stopped.
READ_SECONDS = 3600.0
#: How many sessions one database's count reads at most: far more than any record holds, so one a run wrote cannot
#: fill memory.
MAX_KEPT = 1_000_000
#: Which of OpenCode's session tables a database has: OpenCode 2's, `session_v2`, and OpenCode 1's, `session`.
TABLES_SQL = "SELECT name FROM sqlite_schema WHERE type = 'table' AND name IN ('session', 'session_v2')"
#: Every session, as `KeptSession` reads it, in the order of its id.
SESSIONS_SQL = """
SELECT id, parent_id, directory, time_archived FROM session_v2 ORDER BY id LIMIT ?
"""
#: How many sessions only OpenCode 1's table holds.
EARLIER_SQL = """
SELECT count(*) FROM session WHERE id NOT IN (SELECT id FROM session_v2)
"""
#: How many sessions OpenCode 1's table holds, in a database that has no table of OpenCode 2's.
EARLIER_ALL_SQL = "SELECT count(*) FROM session"
#: Each part of every session's text, as `TextRow` reads it: its session, which part, and the text, none empty, among
#: the parts a JSON array names, `?2`, that holds every pattern of `LIKE` another names, `?1`: every part, read whole,
#: when the first names none, and a plain scan of the record in place, with no index, when it names some. A message
#: whose data is not JSON is read as an empty object, so SQLite takes nothing out of it and raises nothing.
PARTS_SQL = """
WITH message AS (
    SELECT session_id, type, CASE WHEN json_valid(data) THEN data ELSE '{}' END AS data FROM session_message
),
content AS (
    SELECT m.session_id, m.data, c.fullkey AS at, json_extract(m.data, c.fullkey || '.type') AS kind
    FROM message m, json_each(m.data, '$.content') c
    WHERE m.type = 'assistant'
),
parts (session_id, part, text) AS (
    SELECT id, 'title', title FROM session_v2
    UNION ALL
    SELECT session_id, 'sent', json_extract(data, '$.text') FROM message
    WHERE type IN ('user', 'synthetic', 'system', 'skill')
    UNION ALL
    SELECT session_id, 'summary', json_extract(data, '$.summary') FROM message WHERE type = 'compaction'
    UNION ALL
    SELECT session_id, 'given', json_extract(data, '$.command') FROM message WHERE type = 'shell'
    UNION ALL
    SELECT session_id, 'returned', json_extract(data, '$.output.output') FROM message WHERE type = 'shell'
    UNION ALL
    SELECT session_id, CASE kind WHEN 'text' THEN 'wrote' ELSE 'reasoning' END, json_extract(data, at || '.text')
    FROM content WHERE kind IN ('text', 'reasoning')
    UNION ALL
    SELECT session_id, 'given',
        (SELECT group_concat(t.value, char(10)) FROM json_tree(data, at || '.state.input') t WHERE t.type = 'text')
    FROM content WHERE kind = 'tool'
    UNION ALL
    SELECT session_id, 'returned',
        (SELECT group_concat(json_extract(data, x.fullkey || '.text'), char(10))
         FROM json_each(data, at || '.state.content') x WHERE json_extract(data, x.fullkey || '.type') = 'text')
    FROM content WHERE kind = 'tool'
    UNION ALL
    SELECT session_id, 'returned', json_extract(data, at || '.state.error.message') FROM content WHERE kind = 'tool'
)
SELECT session_id, part, text FROM parts
WHERE text IS NOT NULL AND text != '' AND part IN (SELECT value FROM json_each(?2))
  AND NOT EXISTS (SELECT 1 FROM json_each(?1) w WHERE text NOT LIKE w.value ESCAPE '\\')
"""
#: What `PARTS_SQL` takes to read every part whole: no pattern, and every part.
EVERY_PART = ("[]", json.dumps(TEXT_PARTS))


def record() -> SessionRecord:
    """Read every session OpenCode 2 keeps, in the operator's database and each sandbox role's, and what they are.

    Returns:
        The sessions; `missing` when OpenCode has no database yet; `failed`, with why, when the operator's could not
        be read.
    """
    found: list[KeptSession] = []
    earlier = skipped = passed_over = databases = size = 0
    for n, path in enumerate(sessions.databases()):
        if not path.is_file():
            continue
        try:
            with sessions.opened(path) as conn:
                tables = {str(row[0]) for row in sessions.query(conn, TABLES_SQL)}
                rows = sessions.query(conn, SESSIONS_SQL, MAX_KEPT) if "session_v2" in tables else []
                earlier += _earlier(conn, tables)
        except sqlite3.Error as e:
            if n == 0:
                return SessionRecord("failed", error=f"OpenCode's database could not be read: {str(e)[:200]}")
            passed_over += 1
            continue
        kept = [_kept(row) for row in rows]
        found.extend(k for k in kept if k is not None)
        skipped += sum(k is None for k in kept)
        databases += 1
        size += _size(path)
    if not databases:
        return SessionRecord("missing", passed_over=passed_over)
    return SessionRecord(
        "found",
        found,
        databases=databases,
        size_bytes=size,
        earlier_only=earlier,
        skipped=skipped,
        passed_over=passed_over,
    )


def rows() -> Generator[TextRow | None]:
    """Read every part of every session's text, from the operator's database and each sandbox role's, one at a time.

    A sandbox role's database canopy cannot read is passed over, as `record` passes it over.

    Yields:
        Each part, or None for a row canopy cannot read.

    Raises:
        sqlite3.Error: the operator's database could not be read.
    """
    for n, path in enumerate(sessions.databases()):
        if not path.is_file():
            continue
        try:
            with sessions.opened(path, seconds=READ_SECONDS) as conn:
                if "session_v2" not in {row[0] for row in sessions.query(conn, TABLES_SQL)}:
                    continue
                for row in sessions.each(conn, PARTS_SQL, *EVERY_PART):
                    yield _row(row)
        except sqlite3.Error:
            if n == 0:
                raise
            continue


def scan(words: Sequence[str], parts: Collection[TextPart]) -> list[tuple[str, TextPart]]:
    """Find the parts among `parts` that hold every one of `words`, by a plain scan of every database, with no index.

    A word is found anywhere in a part, its case aside for ASCII letters, as `LIKE` finds it.

    Returns:
        Each session and part found, once each.

    Raises:
        sqlite3.Error: the operator's database could not be read.
    """
    patterns = json.dumps([f"%{_escaped(w)}%" for w in words])
    named = json.dumps(list(parts))
    found: set[tuple[str, TextPart]] = set()
    for n, path in enumerate(sessions.databases()):
        if not path.is_file():
            continue
        try:
            with sessions.opened(path, seconds=READ_SECONDS) as conn:
                if "session_v2" not in {row[0] for row in sessions.query(conn, TABLES_SQL)}:
                    continue
                found.update(h for row in sessions.each(conn, PARTS_SQL, patterns, named) if (h := _hit(row)))
        except sqlite3.Error:
            if n == 0:
                raise
            continue
    return sorted(found)


# How many sessions only OpenCode 1's table holds, in a database whose tables are `tables`.
def _earlier(conn: sqlite3.Connection, tables: Collection[str]) -> int:
    if "session" not in tables:
        return 0
    counted = sessions.query(conn, EARLIER_SQL if "session_v2" in tables else EARLIER_ALL_SQL)[0][0]
    return counted if isinstance(counted, int) else 0


# The row as a session, or None when canopy cannot read it.
def _kept(row: Sequence[object]) -> KeptSession | None:
    found, parent, directory, archived = row
    named = session_id(found)
    if named is None or not isinstance(directory, str) or not (archived is None or isinstance(archived, int)):
        return None
    if parent is not None and session_id(parent) is None:
        return None
    return KeptSession(
        session_id=named,
        parent_id=cast("str | None", parent),
        directory="".join(c for c in directory if c.isprintable())[:MAX_DIRECTORY],
        archived=archived is not None,
    )


# The row as a part of a session's text, or None when canopy cannot read it.
def _row(row: Sequence[object]) -> TextRow | None:
    found, part, text = row
    named = session_id(found)
    if named is None or part not in TEXT_PARTS or not isinstance(text, str):
        return None
    return TextRow(session_id=named, part=cast("TextPart", part), text=text)


# The row as a session and a part found, or None when canopy cannot read it.
def _hit(row: Sequence[object]) -> tuple[str, TextPart] | None:
    found = _row(row)
    return (found.session_id, found.part) if found is not None else None


# What a database takes on disk: its file and the log of writes not yet folded into it.
def _size(path: Path) -> int:
    size = 0
    for each in (path, path.with_name(f"{path.name}-wal")):
        with contextlib.suppress(OSError):
            size += each.stat().st_size
    return size


# The word as `LIKE` finds it literally: its wildcards, and the escape, escaped.
def _escaped(word: str) -> str:
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
