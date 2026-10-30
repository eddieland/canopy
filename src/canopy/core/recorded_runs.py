"""The runs the overseer asks for, recorded at the ask and spawned by the tick after its run (DESIGN §40).

A dispatch, a review, a revision of a review's draft, or a chore's run the overseer asks for, through a tool or its
command, passes its guards and is recorded here, never spawned from the overseer's process tree. Until the tick spawns
it, it counts as running in every guard's count: it is its ticket's one run, and holds a worker, or a chore run, as a
running one does (`holding`). It leases no slot. The tick spawns it once the overseer's run has ended, under its guards
again; one it did not spawn is closed `unstarted` as the tick closes, or as the next tick starts when this one died, and
counts toward no limit then, since only a run that started does.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import db, records, sql
from canopy.core.vocab import RecordedKind, RecordedStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping

#: The kinds that hold a worker, within `capacity.max_workers`, while recorded: each leases a slot once it starts.
HOLDS_WORKER = frozenset({RecordedKind.DISPATCH, RecordedKind.REVIEW, RecordedKind.REVISION})
#: The kinds that hold a review run, within `capacity.max_reviews` and the day's reviews, while recorded.
HOLDS_REVIEW = frozenset({RecordedKind.REVIEW, RecordedKind.REVISION})


def record(
    conn: sqlite3.Connection,
    *,
    tick_id: int,
    kind: RecordedKind,
    request: Mapping[str, object],
    ticket_key: str | None = None,
    pr_url: str | None = None,
    persona: str | None = None,
    chore: str | None = None,
) -> int:
    """Record a run the overseer asked for in tick `tick_id`, its guards passed, with what it holds until it starts.

    The caller holds the dispatch lock, across the guards and this insert, so two asks cannot both pass a limit.

    Returns:
        The recorded run's id.
    """
    insert = records.insert(
        records.RecordedRun,
        tick_id=tick_id,
        kind=kind,
        request=json.dumps(request, sort_keys=True),
        ticket_key=ticket_key,
        pr_url=pr_url,
        persona=persona,
        chore=chore,
        recorded_at=db.now(),
    )
    return db.rowid(insert.run(conn))


def holding(conn: sqlite3.Connection, *, but: int | None = None) -> list[records.RecordedRun]:
    """The recorded runs not yet spawned or closed, which count as running, but `but`, the one being spawned.

    Returns:
        Them, oldest first.
    """
    query = sql.select("*").from_("recorded_runs").where("status = ?", RecordedStatus.RECORDED)
    if but is not None:
        query = query.where("id != ?", but)
    return records.fetch_all(conn, records.RecordedRun, query.order_by("id"))


def workers(held: Iterable[records.RecordedRun]) -> list[records.RecordedRun]:
    """Those of `held` that hold a worker: a dispatch, a review, or a revision.

    Returns:
        Them, in `held`'s order.
    """
    return [r for r in held if r.kind in HOLDS_WORKER]


def of_tick(conn: sqlite3.Connection, tick_id: int) -> list[records.RecordedRun]:
    """The runs tick `tick_id` recorded and has not spawned or closed.

    Returns:
        Them, in the order they were asked for.
    """
    query = sql.select("*").from_("recorded_runs").where("tick_id = ? AND status = ?", tick_id, RecordedStatus.RECORDED)
    return records.fetch_all(conn, records.RecordedRun, query.order_by("id"))


def get(conn: sqlite3.Connection, recorded_id: int) -> records.RecordedRun | None:
    """Return the recorded run `recorded_id`, or None."""
    query = records.select(records.RecordedRun).where("id = ?", recorded_id)
    return query.one(conn)


def request_of(recorded: records.RecordedRun) -> dict[str, object]:
    """The request `recorded` was asked with, as the verb's request model reads it.

    Returns:
        Its fields, by name.
    """
    found: dict[str, object] = json.loads(recorded.request)
    return found


def close(conn: sqlite3.Connection, recorded_id: int, status: RecordedStatus, *, run_id: int | None = None) -> bool:
    """Close recorded run `recorded_id` as `status`, with the run it started as. Nothing changes for one closed.

    Returns:
        True if this call closed it.
    """
    update = (
        records.update(records.RecordedRun)
        .set(status=status, run_id=run_id, closed_at=db.now())
        .where("id = ? AND status = ?", recorded_id, RecordedStatus.RECORDED)
    )
    return update.run(conn).rowcount == 1


def close_unstarted(conn: sqlite3.Connection, *, tick_id: int | None = None) -> int:
    """Close as `unstarted` every recorded run of tick `tick_id` not spawned, or with None, of every tick.

    A run its tick did not spawn is never spawned by a later one, which decides again from what it reads.

    Returns:
        How many it closed.
    """
    update = (
        records.update(records.RecordedRun)
        .set(status=RecordedStatus.UNSTARTED, closed_at=db.now())
        .where("status = ?", RecordedStatus.RECORDED)
    )
    if tick_id is not None:
        update = update.where("tick_id = ?", tick_id)
    return update.run(conn).rowcount
