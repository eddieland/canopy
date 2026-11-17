"""Sessions found by what they said, did, and read (ROADMAP M72, stage 2): the index searched, and each hit's snippet.

A search reads the index the loop keeps (`canopy.core.session_index`), read-only. A session is found when its title and
one of its messages hold every word between them, each matched as a word, its English endings aside, as memory's search
matches (DESIGN §28), never as the index's query syntax, so no query is an error: a message's row holds the session's
title beside its text, and is found only when its text holds one of the words, so a title that holds them all does not
find every message of its session; the title's own row finds a session by its title alone. A session of canopy's is
never found by what it was sent, whatever the index holds of it. Hits are ranked by how well they match, a word in a
title weighing more, then newest first (`found`).

A hit's snippet is read from the runtime's record when the search is made, for the hits shown alone (`hit`): the
message whose row matched best, read again, on one line, nothing hidden in it, bounded, the query's words marked. The
record is what runs write, so the snippet is data (TRUST_MODEL T1), rendered as text.
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import session_index, sql
from canopy.runtime import indexed_text

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from canopy.runtime.implementation import Version

#: How much a word in a session's title weighs, against 1 for one in a message: a title names what a session is about.
TITLE_WEIGHT = 4.0
#: How many sessions a search finds at most, and how many rows of the index it reads for them.
MAX_FOUND = 1000
MAX_ROWS = 20_000
#: How many words a snippet holds around the words found, and how many characters at most.
SNIPPET_WORDS = 24
MAX_SNIPPET = 400
# What `snippet()` marks a word found with: characters a snippet's text never holds, since every one that is not
# printable is dropped first.
_START, _END = "\x01", "\x02"
# A message's row, found when its title and text hold every word between them and its text holds one.
_MESSAGE_MATCH = "{cols} : ({every}) AND {text} : ({any})"


@dataclass(frozen=True)
class Mark:
    """A piece of a snippet: its text, and whether it is one of the words searched for."""

    text: str
    marked: bool = False


@dataclass(frozen=True)
class Found:
    """A session the index found, as a search ranks it."""

    session_id: str
    #: Which of the runtime's records keeps it, as the index read it.
    record: str
    #: The message whose row matched best; None when its title did.
    message_id: str | None
    #: How many more of its messages hold the words.
    more: int
    #: Whether it was indexed in part, past a bound.
    cut: bool


@dataclass(frozen=True)
class Hit:
    """What a list shows of a session found by its words, beside its title."""

    #: The best message's words around those found, marked; None when its title held them, or the runtime's record no
    #: longer keeps the message.
    snippet: Sequence[Mark] | None
    #: How many more of its messages hold the words.
    more: int
    #: Whether it was indexed in part, past a bound: words past it are not found.
    cut: bool


def found(state_dir: Path, words: Sequence[str], *, canopy: bool, limit: int = MAX_FOUND) -> list[Found]:
    """Find the sessions whose title and one message hold every one of `words` between them, best first.

    `canopy` finds canopy's sessions, never by what they were sent; else the sessions outside canopy, by any part.
    `words` are a query's, as memory's search reads them; with none, nothing is found.

    Returns:
        At most `limit` sessions, ranked by how well they match, a word in a title weighing more, then newest first;
        none when there is no index.
    """
    if not words:
        return []
    every = " AND ".join(f'"{w}"' for w in words)
    either = " OR ".join(f'"{w}"' for w in words)
    cols, text = ("{title body}", "{body}") if canopy else ("{title sent body}", "{sent body}")
    try:
        with session_index.read_only(state_dir) as idx:
            messages = _rows(idx, _MESSAGE_MATCH.format(cols=cols, every=every, text=text, any=either), title=False)
            titles = _rows(idx, f"{{title}} : ({every})", title=True)
    except sqlite3.Error:
        return []
    best: dict[str, _Row] = {}
    counts: dict[str, int] = {}
    for row in [*titles, *messages]:
        if row.message_id is not None:
            counts[row.session_id] = counts.get(row.session_id, 0) + 1
        if row.session_id not in best or row.rank < best[row.session_id].rank:
            best[row.session_id] = row
    ranked = sorted(best.values(), key=lambda r: (r.rank, -r.updated_ms, r.session_id))
    return [
        Found(
            session_id=r.session_id,
            record=r.record,
            message_id=r.message_id,
            more=counts.get(r.session_id, 0) - (r.message_id is not None),
            cut=r.cut,
        )
        for r in ranked[:limit]
    ]


def hit(found: Found, words: Sequence[str], *, canopy: bool, version: Version) -> Hit:
    """What a list shows of session `found`: its best message read again from the runtime's record, `words` marked.

    Of one of canopy's, what it was sent is left out of the snippet, as the search leaves it out.

    Returns:
        Its snippet, how many more messages hold the words, and whether it was cut.
    """
    snippet: list[Mark] | None = None
    if found.message_id is not None:
        parts = indexed_text.message(
            found.record,
            found.session_id,
            found.message_id,
            max_chars=session_index.MAX_MESSAGE_CHARS,
            version=version,
        )
        if parts is not None:
            snippet = _snippet("\n".join(p.text for p in parts if not (canopy and p.part == "sent")), words)
    return Hit(snippet=snippet, more=found.more, cut=found.cut)


def marked_text(snippet: Sequence[Mark], *, mark: str = "*") -> str:
    """A snippet as one line of text, each word found between two `mark`s.

    Returns:
        The line.
    """
    return "".join(f"{mark}{m.text}{mark}" if m.marked else m.text for m in snippet)


@dataclass(frozen=True)
class _Row:
    """A row of the index a search matched: its session, its message, how well it matched, and its session's facts."""

    session_id: str
    message_id: str | None
    rank: float
    record: str
    updated_ms: int
    cut: bool


# The rows `match` finds, best first, at most `MAX_ROWS`: the title's rows, or the messages'.
def _rows(idx: sqlite3.Connection, match: str, *, title: bool) -> list[_Row]:
    query = (
        sql.select("m.session_id, m.message_id, h.rank, s.record, s.updated_ms, s.cut")
        # bm25() runs only in the query of the index itself, so its rows are read first, and joined after.
        .with_(
            "h AS MATERIALIZED (SELECT rowid AS row, bm25(words, ?, 1.0, 1.0) AS rank FROM words WHERE words MATCH ?"
            " ORDER BY rank LIMIT ?)",
            TITLE_WEIGHT,
            match,
            MAX_ROWS,
        )
        .from_("h")
        .join("messages m ON m.row = h.row")
        .join("sessions s ON s.session_id = m.session_id")
        .where("(m.message_id IS NULL) = ?", title)
    )
    return [
        _Row(
            str(session_id),
            None if message_id is None else str(message_id),
            float(rank),
            str(record),
            int(at),
            bool(c),
        )
        for session_id, message_id, rank, record, at, c in sql.execute(idx, query)
    ]


# The words of `text` around those of `words` found in it, as SQLite's `snippet()` picks them, each found marked: on one
# line, every character that is not printable dropped, at most `MAX_SNIPPET` characters.
def _snippet(text: str, words: Sequence[str]) -> list[Mark]:
    flat = "".join(c for c in " ".join(text.split()) if c.isprintable())
    if not flat:
        return []
    picked = flat[:MAX_SNIPPET]
    with contextlib.closing(sqlite3.connect(":memory:")) as conn:
        sql.execute(conn, sql.frag("CREATE VIRTUAL TABLE t USING fts5(body, tokenize='porter unicode61')"))
        sql.execute(conn, sql.frag("INSERT INTO t (body) VALUES (?)", flat))
        row = sql.execute(
            conn,
            sql.select("snippet(t, 0, ?, ?, '…', ?)", _START, _END, SNIPPET_WORDS)
            .from_("t")
            .where("t MATCH ?", " OR ".join(f'"{w}"' for w in words)),
        ).fetchone()
    if row is not None:
        picked = str(row[0])
    return _marks(picked)


# A snippet `snippet()` marked, as its pieces, at most `MAX_SNIPPET` characters of text.
def _marks(picked: str) -> list[Mark]:
    marks: list[Mark] = []
    left = MAX_SNIPPET
    for n, piece in enumerate(picked.replace(_END, _START).split(_START)):
        if piece and left > 0:
            marks.append(Mark(piece[:left], marked=n % 2 == 1))
            left -= len(piece)
    return marks
