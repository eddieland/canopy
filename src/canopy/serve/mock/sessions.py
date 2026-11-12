"""The runtime's sessions as the mock's loop last read them (DESIGN §13), for the Sessions page and the search's panels.

`sessions.search` is `titles`, so the read kept each session's title. Every agent run the journal holds has its
session, titled as canopy titles it, at the run's start and cost; run 41's worker ran a subagent to explore the code.
Outside canopy, the operator's own: a question about the deploy script with a subagent of its own, notes, a bisect, a
session the runtime archived, and another workspace's worker run, each in its own directory under their home. One more
ran in a client's directory, which `sessions.exclude` names, so it is listed nowhere. Each of those started on T0's day,
as the journal's runs did but for its months before T0, so the spend page's day holds them all. The loop read them
eight minutes after T0.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from canopy.core import db, records, runtime_sessions
from canopy.runtime.report import SessionPage, SessionSpend

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Iterator
    from datetime import datetime
    from pathlib import Path

#: The directory the mock's `sessions.exclude` names, whose sessions are listed nowhere.
EXCLUDED = "/home/op/clients/globex"
#: The operator's session that ran a subagent of its own, under which the page lists it.
DEPLOY = "ses_op_deploy"
#: The subagent run 41's worker ran.
EXPLORE = "ses_mock41_explore"

# The sessions outside canopy: id, the session it ran for, title, directory, minutes after T0 it started and was last
# updated, what it cost, and whether the runtime archived it.
_OUTSIDE: tuple[tuple[str, str | None, str, str, int, int, float, bool], ...] = (
    (DEPLOY, None, "Why does the deploy script hang on staging?", "/home/op/acme/infra", -48, -9, 0.84, False),
    (
        "ses_op_deploy_find",
        DEPLOY,
        "Find where deploy.sh waits on the health check",
        "/home/op/acme/infra",
        -40,
        -31,
        0.19,
        False,
    ),
    ("ses_op_notes", None, "Outline the Q4 planning doc", "/home/op/notes", -190, -150, 0.21, False),
    (
        "ses_op_other",
        None,
        "XYZ-12 implement: Rate-limit the export endpoint",
        "/home/op/beta/.treehouse/api-5d1e0b2c/1/api",
        -420,
        -360,
        1.12,
        False,
    ),
    ("ses_op_bisect", None, "Bisect the flaky checkout test", "/home/op/src/web-experiments", -690, -600, 1.37, False),
    ("ses_op_router", None, "Try the new router's loaders", "/home/op/scratch/router", -710, -700, 0.46, True),
    ("ses_op_globex", None, "Globex invoice export totals", EXCLUDED, -300, -280, 0.58, False),
)


def seed(conn: sqlite3.Connection, t0: datetime, root: Path) -> None:
    """Record the runtime's sessions, canopy's and the operator's, as the loop's read under `sessions.exclude` would.

    `t0` is the mock's T0, and `root` the workspace's root, where canopy's ticks ran.
    """

    def ms(minutes: int) -> int:
        return int((t0 + timedelta(minutes=minutes)).timestamp() * 1000)

    sessions = [*_canopys(conn, root, ms), *_outside(ms)]
    last = max(sessions, key=lambda s: (s.updated_ms, s.session_id))
    runtime_sessions.record(
        conn,
        SessionPage("found", tuple(sessions), cursor=(last.updated_ms, last.session_id)),
        now=db.format_time(t0 + timedelta(minutes=8)),
        titles=runtime_sessions.titles_setting([EXCLUDED]),
        restarted=True,
    )


# Each run's session, titled as canopy titles it, and run 41's subagent.
def _canopys(conn: sqlite3.Connection, root: Path, ms: Callable[[int], int]) -> Iterator[SessionSpend]:
    home = str(root)
    for tick in records.select(records.Tick).all(conn):
        yield from _session(tick.session_id, f"tick {tick.id} · {tick.woken_by}", home, tick.started_at, tick.cost_usd)
    for run in records.select(records.Run).all(conn):
        ticket = db.get_ticket(conn, run.ticket_key)
        named = f": {ticket.title}" if ticket is not None and ticket.title else ""
        title = f"{run.ticket_key} {run.kind}{named}"
        yield from _session(run.session_id, title, home, run.started_at, run.cost_usd)
    for review in records.select(records.ReviewRun).all(conn):
        yield from _session(review.session_id, f"review {review.pr_url}", home, review.started_at, review.cost_usd)
    for chore in records.select(records.ChoreRun).all(conn):
        yield from _session(chore.session_id, f"chore {chore.chore}", home, chore.started_at, chore.cost_usd)
    for task in records.select(records.TaskRun).all(conn):
        yield from _session(task.session_id, f"task {task.task_id}", home, task.started_at, task.cost_usd)
    for epic in records.select(records.EpicRun).all(conn):
        yield from _session(epic.session_id, f"epic {epic.epic_id} plan", home, epic.started_at, epic.cost_usd)
    yield SessionSpend(
        session_id=EXPLORE,
        parent_id="ses_mock41",
        directory=home,
        created_ms=ms(3),
        updated_ms=ms(6),
        cost_usd=0.04,
        input=0,
        output=0,
        reasoning=0,
        cache_read=0,
        cache_write=0,
        title="Explore where the login redirect is decided",
    )


# A run's session as the runtime reports it, when the run names one.
def _session(
    session_id: str | None,
    title: str,
    directory: str,
    started_at: str,
    cost: float | None,
) -> list[SessionSpend]:
    if session_id is None:
        return []
    at = int(db.parse_time(started_at).timestamp() * 1000)
    spent = SessionSpend(
        session_id=session_id,
        parent_id=None,
        directory=directory,
        created_ms=at,
        updated_ms=at,
        cost_usd=cost or 0.0,
        input=0,
        output=0,
        reasoning=0,
        cache_read=0,
        cache_write=0,
        title=title,
    )
    return [spent]


def _outside(ms: Callable[[int], int]) -> Iterator[SessionSpend]:
    for session_id, parent, title, directory, started, updated, cost, archived in _OUTSIDE:
        yield SessionSpend(
            session_id=session_id,
            parent_id=parent,
            directory=directory,
            created_ms=ms(started),
            updated_ms=ms(updated),
            cost_usd=cost,
            input=int(cost * 40_000),
            output=int(cost * 6_000),
            reasoning=0,
            cache_read=int(cost * 400_000),
            cache_write=0,
            title=title,
            archived_ms=ms(updated) if archived else None,
        )
