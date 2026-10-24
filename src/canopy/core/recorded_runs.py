"""The runs the overseer asks for: recorded at the ask, started by its tick once the overseer's run ends (DESIGN §8).

A dispatch, a review, a revision, or a chore run the overseer asks for inside a tick is checked against every guard
and recorded here, never spawned from the overseer's process tree. Until its tick starts it, a guard refuses it then,
or the tick ends without starting it, a recorded run counts as running in every guard: its ticket's one run, its PR's,
its chore's, and its capacity. One the tick did not start is closed `unstarted` and counts toward no limit; no later
tick starts it, since that tick decides again from what it reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, records, sql
from canopy.core.vocab import RecordedKind, RecordedStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

#: The kinds that hold a worker's slot, and so count toward `capacity.max_workers`; a chore run holds none.
SLOT_KINDS = frozenset({RecordedKind.DISPATCH, RecordedKind.REVIEW, RecordedKind.REVISION})
#: The kinds that are review runs, which count toward `capacity.max_reviews` and the day's reviews.
REVIEW_KINDS = frozenset({RecordedKind.REVIEW, RecordedKind.REVISION})


def record(
    conn: sqlite3.Connection,
    *,
    tick_id: int,
    kind: RecordedKind,
    rank: int,
    request: str,
    ticket_key: str | None = None,
    pr: str | None = None,
    persona: str | None = None,
    chore: str | None = None,
) -> int:
    """Record a run the overseer asked for in tick `tick_id`, whose guards passed; the caller holds the dispatch lock.

    `request` is the overseer's request, validated, as JSON, which its tick starts the run from; `rank` its place in
    §7's order. `ticket_key`, `pr`, `persona`, and `chore` are what it holds while recorded.

    Returns:
        The recorded run's id.
    """
    insert = sql.insert(
        "recorded_runs",
        tick_id=tick_id,
        kind=kind,
        rank=rank,
        request=request,
        ticket_key=ticket_key,
        pr=pr,
        persona=persona,
        chore=chore,
        recorded_at=db.now(),
    )
    return db.rowid(sql.execute(conn, insert))


def held(conn: sqlite3.Connection, *, but: int | None = None) -> list[records.RecordedRun]:
    """The runs recorded and not yet started, which count as running, but `but`, the one being started.

    Returns:
        Them, oldest first.
    """
    query = sql.select("*").from_("recorded_runs").where("status = ?", RecordedStatus.RECORDED)
    if but is not None:
        query = query.where("id != ?", but)
    return records.fetch_all(conn, records.RecordedRun, query.order_by("id"))


def of_tick(conn: sqlite3.Connection, tick_id: int) -> list[records.RecordedRun]:
    """The runs tick `tick_id` recorded and has not started, in §7's order, then as they were asked for.

    Returns:
        Them, in the order the tick starts them.
    """
    query = (
        sql.select("*")
        .from_("recorded_runs")
        .where("tick_id = ? AND status = ?", tick_id, RecordedStatus.RECORDED)
        .order_by("rank, id")
    )
    return records.fetch_all(conn, records.RecordedRun, query)


def get(conn: sqlite3.Connection, recorded_id: int) -> records.RecordedRun | None:
    """Return the recorded run `recorded_id`, or None."""
    query = sql.select("*").from_("recorded_runs").where("id = ?", recorded_id)
    return records.fetch_one(conn, records.RecordedRun, query)


def close(conn: sqlite3.Connection, recorded_id: int, status: RecordedStatus, *, run_id: int | None = None) -> None:
    """Close recorded run `recorded_id` as `status`, naming the run it started, if it is still recorded."""
    update = (
        sql.update("recorded_runs")
        .set(status=status, run_id=run_id, ended_at=db.now())
        .where("id = ? AND status = ?", recorded_id, RecordedStatus.RECORDED)
    )
    sql.execute(conn, update)


def close_unstarted(conn: sqlite3.Connection, *, tick_id: int | None = None) -> list[int]:
    """Close every run still recorded, tick `tick_id`'s alone when given, as `unstarted`: no later tick starts one.

    A tick calls it as it closes, for its own, and at its start, for those a tick that died left (DESIGN §6 step 2).

    Returns:
        The ids of the runs closed.
    """
    update = sql.update("recorded_runs").set(status=RecordedStatus.UNSTARTED, ended_at=db.now())
    update = update.where("status = ?", RecordedStatus.RECORDED)
    if tick_id is not None:
        update = update.where("tick_id = ?", tick_id)
    return [int(r[0]) for r in sql.execute(conn, update.returning("id")).fetchall()]


def slots(found: Sequence[records.RecordedRun]) -> int:
    """How many of `found` hold a worker's slot once started: dispatches, reviews, and revisions.

    Returns:
        The count.
    """
    return sum(r.kind in SLOT_KINDS for r in found)


def reviews(found: Sequence[records.RecordedRun]) -> list[records.RecordedRun]:
    """The review runs among `found`: reviews and revisions.

    Returns:
        Them, in `found`'s order.
    """
    return [r for r in found if r.kind in REVIEW_KINDS]
