"""A tick's runs of the overseer (DESIGN §40): the subject each was given, how it ended, its session, and its cost.

A tick that runs its overseer records the run as it starts, and what the runtime reported and how it ended once it
ends, beside what `ticks` keeps of it. A tick makes one run, given the whole state block, its subject None, unless
`loop.overseer_per_subject` is on: then it makes one for each subject left to the overseer, one at a time, each given
that subject alone: a ticket, by its key; a PR to review, `pr:<url>`; or the due chores together, `CHORES`. No ticket
key holds a `:`, so no subject's name is another's. One still running when its tick closes failed with the tick; one a
dead tick left running is closed `abandoned` by the next.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, records
from canopy.core.vocab import OverseerRunStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection

    from canopy.runtime.report import Usage

#: What a PR's subject starts with, before its URL, as the attention list names a PR with no ticket.
PR_PREFIX = "pr:"
#: The subject of the run given the due chores with a `when`, together.
CHORES = "chore:*"


def start(conn: sqlite3.Connection, tick_id: int, *, subject: str | None = None) -> int:
    """Record a run of the overseer starting in tick `tick_id`, given `subject`, or the whole state block for None.

    Returns:
        The run's id.
    """
    insert = records.insert(records.OverseerRun, tick_id=tick_id, subject=subject, started_at=db.now())
    return db.rowid(insert.run(conn))


def set_model(conn: sqlite3.Connection, run_id: int, model: str | None) -> None:
    """Record the model run `run_id` asks the runtime for (DESIGN §13); None for the runtime's default."""
    records.update(records.OverseerRun).set(model=model).where("id = ?", run_id).run(conn)


def report(conn: sqlite3.Connection, run_id: int, session_id: str | None, usage: Usage | None) -> None:
    """Record what the runtime reported of run `run_id` once it ended: its session and what it cost, each if any."""
    update = db.spent_on(records.update(records.OverseerRun), usage).set(session_id=session_id)
    update.where("id = ?", run_id).run(conn)


def end(conn: sqlite3.Connection, run_id: int, failure: str | None, *, undone: bool = False) -> None:
    """Close run `run_id`: `ok` with no `failure`, else `failed` with it. Nothing changes for one already closed.

    With `undone`, it ended well and left a duty undone, `failure` naming them (DESIGN §6 step 5).
    """
    if failure is None:
        status = OverseerRunStatus.OK
    else:
        status = OverseerRunStatus.UNDONE if undone else OverseerRunStatus.FAILED
    _closing(status, failure).where("id = ?", run_id).run(conn)


def running(conn: sqlite3.Connection, tick_id: int) -> records.OverseerRun | None:
    """Tick `tick_id`'s run of the overseer still running: its runs go one at a time, so there is at most one.

    Returns:
        The run, or None between runs and outside them.
    """
    query = records.select(records.OverseerRun).where("tick_id = ? AND status = ?", tick_id, OverseerRunStatus.RUNNING)
    return query.order_by("id DESC").limit(1).one(conn)


def subjects(conn: sqlite3.Connection, ticks: Collection[int]) -> dict[int, set[str | None]]:
    """The subject each run of each of `ticks` was given, None for a run given the whole state block.

    Returns:
        By tick, its runs' subjects; a tick that made no run has no entry.
    """
    found: dict[int, set[str | None]] = {}
    if not ticks:
        return found
    for run in records.select(records.OverseerRun).where_in("tick_id", ticks).all(conn):
        found.setdefault(run.tick_id, set()).add(run.subject)
    return found


def left_undone(conn: sqlite3.Connection, tick_id: int, undone: str) -> None:
    """Mark tick `tick_id`'s runs that ended `ok` as `undone`, `undone` naming the duties they left (DESIGN §6)."""
    update = records.update(records.OverseerRun).set(status=OverseerRunStatus.UNDONE, failure=undone)
    update.where("tick_id = ? AND status = ?", tick_id, OverseerRunStatus.OK).run(conn)


def close_running(conn: sqlite3.Connection, tick_id: int, failure: str) -> None:
    """Close tick `tick_id`'s runs still running as it closes, `failed` with `failure`, the tick's summary."""
    _closing(OverseerRunStatus.FAILED, failure).where("tick_id = ?", tick_id).run(conn)


def close_abandoned(conn: sqlite3.Connection) -> None:
    """Close every run still running `abandoned`: its tick's process died. Call only while holding the tick lock."""
    _closing(OverseerRunStatus.ABANDONED, None).run(conn)


def _closing(status: OverseerRunStatus, failure: str | None) -> records.Update[records.OverseerRun]:
    """An update closing the runs still running as `status`, with `failure`, stamped now.

    Returns:
        The update, for the caller to narrow to the runs it closes.
    """
    return (
        records.update(records.OverseerRun)
        .set(status=status, failure=failure, ended_at=db.now())
        .where("status = ?", OverseerRunStatus.RUNNING)
    )
