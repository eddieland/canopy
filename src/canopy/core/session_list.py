"""Every session the runtime keeps, listed and found by its title, as the journal records them (DESIGN §13, M72).

While `sessions.search` is `titles`, the read the loop makes between ticks keeps each session's title
(`canopy.core.runtime_sessions`). This lists them, newest first: the sessions outside canopy, the operator's own and
another workspace's runs, or canopy's, each named by the run that made it. A subagent's session is listed under the
one it ran for, and an archived one is left out unless asked for, as the runtime's own list leaves it out. A list
narrowed to a directory holds only the sessions that ran in that one, not below it. None in a directory
`sessions.exclude` names is ever listed. With words, it finds the newest whose title holds every one, a
subagent's among them. It reads the journal alone, never the runtime's record, so it serves only what the read kept.

While `sessions.search` is `text`, words are found instead by the index of what each session said, did, and read
(`canopy.core.session_search`), ranked as it ranks them, each hit with a snippet read from the runtime's record; the
journal still says which sessions are listed, so the index never lists one the list would not.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, LiteralString, cast

from canopy.core import db, memory_search, records, runtime_sessions, session_search, sql

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable, Mapping, Sequence
    from pathlib import Path

    from canopy.core.run_models import RunTable
    from canopy.core.session_search import Hit
    from canopy.core.vocab import SessionsRead
    from canopy.runtime.implementation import Version

#: Whose sessions a list holds: those outside canopy, the operator's own and other workspaces' runs; or canopy's, this
#: journal's runs' and their subagents'.
type Whose = Literal["outside", "canopy"]

#: How a session's cost is held to a bound: below it, at most it, above it, or at least it.
type CostOp = Literal["lt", "lte", "gt", "gte"]

#: Each comparison of a session's cost with a bound, as SQL.
_COST: Final[Mapping[CostOp, LiteralString]] = {
    "lt": "cost_usd < ?",
    "lte": "cost_usd <= ?",
    "gt": "cost_usd > ?",
    "gte": "cost_usd >= ?",
}
#: How many sessions one list holds at most, and how many it holds by default.
MAX_LISTED: Final = 500
LISTED: Final = 50
#: How many subagents' sessions a list holds at most under the sessions it lists: far more than a run starts.
MAX_SUBAGENTS: Final = 2000
#: How many sessions up a subagent's is looked for the run that made it: far deeper than any runtime nests them, and a
#: bound on a parent chain a run wrote into a loop.
_MAX_DEPTH: Final = 50


@dataclass(frozen=True)
class MadeBy:
    """The run of canopy's that made a session, or the session a subagent of it ran for: its table and its id."""

    table: RunTable
    run_id: int
    #: The model canopy asked the runtime for, for the run's own session; None for the runtime's default, or for a
    #: subagent's session, whose model the run did not choose.
    model: str | None = None


@dataclass(frozen=True)
class CostBound:
    """A bound a list holds each session's own cost to, in dollars: only the sessions that cost `op` `usd`."""

    op: CostOp
    usd: float


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
    #: The model it was asked to run on, as `provider/model[@variant]`: the one the runtime records the session was set
    #: to, else the one canopy asked for its run. None when neither is known, as for the runtime's default.
    asked: str | None = None
    #: The models its replies name, the most costly first: what served it, which for a router is not what was asked.
    models: Sequence[str] = ()
    #: The sessions that ran for it as subagents, oldest first, each with its own; empty for a list found by words.
    subagents: Sequence[Listed] = ()
    #: Found by the index of what sessions said: its snippet, and how many more of its messages hold the words; None
    #: for a list not found so.
    hit: Hit | None = None


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
    directory: str | None = None,
    limit: int = LISTED,
    text: Version | None = None,
    model: str | None = None,
    costs: Collection[CostBound] = (),
) -> Listing:
    """List the runtime's sessions `whose` names, newest first, or find the newest whose title holds every word.

    `state_dir` is the workspace's, below which every session is canopy's, and `exclude` is `sessions.exclude`, whose
    directories' sessions are never listed. Without `words`, each session a subagent's ran for is listed with its
    subagents' under it. A word is found anywhere in a title, its case aside for ASCII letters, as `LIKE` finds it.
    `archived` lists the sessions the runtime archived too, and `directory` narrows the list to the sessions that ran in
    that directory exactly, their subagents' among them, none in one `exclude` names all the same. With `text`, the
    runtime that keeps the record, words are found by the index of what sessions said, the best match first. `model`
    narrows the list to the sessions asked to run on that model, or served by it, named exactly, each on a line of
    its own as one found by words is: where a router among the models was used, and what it routed to. `costs`
    narrows it to the sessions whose own cost, a subagent's apart, is within every bound, each on a line of its own
    the same way, so a subagent's that is within them is listed though the session it ran for is not.

    Returns:
        At most `limit` sessions, within `MAX_LISTED`, and how far the read has come.
    """
    limit = max(1, min(limit, MAX_LISTED))
    if text is not None and words:
        return _found(
            conn,
            whose=whose,
            state_dir=state_dir,
            exclude=exclude,
            words=words,
            archived=archived,
            directory=directory,
            limit=limit,
            version=text,
            model=model,
            costs=costs,
        )
    flat = bool(words) or model is not None or bool(costs)
    with db.read_snapshot(conn):
        query = _matching(
            whose,
            state_dir,
            exclude,
            archived=archived,
            directory=directory,
            model=model,
            costs=costs,
        )
        for word in words:
            query = query.where("title LIKE ? ESCAPE '\\'", f"%{_escaped(word)}%")
        if not flat and directory is None:
            query = query.where("parent_id IS NULL OR parent_id NOT IN (SELECT session_id FROM runtime_sessions)")
        elif not flat:
            # Narrowed, a session whose parent ran in another directory heads a tree of its own, so every session
            # that ran here is listed, however deep it ran.
            query = query.where(
                "parent_id IS NULL OR parent_id NOT IN (SELECT session_id FROM runtime_sessions WHERE directory = ?)",
                directory,
            )
        found = records.fetch_all(conn, _Session, query.order_by("started_at DESC, session_id").limit(limit + 1))
        shown = found[:limit]
        ids = [s.session_id for s in shown]
        below: list[_Session] = []
        if not flat:
            below = _subagents(
                conn,
                ids,
                whose=whose,
                state_dir=state_dir,
                exclude=exclude,
                archived=archived,
                directory=directory,
            )
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


# The sessions found by the index of what sessions said, of those the list would hold, the best match first, each with
# its hit.
def _found(
    conn: sqlite3.Connection,
    *,
    whose: Whose,
    state_dir: Path,
    exclude: Sequence[str],
    words: Sequence[str],
    archived: bool,
    directory: str | None,
    limit: int,
    version: Version,
    model: str | None,
    costs: Collection[CostBound],
) -> Listing:
    ours = whose == "canopy"
    # Each a word as memory's search reads it, never the index's query syntax.
    words = memory_search.words(" ".join(words))
    ranked = session_search.found(state_dir, words, canopy=ours)
    with db.read_snapshot(conn):
        query = _matching(
            whose,
            state_dir,
            exclude,
            archived=archived,
            directory=directory,
            model=model,
            costs=costs,
        ).where(
            "session_id IN (SELECT value FROM json_each(?))",
            json.dumps([f.session_id for f in ranked]),
        )
        listed = {s.session_id: s for s in records.fetch_all(conn, _Session, query)}
        kept = [f for f in ranked if f.session_id in listed]
        shown = kept[:limit]
        made = _made_by(conn, [f.session_id for f in shown]) if ours else {}
        found = [
            dataclasses.replace(
                _tree([listed[f.session_id]], [], made)[0],
                hit=session_search.hit(f, words, canopy=ours, version=version),
            )
            for f in shown
        ]
        return Listing(found, more=len(kept) > limit, progress=progress(conn, exclude))


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
    asked_model: str | None
    #: The models its replies name, a JSON array, the most costly first.
    models: str


# The sessions `whose` names, never one `exclude` names, an archived one only when `archived`, given a `directory`,
# only those that ran in it, given a `model`, only those asked to run on it, by the runtime's record or by the
# run that made them, or served by it, and only those whose cost is within each of `costs`.
def _matching(
    whose: Whose,
    state_dir: Path,
    exclude: Collection[str],
    *,
    archived: bool,
    directory: str | None,
    model: str | None = None,
    costs: Collection[CostBound] = (),
) -> sql.Select:
    query = (
        sql.select(
            "session_id, parent_id, title, directory, started_at, updated_at, cost_usd, archived_at, asked_model,"
            " models",
        )
        .from_("({}) AS c", runtime_sessions.sessions_in("", None, state_dir))
        .where("ours = ?", whose == "canopy")
        .where("NOT ({})", runtime_sessions.excluded(exclude))
    )
    if directory is not None:
        query = query.where("directory = ?", directory)
    for bound in costs:
        query = query.where(_COST[bound.op], bound.usd)
    if model is not None:
        ran = sql.any_of(
            *(
                sql.frag("EXISTS (SELECT 1 FROM {} WHERE session_id = c.session_id AND model = ?)", sql.name(t), model)
                for t in runtime_sessions.RUN_TABLES
            ),
        )
        query = query.where(
            "asked_model = ? OR EXISTS (SELECT 1 FROM runtime_session_models m WHERE m.session_id = c.session_id"
            " AND m.model = ?) OR {}",
            model,
            model,
            ran,
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
    directory: str | None,
) -> list[_Session]:
    if not ids:
        return []
    # Narrowed, the walk stays in the directory: one that ran elsewhere ends it, and what ran below it here heads a
    # tree of its own (`listing`).
    first, then = sql.frag("1"), sql.frag("1")
    if directory is not None:
        first, then = sql.frag("directory = ?", directory), sql.frag("s.directory = ?", directory)
    query = (
        _matching(whose, state_dir, exclude, archived=archived, directory=directory)
        .with_(
            "below(session_id, depth) AS ("
            "SELECT session_id, 1 FROM runtime_sessions WHERE parent_id IN (SELECT value FROM json_each(?)) AND {}"
            " UNION SELECT s.session_id, b.depth + 1 FROM runtime_sessions s JOIN below b ON s.parent_id = b.session_id"
            " WHERE b.depth < ? AND {})",
            json.dumps(list(ids)),
            first,
            _MAX_DEPTH,
            then,
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
            sql.select("session_id, ? AS run_table, id AS run_id, model", t)
            .from_("{}", sql.name(t))
            .where("session_id IN (SELECT at FROM up)")
            for t in runtime_sessions.RUN_TABLES
        ),
        every=True,
    )
    query = (
        sql.select("u.session_id, r.run_table, r.run_id, r.model, u.depth")
        .with_(
            "up(session_id, at, depth) AS ("
            "SELECT value, value, 0 FROM json_each(?)"
            " UNION SELECT u.session_id, s.parent_id, u.depth + 1 FROM up u JOIN runtime_sessions s"
            " ON s.session_id = u.at WHERE s.parent_id IS NOT NULL AND u.depth < ?)",
            json.dumps(list(ids)),
            _MAX_DEPTH,
            recursive=True,
        )
        .with_("ran(session_id, run_table, run_id, model) AS ({})", ran)
        .from_("up u")
        .join("ran r ON r.session_id = u.at")
        .order_by("u.depth DESC, r.run_table, r.run_id")
    )
    # The nearest is read last, so it is the one kept.
    made: dict[str, MadeBy] = {}
    for session_id, table, run_id, model, depth in sql.execute(conn, query):
        if table in runtime_sessions.RUN_TABLES and isinstance(run_id, int):
            asked = model if depth == 0 and isinstance(model, str) else None
            made[str(session_id)] = MadeBy(cast("RunTable", table), run_id, asked)
    return made


# The sessions listed, each with its subagents' under it, from those `below` them, oldest first.
def _tree(shown: Iterable[_Session], below: Sequence[_Session], made: dict[str, MadeBy]) -> list[Listed]:
    children: dict[str, list[_Session]] = {}
    for session in below:
        if session.parent_id is not None:
            children.setdefault(session.parent_id, []).append(session)

    def listed(session: _Session, seen: frozenset[str]) -> Listed:
        mine = [c for c in children.get(session.session_id, []) if c.session_id not in seen]
        by = made.get(session.session_id)
        return Listed(
            session_id=session.session_id,
            parent_id=session.parent_id,
            title=session.title,
            directory=session.directory,
            started_at=session.started_at,
            updated_at=session.updated_at,
            cost_usd=session.cost_usd,
            archived=session.archived_at is not None,
            made_by=by,
            asked=session.asked_model or (by.model if by is not None else None),
            models=tuple(m for m in json.loads(session.models) if isinstance(m, str)),
            subagents=tuple(listed(c, seen | {c.session_id}) for c in mine),
        )

    return [listed(s, frozenset({s.session_id})) for s in shown]


# The word as `LIKE` finds it literally: its wildcards, and the escape, escaped.
def _escaped(word: str) -> str:
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
