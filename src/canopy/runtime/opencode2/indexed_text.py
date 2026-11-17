"""What an index of every OpenCode 2 session's text reads (ROADMAP M72, stage 2), from OpenCode 2.1.4's database.

A session is read in two steps: its row in `session_v2`, a page at a time in the order of its update, after a cursor
or, newest first, before one (`heads`), and then its messages in `session_message`, each part of each message as
`canopy.runtime.opencode2.session_text` takes them apart, with the message's id (`texts`). A snippet reads one message
again (`message`), and the index drops what the record no longer keeps by every session's id (`kept`).

Each database is opened read-only as the spend's read opens it (`canopy.runtime.opencode.sessions.opened`): the
operator's, and each sandbox role's, whose sessions are merged with the operator's in the order of their update. A
role's canopy cannot read is passed over whole, so a run can keep only its own role's sessions from being read. Each
row is validated (D026): a session canopy cannot read is passed over, its place kept so the cursor passes it, and a
message whose data is not JSON, or a part that is not text, gives no text. A record is named by its database's path,
and only a database `databases` lists is ever opened by name.
"""

from __future__ import annotations

import operator
import sqlite3
from typing import TYPE_CHECKING, cast

from canopy.runtime.opencode import sessions
from canopy.runtime.report import (
    MAX_DIRECTORY,
    TEXT_PARTS,
    HeadPage,
    KeptIds,
    MessageText,
    SessionHead,
    SessionTexts,
    TextPart,
    session_id,
    session_title,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from canopy.runtime.report import SessionCursor

#: How long reading one session's messages may take, in seconds, before canopy stops it and reads it as cut: a run can
#: write a session no read would end.
SESSION_SECONDS = 5.0
#: How many session ids `kept` reads of one database at most: far more than any record holds.
MAX_KEPT = 1_000_000
#: Whether a database has OpenCode 2's table of sessions.
TABLE_SQL = "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'session_v2'"
#: Sessions updated after a cursor, the least recently updated first: the cursor's update, or NULL for every session,
#: its id, and how many. A row whose update or id is not of its column's type is never read: the cursor could not pass
#: it.
AFTER_SQL = """
SELECT id, parent_id, directory, title, time_updated FROM session_v2
WHERE typeof(time_updated) = 'integer' AND typeof(id) = 'text'
  AND (?1 IS NULL OR time_updated > ?1 OR (time_updated = ?1 AND id > ?2))
ORDER BY time_updated, id
LIMIT ?3
"""
#: Sessions updated before a cursor, the most recently updated first, as `AFTER_SQL` takes its values.
BEFORE_SQL = """
SELECT id, parent_id, directory, title, time_updated FROM session_v2
WHERE typeof(time_updated) = 'integer' AND typeof(id) = 'text'
  AND (?1 IS NULL OR time_updated < ?1 OR (time_updated = ?1 AND id < ?2))
ORDER BY time_updated DESC, id DESC
LIMIT ?3
"""
#: Whether the record keeps a session, by its id.
KEEPS_SQL = "SELECT 1 FROM session_v2 WHERE id = ?"
#: How many messages a session has, by its id.
COUNT_SQL = "SELECT count(*) FROM session_message WHERE session_id = ?"
#: Every session's id, at most how many.
IDS_SQL = "SELECT id FROM session_v2 WHERE typeof(id) = 'text' LIMIT ?"
#: Each part of a session's messages, by the session's id, `?1`, and, unless NULL, one message's, `?2`, of its first
#: `?3` messages in their order: the message's id, the part, as `canopy.runtime.opencode2.session_text.PARTS_SQL` names
#: them, its text cut to `?4` characters, and whether it was longer. A message whose data is not JSON is read as an
#: empty object, so SQLite takes nothing out of it and raises nothing; a part that is not text is left out.
PARTS_SQL = """
WITH message AS (
    SELECT id, seq, type, CASE WHEN json_valid(data) THEN data ELSE '{}' END AS data FROM session_message
    WHERE session_id = ?1 AND (?2 IS NULL OR id = ?2)
    ORDER BY seq, id
    LIMIT ?3
),
content AS (
    SELECT m.id, m.seq, m.data, c.key AS n, c.fullkey AS at, json_extract(m.data, c.fullkey || '.type') AS kind
    FROM message m, json_each(m.data, '$.content') c
    WHERE m.type = 'assistant'
),
parts (message_id, seq, n, part, text) AS (
    SELECT id, seq, 0, 'sent', json_extract(data, '$.text') FROM message
    WHERE type IN ('user', 'synthetic', 'system', 'skill')
    UNION ALL
    SELECT id, seq, 0, 'summary', json_extract(data, '$.summary') FROM message WHERE type = 'compaction'
    UNION ALL
    SELECT id, seq, 0, 'given', json_extract(data, '$.command') FROM message WHERE type = 'shell'
    UNION ALL
    SELECT id, seq, 1, 'returned', json_extract(data, '$.output.output') FROM message WHERE type = 'shell'
    UNION ALL
    SELECT id, seq, n, CASE kind WHEN 'text' THEN 'wrote' ELSE 'reasoning' END, json_extract(data, at || '.text')
    FROM content WHERE kind IN ('text', 'reasoning')
    UNION ALL
    SELECT id, seq, n, 'given',
        (SELECT group_concat(t.value, char(10)) FROM json_tree(data, at || '.state.input') t WHERE t.type = 'text')
    FROM content WHERE kind = 'tool'
    UNION ALL
    SELECT id, seq, n, 'returned',
        (SELECT group_concat(json_extract(data, x.fullkey || '.text'), char(10))
         FROM json_each(data, at || '.state.content') x WHERE json_extract(data, x.fullkey || '.type') = 'text')
    FROM content WHERE kind = 'tool'
    UNION ALL
    SELECT id, seq, n, 'returned', json_extract(data, at || '.state.error.message') FROM content WHERE kind = 'tool'
)
SELECT message_id, part, substr(text, 1, ?4), length(text) > ?4 FROM parts
WHERE typeof(text) = 'text' AND text != ''
ORDER BY seq, message_id, n
"""


def unindexed() -> str | None:
    """Say why OpenCode 2's text cannot be indexed: it can.

    Returns:
        None.
    """
    return None


def heads(cursor: SessionCursor | None, *, newest_first: bool, limit: int) -> HeadPage:
    """Read the sessions updated after `cursor`, or with `newest_first`, before it, from every database.

    With no cursor, from the first session, or the newest. The operator's database and each sandbox role's are read
    from the same cursor, and their sessions merged in the order of their update.

    Returns:
        At most `limit` rows, in the order read; `missing` when OpenCode has no database yet; `failed`, with why, when
        the operator's could not be read.
    """
    statement = BEFORE_SQL if newest_first else AFTER_SQL
    at, after = cursor if cursor is not None else (None, "")
    rows: list[tuple[SessionCursor, SessionHead | None]] = []
    found = False
    passed_over = 0
    for n, path in enumerate(sessions.databases()):
        if not path.is_file():
            continue
        try:
            with sessions.opened(path) as conn:
                if sessions.query(conn, TABLE_SQL):
                    rows.extend(_head(row, str(path)) for row in sessions.query(conn, statement, at, after, limit))
        except sqlite3.Error as e:
            if n == 0:
                return HeadPage("failed", error=f"OpenCode's database could not be read: {str(e)[:200]}")
            passed_over += 1
            continue
        found = True
    if not found:
        return HeadPage("missing", passed_over=passed_over)
    rows.sort(key=operator.itemgetter(0), reverse=newest_first)
    return HeadPage("found", rows[:limit], passed_over=passed_over)


def texts(head: SessionHead, *, max_messages: int, max_chars: int, max_total: int) -> SessionTexts:
    """Read the text of session `head`'s first `max_messages` messages, from the record that keeps it.

    Each part is cut to `max_chars` characters, and the read stops once `max_total` characters are read. A read that
    runs past `SESSION_SECONDS` is stopped, and what it read kept, cut.

    Returns:
        Each part, in the order of the messages; `missing` when the record no longer keeps the session; `failed` when
        the record could not be read.
    """
    path = _named(head.record)
    if path is None:
        return SessionTexts("missing")
    found: list[MessageText] = []
    total = 0
    cut = False
    try:
        with sessions.opened(path, seconds=SESSION_SECONDS) as conn:
            if not sessions.query(conn, KEEPS_SQL, head.session_id):
                return SessionTexts("missing")
            count = sessions.query(conn, COUNT_SQL, head.session_id)[0][0]
            cut = isinstance(count, int) and count > max_messages
            for row in sessions.each(conn, PARTS_SQL, head.session_id, None, max_messages, max_chars):
                part = _part(row)
                if part is None:
                    continue
                found.append(part)
                total += len(part.text)
                cut = cut or part.cut
                if total >= max_total:
                    cut = True
                    break
    except sqlite3.Error as e:
        if "interrupted" in str(e):
            # Stopped past its time: what was read is kept, and the session is cut.
            return SessionTexts("found", found, cut=True)
        return SessionTexts("failed")
    return SessionTexts("found", found, cut=cut)


def message(record: str, session: str, message_id: str, *, max_chars: int) -> list[MessageText] | None:
    """Read one message of a session again, for a snippet: each part, cut to `max_chars` characters.

    Returns:
        Its parts; None when the record no longer keeps it, or could not be read.
    """
    path = _named(record)
    if path is None:
        return None
    try:
        with sessions.opened(path, seconds=SESSION_SECONDS) as conn:
            rows = sessions.query(conn, PARTS_SQL, session, message_id, 1, max_chars)
    except sqlite3.Error:
        return None
    found = [p for row in rows if (p := _part(row)) is not None]
    return found or None


def kept() -> KeptIds:
    """Read every session's id, from the operator's database and each sandbox role's.

    Returns:
        Each database's sessions, by its name; `missing` when OpenCode has no database yet; `failed` when the
        operator's could not be read. A role's that could not be read is named among the unread.
    """
    found: dict[str, frozenset[str]] = {}
    unread: set[str] = set()
    for n, path in enumerate(sessions.databases()):
        if not path.is_file():
            continue
        try:
            with sessions.opened(path) as conn:
                ids = sessions.query(conn, IDS_SQL, MAX_KEPT) if sessions.query(conn, TABLE_SQL) else []
        except sqlite3.Error:
            if n == 0:
                return KeptIds("failed")
            unread.add(str(path))
            continue
        found[str(path)] = frozenset(i for (value,) in ids if (i := session_id(value)) is not None)
    if not found and not unread:
        return KeptIds("missing")
    return KeptIds("found", found, unread=frozenset(unread))


# The row as where it sorts and the session, or None for a session canopy cannot read.
def _head(row: Sequence[object], record: str) -> tuple[SessionCursor, SessionHead | None]:
    found, parent, directory, title, updated = row
    at = (cast("int", updated), cast("str", found))
    named = session_id(found)
    if named is None or not isinstance(directory, str) or (parent is not None and session_id(parent) is None):
        return at, None
    return at, SessionHead(
        session_id=named,
        parent_id=cast("str | None", parent),
        directory="".join(c for c in directory if c.isprintable())[:MAX_DIRECTORY],
        title=session_title(title),
        updated_ms=cast("int", updated),
        record=record,
    )


# The row as a part of a message, or None when canopy cannot read it.
def _part(row: Sequence[object]) -> MessageText | None:
    found, part, text, longer = row
    if session_id(found) is None or part not in TEXT_PARTS or not isinstance(text, str):
        return None
    return MessageText(message_id=cast("str", found), part=cast("TextPart", part), text=text, cut=bool(longer))


# The database a record names, when it is one of OpenCode's: an index's file names it, never a path to open unchecked.
def _named(record: str) -> Path | None:
    return next((p for p in sessions.databases() if str(p) == record and p.is_file()), None)
