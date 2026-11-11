"""Every session the runtime keeps, listed and found by its title, as the journal records them (DESIGN §13, M72).

While `sessions.search` is `titles`, the read the loop makes between ticks keeps each session's title
(`canopy.core.runtime_sessions`). This lists them, newest first: the sessions outside canopy, the operator's own and
another workspace's runs, or canopy's, each named by the run that made it. A subagent's session is listed under the
one it ran for, and an archived one is left out unless asked for, as the runtime's own list leaves it out. None in a
directory `sessions.exclude` names is ever listed. With words, it finds the newest whose title holds every one, a
subagent's among them. It reads the journal alone, never the runtime's record, so it serves only what the read kept.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from canopy.core import db, records, runtime_sessions, sql

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable, Sequence
    from pathlib import Path

    from canopy.core.run_models import RunTable
    from canopy.core.vocab import SessionsRead

#: Whose sessions a list holds: those outside canopy, the operator's own and other workspaces' runs; or canopy's, this
#: journal's runs' and their subagents'.
type Whose = Literal["outside", "canopy"]

#: How many sessions one list holds at most, and how many it holds by default.
MAX_LISTED = 500
LISTED = 50
#: How many subagents' sessions a list holds at most under the sessions it lists: far more than a run starts.
MAX_SUBAGENTS = 2000
#: How many sessions up a subagent's is looked for the run that made it: far deeper than any runtime nests them, and a
#: bound on a parent chain a run wrote into a loop.
_MAX_DEPTH = 50


@dataclass(frozen=True)
class MadeBy:
    """The run of canopy's that made a session, or the session a subagent of it ran for: its table and its id."""

    table: RunTable
    run_id: int


@dataclass(frozen=True)
class Listed:
    """A session the runtime keeps, as a list shows it."""

    session_id: str
    #: The session it ran for, as a subagent; None for a session of its own.
    parent_id: str | None
    #: As the read kept it; None when it has none, or was not read since titles were kept.
    title: str | None
    directory: str
    started_at: str
    updated_at: str
    cost_usd: float
    #: Whether the runtime archived it, so its own list leaves it out.
    archived: bool
    #: For one of canopy's, the run that made it; None for one outside, or one of canopy's no run names, as a chore's
    #: trial run that records none.
    made_by: MadeBy | None
    #: The sessions that ran for it as subagents, oldest first, each with its own; empty for a list found by words.
    subagents: Sequence[Listed] = ()


@dataclass(frozen=True)
class Progress:
    """How far the read of the runtime's record has come, as a list says it."""

    #: How the last read ended, and when; both None before the loop's first.
    status: SessionsRead | None
    read_at: str | None
    #: canopy's words for why the last read failed; None unless it did.
    error: str | None
    #: The update of the last session read, as a journal time: every session updated before it was read; None before
    #: the first.
    through: str | None
    #: Whether the read keeps titles as `sessions.exclude` now says: False until the loop's next read starts again
    #: from the first session under it.
    current: bool


@dataclass(frozen=True)
class Listing:
    """A list of the runtime's sessions, newest first, and how far the read that kept them has come."""

    sessions: Sequence[Listed]
    #: Whether more sessions matched than it lists.
    more: bool
    progress: Progress


def listing(
    conn: sqlite3.Connection,
    *,
    whose: Whose,
    state_dir: Path,
    exclude: Sequence[str],
    words: Sequence[str] = (),
    archived: bool = False,
    limit: int = LISTED,
) -> Listing:
    """List the runtime's sessions `whose` names, newest first, or find the newest whose title holds every word.

    `state_dir` is the workspace's, below which every session is canopy's, and `exclude` is `sessions.exclude`, whose
    directories' sessions are never listed. Without `words`, each session a subagent's ran for is listed with its
    subagents' under it. A word is found anywhere in a title, its case aside for ASCII letters, as `LIKE` finds it.
    `archived` lists the sessions the runtime archived too.

    Returns:
        At most `limit` sessions, within `MAX_LISTED`, and how far the read has come.
    """
    limit = max(1, min(limit, MAX_LISTED))
    with db.read_snapshot(conn):
        query = _matching(whose, state_dir, exclude, archived=archived)
        for word in words:
            query = query.where("title LIKE ? ESCAPE '\\'", f"%{_escaped(word)}%")
        if not words:
            query = query.where("parent_id IS NULL OR parent_id NOT IN (SELECT session_id FROM runtime_sessions)")
        found = records.fetch_all(conn, _Session, query.order_by("started_at DESC, session_id").limit(limit + 1))
        shown = found[:limit]
        ids = [s.session_id for s in shown]
        below: list[_Session] = []
        if not words:
            below = _subagents(conn, ids, whose=whose, state_dir=state_dir, exclude=exclude, archived=archived)
        made = _made_by(conn, [s.session_id for s in [*shown, *below]]) if whose == "canopy" else {}
        listed = _tree(shown, below, made)
        return Listing(listed, more=len(found) > limit, progress=progress(conn, exclude))


def progress(conn: sqlite3.Connection, exclude: Sequence[str]) -> Progress:
    """How far the read of the runtime's record has come, with `exclude`, `sessions.exclude`, in force.

    Returns:
        How the last read ended, how far it has read, and whether it keeps titles as `exclude` says.
    """
    read = runtime_sessions.last_read(conn)
    if read is None:
        return Progress(status=None, read_at=None, error=None, through=None, current=False)
    through = None
    if read.cursor_session_id is not None:
        session = runtime_sessions.of_session(conn, read.cursor_session_id)
        through = session.updated_at if session is not None else None
    return Progress(
        status=read.status,
        read_at=read.read_at,
        error=read.error,
        through=through,
        current=read.titles == runtime_sessions.titles_setting(exclude),
    )


@dataclass(frozen=True)
class _Session(records.View):
    """A session as `runtime_sessions.sessions_in` reads it, the columns a list shows."""

    session_id: str
    parent_id: str | None
    title: str | None
    directory: str
    started_at: str
    updated_at: str
    cost_usd: float
    archived_at: str | None


# The sessions `whose` names, never one `exclude` names, and an archived one only when `archived`.
def _matching(whose: Whose, state_dir: Path, exclude: Collection[str], *, archived: bool) -> sql.Select:
    query = (
        sql.select("session_id, parent_id, title, directory, started_at, updated_at, cost_usd, archived_at")
        .from_("({}) AS c", runtime_sessions.sessions_in("", None, state_dir))
        .where("ours = ?", whose == "canopy")
        .where("NOT ({})", runtime_sessions.excluded(exclude))
    )
    return query if archived else query.where("archived_at IS NULL")


# The sessions that ran for the sessions `ids` names, as subagents, however deep, as `_matching` finds them, oldest
# first, at most `MAX_SUBAGENTS`.
def _subagents(
    conn: sqlite3.Connection,
    ids: Sequence[str],
    *,
    whose: Whose,
    state_dir: Path,
    exclude: Collection[str],
    archived: bool,
) -> list[_Session]:
    if not ids:
        return []
    query = (
        _matching(whose, state_dir, exclude, archived=archived)
        .with_(
            "below(session_id, depth) AS ("
            "SELECT session_id, 1 FROM runtime_sessions WHERE parent_id IN (SELECT value FROM json_each(?))"
            " UNION SELECT s.session_id, b.depth + 1 FROM runtime_sessions s JOIN below b ON s.parent_id = b.session_id"
            " WHERE b.depth < ?)",
            json.dumps(list(ids)),
            _MAX_DEPTH,
            recursive=True,
        )
        .where("session_id IN (SELECT session_id FROM below)")
        .order_by("started_at, session_id")
        .limit(MAX_SUBAGENTS)
    )
    return records.fetch_all(conn, _Session, query)


# The run that made each of the sessions `ids` names, by its id: its own, or the nearest of the sessions it ran for.
def _made_by(conn: sqlite3.Connection, ids: Sequence[str]) -> dict[str, MadeBy]:
    if not ids:
        return {}
    ran = sql.union(
        *(
            sql.select("session_id, ? AS run_table, id AS run_id", t)
            .from_("{}", sql.name(t))
            .where("session_id IN (SELECT at FROM up)")
            for t in runtime_sessions.RUN_TABLES
        ),
        every=True,
    )
    query = (
        sql.select("u.session_id, r.run_table, r.run_id")
        .with_(
            "up(session_id, at, depth) AS ("
            "SELECT value, value, 0 FROM json_each(?)"
            " UNION SELECT u.session_id, s.parent_id, u.depth + 1 FROM up u JOIN runtime_sessions s"
            " ON s.session_id = u.at WHERE s.parent_id IS NOT NULL AND u.depth < ?)",
            json.dumps(list(ids)),
            _MAX_DEPTH,
            recursive=True,
        )
        .with_("ran(session_id, run_table, run_id) AS ({})", ran)
        .from_("up u")
        .join("ran r ON r.session_id = u.at")
        .order_by("u.depth DESC, r.run_table, r.run_id")
    )
    # The nearest is read last, so it is the one kept.
    made: dict[str, MadeBy] = {}
    for session_id, table, run_id in sql.execute(conn, query):
        if table in runtime_sessions.RUN_TABLES and isinstance(run_id, int):
            made[str(session_id)] = MadeBy(cast("RunTable", table), run_id)
    return made


# The sessions listed, each with its subagents' under it, from those `below` them, oldest first.
def _tree(shown: Iterable[_Session], below: Sequence[_Session], made: dict[str, MadeBy]) -> list[Listed]:
    children: dict[str, list[_Session]] = {}
    for session in below:
        if session.parent_id is not None:
            children.setdefault(session.parent_id, []).append(session)

    def listed(session: _Session, seen: frozenset[str]) -> Listed:
        mine = [c for c in children.get(session.session_id, []) if c.session_id not in seen]
        return Listed(
            session_id=session.session_id,
            parent_id=session.parent_id,
            title=session.title,
            directory=session.directory,
            started_at=session.started_at,
            updated_at=session.updated_at,
            cost_usd=session.cost_usd,
            archived=session.archived_at is not None,
            made_by=made.get(session.session_id),
            subagents=tuple(listed(c, seen | {c.session_id}) for c in mine),
        )

    return [listed(s, frozenset({s.session_id})) for s in shown]


# The word as `LIKE` finds it literally: its wildcards, and the escape, escaped.
def _escaped(word: str) -> str:
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
