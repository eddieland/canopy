"""`canopy memory search` (DESIGN §28, Search): memories found by their words, ranked with bm25().

A worker's run searches what its prompt could have been served, and more of it: its own ticket's notes, the ones a
newer note under the key replaced and the ones the digest's cap left out included, and the lessons for the repositories
it leased. Each tier is searched only while it was at `use` for the run, by what the journal says the run was rendered
under, never by the config as it is now. A run never finds a pending proposal, an invalidated note, or another ticket's
notes. The operator's shell searches every memory that still has its text. It reads only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from canopy.core import db, memory, records, sql
from canopy.core.vocab import MemoryMode, MemoryScope, MemoryStatus, RunStatus

if TYPE_CHECKING:
    import sqlite3

# A query's words past these are not searched for.
MAX_WORDS: Final = 8
DEFAULT_LIMIT: Final = 10
MAX_LIMIT: Final = 50
# bm25()'s weight for a word in a memory's key, against 1 for one in its text: a key names what the memory is about.
_KEY_WEIGHT: Final = 2.0


class Unsearchable(Exception):  # noqa: N818  (a refusal, as `conversation.Refused` is)
    """A search names a run that is not one of canopy's running worker runs."""


@dataclass(frozen=True)
class RunScope:
    """What one run's search reaches: its ticket's notes and the lessons for its repositories, each while at `use`."""

    run_id: int
    ticket_key: str
    notes: bool
    lessons: bool
    repos: frozenset[str]

    @property
    def any(self) -> bool:
        """Whether the search reaches anything at all."""
        return self.notes or self.lessons


def run_scope(conn: sqlite3.Connection, run_id: int) -> RunScope:
    """Return what run `run_id`'s search reaches: what its tiers at `use` served it, by its journal row (DESIGN §28).

    Returns:
        The run's ticket, whether its notes and its lessons are searched, and the repositories it leased.

    Raises:
        Unsearchable: No run has the id, or the run has ended.
    """
    run = db.get_run(conn, run_id)
    if run is None:
        raise Unsearchable(f"no run {run_id}")
    if run["status"] != RunStatus.RUNNING:
        raise Unsearchable(f"run {run_id} has ended")
    rendered = memory.run_memory(conn, run_id)
    return RunScope(
        run_id=run_id,
        ticket_key=str(run["ticket_key"]),
        notes=rendered is not None and rendered.ticket_notes is MemoryMode.USE,
        lessons=rendered is not None and rendered.proposals is MemoryMode.USE,
        repos=frozenset(str(s.repo) for s in db.run_slots(conn, run_id) if s.repo is not None),
    )


def words(query: str) -> list[str]:
    """Return the words of `query` a search looks for: its runs of letters and digits, the first `MAX_WORDS`."""
    return re.findall(r"\w+", query)[:MAX_WORDS]


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    scope: RunScope | None,
    ticket: str | None = None,
    kind: MemoryScope | None = None,
    in_force: bool = False,
    every: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> list[records.Memory]:
    """Return the memories whose key or text holds any word of `query`, best match first, at most `limit`.

    With `scope`, only what that run reaches; without it, as the operator, every memory with a text, or with `ticket`
    only that ticket's notes and proposals. With `kind`, only memories of that scope, and with `in_force` only those in
    force, so the limit is spent on what the caller shows, not on what it would drop. With `every`, only the memories
    that hold every word, as the memory page's filter keeps its rows. Each word is matched as a word,
    its English endings aside, never as FTS5's query syntax, so no query a worker writes is an error.

    Returns:
        The memories found, ranked with bm25(), a word in a key weighing more than one in a text.

    Raises:
        ValueError: `query` has no word to search for.
    """
    found = words(query)
    if not found:
        raise ValueError("a search needs a word of letters or digits")
    match = (" AND " if every else " OR ").join(f'"{w}"' for w in found)
    return records.fetch_all(
        conn,
        records.Memory,
        sql.select("m.*")
        .from_("memories_fts")
        .join("memories m ON m.id = memories_fts.rowid")
        .where("memories_fts MATCH ?", match)
        .where("m.body IS NOT NULL")
        .where("{}", _reach(scope, ticket))
        .where("? IS NULL OR m.scope = ?", kind, kind)
        .where("? = 0 OR m.status = ?", in_force, MemoryStatus.ACTIVE)
        .order_by("bm25(memories_fts, ?, 1.0), m.id DESC", _KEY_WEIGHT)
        .limit(max(1, min(limit, MAX_LIMIT))),
    )


def _reach(scope: RunScope | None, ticket: str | None) -> sql.Fragment:
    """The condition naming the memories a search may find.

    Returns:
        The condition, with its values.
    """
    if scope is None:
        return sql.frag("? IS NULL OR m.ticket_key = ?", ticket, ticket)
    clauses: list[sql.Fragment] = []
    if scope.notes:
        clauses.append(
            sql.frag(
                "m.scope = ? AND m.ticket_key = ? AND {}",
                MemoryScope.TICKET,
                scope.ticket_key,
                sql.in_("m.status", (MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED)),
            ),
        )
    if scope.lessons:
        # With no repository leased, `IN ()` matches none, and only a lesson for every repository is found.
        clauses.append(
            sql.frag(
                "m.scope = ? AND m.status = ? AND (m.repo IS NULL OR {})",
                MemoryScope.LESSON,
                MemoryStatus.ACTIVE,
                sql.in_("m.repo", sorted(scope.repos)),
            ),
        )
    return sql.any_of(*clauses)
