"""The runtime's sessions as the API sends them (DESIGN §13): listed, and found by their titles.

`canopy sessions` lists the same, through the same read of the journal (`canopy.core.session_list`): while
`sessions.search` is `titles`, every session the loop's read kept, but those in a directory `sessions.exclude` names.
At `off` it serves none. Each of canopy's names the run that made it, with what its page needs, and each outside canopy
the command that reopens it in the runtime. A title is untrusted text, which the UI renders as text.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import db, records, session_list
from canopy.runtime import sessions as runtime_sessions
from canopy.serve import search
from canopy.serve.schema.sessions import RuntimeSession, SessionList, SessionRun, SessionsProgress

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable

    from canopy.core.context import Context
    from canopy.core.run_models import RunTable
    from canopy.core.session_list import Listed, MadeBy, Progress, Whose
    from canopy.runtime.implementation import Version
    from canopy.serve.schema.sessions import SessionRunKind

#: What each table of canopy's runs is, as a session's run names it.
RUN_KINDS: dict[RunTable, SessionRunKind] = {
    "ticks": "tick",
    "runs": "run",
    "chore_runs": "chore_run",
    "review_runs": "review",
    "task_runs": "task_run",
    "epic_runs": "epic_run",
}
# A row whose id is among those of a JSON array.
_AMONG = "id IN (SELECT value FROM json_each(?))"


def listed(
    ctx: Context,
    *,
    whose: Whose,
    query: str | None = None,
    archived: bool = False,
    directory: str | None = None,
    limit: int = session_list.LISTED,
) -> SessionList:
    """The sessions `whose` names, newest first, or the newest whose title holds every word of `query`.

    `archived` lists the sessions the runtime archived too, and `directory` only those that ran in it exactly; one
    `sessions.exclude` names lists none. Nothing is read while `sessions.search` is `off`.

    Returns:
        At most `limit` sessions, each of canopy's with its run, each outside canopy with its command, and how far the
        read has come; none, and no progress, at `off`.

    Raises:
        search.BadQueryError: `query` is too short, too long, or has too many words, as a search of the journal's is.
    """
    words = search.words(query) if query is not None else ()
    setting = ctx.config.sessions
    if setting.search == "off":
        return SessionList(search="off", whose=whose, words=list(words), sessions=[], more=False)
    # One snapshot, so a run each session names is in the journal the list was read from.
    with db.read_snapshot(ctx.conn):
        found = session_list.listing(
            ctx.conn,
            whose=whose,
            state_dir=ctx.state_dir,
            exclude=setting.exclude,
            words=words,
            archived=archived,
            directory=directory,
            limit=limit,
        )
        runs = _runs(ctx.conn, [s.made_by for s in _every(found.sessions) if s.made_by is not None])
    version = ctx.config.runtime.version
    return SessionList(
        search=setting.search,
        whose=whose,
        words=list(words),
        sessions=[_session(s, runs, version=version, outside=whose == "outside") for s in found.sessions],
        more=found.more,
        progress=_progress(found.progress),
    )


def _every(sessions: Iterable[Listed]) -> list[Listed]:
    return [each for s in sessions for each in (s, *_every(s.subagents))]


# The pages of the runs `made` names, by each one's table and id: a run's ticket, a chore run's chore, a task run's
# task, and an epic run's epic, read in one query a table.
def _runs(conn: sqlite3.Connection, made: Collection[MadeBy]) -> dict[tuple[RunTable, int], SessionRun]:
    found: dict[tuple[RunTable, int], SessionRun] = {
        (m.table, m.run_id): SessionRun(kind=RUN_KINDS[m.table], id=m.run_id) for m in made
    }
    for row in records.select(records.Run).where(_AMONG, _ids(made, "runs")).all(conn):
        found["runs", row.id] = SessionRun(kind="run", id=row.id, ticket_key=row.ticket_key)
    for review in records.select(records.ReviewRun).where(_AMONG, _ids(made, "review_runs")).all(conn):
        found["review_runs", review.id] = SessionRun(kind="review", id=review.id, ticket_key=review.ticket_key)
    for chore in records.select(records.ChoreRun).where(_AMONG, _ids(made, "chore_runs")).all(conn):
        found["chore_runs", chore.id] = SessionRun(kind="chore_run", id=chore.id, chore=chore.chore)
    for task in records.select(records.TaskRun).where(_AMONG, _ids(made, "task_runs")).all(conn):
        found["task_runs", task.id] = SessionRun(kind="task_run", id=task.id, task_id=task.task_id)
    for epic in records.select(records.EpicRun).where(_AMONG, _ids(made, "epic_runs")).all(conn):
        found["epic_runs", epic.id] = SessionRun(kind="epic_run", id=epic.id, epic_id=epic.epic_id)
    return found


# The ids of the runs of `table` that `made` names, as a JSON array for `_AMONG`.
def _ids(made: Iterable[MadeBy], table: RunTable) -> str:
    return json.dumps([m.run_id for m in made if m.table == table])


def _session(
    session: Listed,
    runs: dict[tuple[RunTable, int], SessionRun],
    *,
    version: Version,
    outside: bool,
) -> RuntimeSession:
    made = session.made_by
    return RuntimeSession(
        session_id=session.session_id,
        parent_id=session.parent_id,
        title=session.title,
        directory=session.directory,
        started_at=db.parse_time(session.started_at),
        updated_at=db.parse_time(session.updated_at),
        cost_usd=session.cost_usd,
        archived=session.archived,
        made_by=runs.get((made.table, made.run_id)) if made is not None else None,
        reopen=runtime_sessions.reopen(session.session_id, session.directory, version=version) if outside else None,
        subagents=[_session(s, runs, version=version, outside=outside) for s in session.subagents],
    )


def _progress(progress: Progress) -> SessionsProgress:
    return SessionsProgress(
        status=progress.status.value if progress.status is not None else None,
        read_at=db.parse_time(progress.read_at) if progress.read_at is not None else None,
        error=progress.error,
        through=db.parse_time(progress.through) if progress.through is not None else None,
        current=progress.current,
    )
