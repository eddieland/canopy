"""The web UI's search over the journal (DESIGN §22): tickets, messages, chore runs, decisions, and ticks.

Reads only. Each source is a plain scan with `LIKE`, newest first, that stops at its limit: no index, for the reasons
§22 gives. Every text a hit carries is untrusted, cut to one line around its first match with control characters
dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from canopy.core import conversation, sql

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Collection, Iterable, Sequence

type Source = Literal["ticket", "message", "chore_run", "decision", "tick"]

MIN_QUERY = 2
MAX_QUERY = 200
MAX_WORDS = 8
# Each source's newest hits; one more is read to learn whether it has more.
PER_SOURCE = 20
SNIPPET = 160
# How much of a snippet comes before its first match, when the text is longer than a snippet.
_LEAD = 50
_CUT = "…"


class BadQueryError(ValueError):
    """A query search refuses: too short, too long, or too many words."""


@dataclass(frozen=True)
class Hit:
    """One row that holds every word: where it is, and a snippet of the field that matched."""

    source: Source
    # The journal's own time format.
    at: str
    snippet: str
    ticket_key: str | None = None
    chore: str | None = None
    # The run that reported a message, or the tick that recorded a decision or is the hit itself.
    run_id: int | None = None
    tick_id: int | None = None
    # A fixed word for the row: a message's kind, a decision's action, a run's or tick's status, a ticket's phase.
    label: str | None = None


@dataclass(frozen=True)
class Found:
    """A search's words, its hits in source order and newest first within each, and the sources that had more."""

    words: tuple[str, ...]
    hits: Sequence[Hit]
    more: Sequence[Source]


def words(query: str) -> tuple[str, ...]:
    """The query's distinct words, in order, with control characters dropped.

    Returns:
        The words, whitespace collapsed, each once in the order it first appears.

    Raises:
        BadQueryError: The query is shorter than `MIN_QUERY` or longer than `MAX_QUERY` characters, or has more than
            `MAX_WORDS` words.
    """
    text = " ".join(conversation.printable(query).split())
    if not MIN_QUERY <= len(text) <= MAX_QUERY:
        raise BadQueryError(f"a search is {MIN_QUERY} to {MAX_QUERY} characters")
    found = tuple(dict.fromkeys(text.split()))
    if len(found) > MAX_WORDS:
        raise BadQueryError(f"a search is at most {MAX_WORDS} words")
    return found


def search(conn: sqlite3.Connection, query: str) -> Found:
    """Every source's newest rows holding each of the query's words in one field. Raises BadQueryError.

    Returns:
        The words, at most `PER_SOURCE` hits from each source, newest first, and the sources that had more.
    """
    terms = words(query)
    hits: list[Hit] = []
    more: list[Source] = []
    for source, rows_of, hit in _SOURCES:
        rows = _matching(conn, rows_of, terms)
        if len(rows) > PER_SOURCE:
            more.append(source)
        hits.extend(hit(row, snippet(str(row["text"]), terms)) for row in rows[:PER_SOURCE])
    return Found(words=terms, hits=hits, more=more)


def snippet(text: str, terms: Iterable[str]) -> str:
    """`text` on one line, cut to SNIPPET characters around the first match of any of `terms`.

    Returns:
        The text, whitespace collapsed and control characters dropped, with "…" where it was cut at either end.
    """
    line = " ".join(conversation.printable(text).split())
    if len(line) <= SNIPPET:
        return line
    match = re.search("|".join(re.escape(t) for t in terms), line, re.IGNORECASE)
    start = max(0, (match.start() if match else 0) - _LEAD)
    end = min(len(line), start + SNIPPET)
    start = max(0, end - SNIPPET)
    head = _CUT if start > 0 else ""
    tail = _CUT if end < len(line) else ""
    return head + line[start + len(head) : end - len(tail)] + tail


def like(term: str) -> str:
    """A `LIKE` pattern matching `term` anywhere, its wildcards and the escape character taken literally.

    Returns:
        `term` with each `%`, `_`, and backslash escaped by a backslash, between two `%`.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _matching(conn: sqlite3.Connection, rows_of: sql.Select, terms: Collection[str]) -> list[sqlite3.Row]:
    # Each source's query is a subquery with a `text` column and an `id` that orders it newest first. SQLite flattens
    # it, so the scan walks the table by id and stops once the limit is met. The SQL is fixed; the terms are bound.
    query = sql.select("*").from_("({})", rows_of)
    for term in terms:
        query = query.where("text LIKE ? ESCAPE '\\'", like(term))
    return sql.execute(conn, query.order_by("id DESC").limit(PER_SOURCE + 1)).fetchall()


# A ticket's text: its key and title, then its branch and each unit's branch and PR, each once. Ordered by when a tick
# last saw it, since a ticket's rowid says only when it was first seen.
_TICKETS = sql.select(
    "t.key, t.phase, t.last_seen_at AS at,"
    "  t.key || coalesce(' ' || t.title, '') || coalesce(' ' || (SELECT group_concat(v, ' ') FROM ("
    "    SELECT t.branch AS v UNION SELECT u.branch FROM ticket_units u WHERE u.ticket_key = t.key"
    "    UNION SELECT u.pr_url FROM ticket_units u WHERE u.ticket_key = t.key"
    "  ) WHERE v IS NOT NULL AND v != ''), '') AS text,"
    "  t.last_seen_at AS id",
).from_("tickets t")
# A ticket's or a chore's; a task's conversation is not searched until tasks are in the web UI (DESIGN §36), and its
# subject is no ticket.
_MESSAGES = (
    sql.select("id, subject_kind, subject_id, at, kind, run_id, body AS text")
    .from_("messages")
    .where("subject_kind IN ('ticket', 'chore')")
)
# A chore run's text: the harness's note, its summary, and each finding's title and detail. Only a run whose result
# is valid JSON has one, and only an object is a finding: the JSON functions fail on anything else.
_CHORE_RUNS = (
    sql.select(
        "id, chore, status, coalesce(ended_at, started_at) AS at,"
        "  coalesce(json_extract(result_json, '$.harness'), '') || char(10)"
        "  || coalesce(json_extract(result_json, '$.summary'), '') || char(10)"
        "  || coalesce((SELECT group_concat("
        "    coalesce(json_extract(f.value, '$.title'), '') || ': ' || coalesce(json_extract(f.value, '$.detail'), ''),"
        "    char(10)) FROM json_each(result_json, '$.findings') AS f WHERE f.type = 'object'), '') AS text",
    )
    .from_("chore_runs")
    .where("json_valid(result_json)")
)
_DECISIONS = sql.select("id, tick_id, ticket_key, chore, action, created_at AS at, rationale AS text").from_(
    "decisions",
)
_TICKS = (
    sql.select("id, status, coalesce(ended_at, started_at) AS at, summary AS text")
    .from_("ticks")
    .where("summary IS NOT NULL")
)


def _ticket(row: sqlite3.Row, text: str) -> Hit:
    phase = row["phase"]
    return Hit("ticket", str(row["at"]), text, ticket_key=str(row["key"]), label=str(phase) if phase else None)


def _message(row: sqlite3.Row, text: str) -> Hit:
    subject = str(row["subject_id"])
    chore = row["subject_kind"] == conversation.CHORE
    run = row["run_id"]
    return Hit(
        "message",
        str(row["at"]),
        text,
        ticket_key=None if chore else subject,
        chore=subject if chore else None,
        run_id=int(run) if run is not None else None,
        # A note to a chore is the operator's reply on its subject (§19).
        label="note" if chore else str(row["kind"]),
    )


def _chore_run(row: sqlite3.Row, text: str) -> Hit:
    return Hit(
        "chore_run",
        str(row["at"]),
        text,
        chore=str(row["chore"]),
        run_id=int(row["id"]),
        label=str(row["status"]),
    )


def _decision(row: sqlite3.Row, text: str) -> Hit:
    key, chore = row["ticket_key"], row["chore"]
    return Hit(
        "decision",
        str(row["at"]),
        text,
        ticket_key=str(key) if key is not None else None,
        chore=str(chore) if chore is not None else None,
        tick_id=int(row["tick_id"]),
        label=str(row["action"]),
    )


def _tick(row: sqlite3.Row, text: str) -> Hit:
    return Hit("tick", str(row["at"]), text, tick_id=int(row["id"]), label=str(row["status"]))


_SOURCES: tuple[tuple[Source, sql.Select, Callable[[sqlite3.Row, str], Hit]], ...] = (
    ("ticket", _TICKETS, _ticket),
    ("message", _MESSAGES, _message),
    ("chore_run", _CHORE_RUNS, _chore_run),
    ("decision", _DECISIONS, _decision),
    ("tick", _TICKS, _tick),
)
