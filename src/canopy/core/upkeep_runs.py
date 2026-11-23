"""The pools' upkeep the journal records (DESIGN §26): git's maintenance in a primary clone, and `pools.idle_cmd`.

A live tick reads here when each is next due, and raises `upkeep_failed` for each whose newest run failed; `canopy gc
--git` records its runs here too, so the loop's next one waits its hours after a pass by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db, records, sql
from canopy.core.vocab import UpkeepKind, UpkeepStatus

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime


def record(
    conn: sqlite3.Connection,
    *,
    tick_id: int | None,
    kind: UpkeepKind,
    repo: str,
    slot_path: str | None,
    started_at: datetime,
    status: UpkeepStatus,
    detail: str,
) -> int:
    """Record a run of `kind` that started at `started_at` and ends now.

    Returns:
        The run's id.
    """
    statement = records.insert(
        records.UpkeepRun,
        tick_id=tick_id,
        kind=kind,
        repo=repo,
        slot_path=slot_path,
        started_at=db.format_time(started_at),
        ended_at=db.now(),
        status=status,
        detail=detail,
    ).returning("id")
    [run_id] = records.fetch_values(conn, int, statement)
    return run_id


def latest(
    conn: sqlite3.Connection,
    kind: UpkeepKind,
    repo: str,
    slot_path: str | None = None,
) -> records.UpkeepRun | None:
    """The newest run of `kind` in `repo`'s primary clone, or in its slot at `slot_path`.

    Returns:
        The run, or None before the first.
    """
    query = records.select(records.UpkeepRun).where("kind = ?", kind).where("repo = ?", repo)
    query = query.where("slot_path IS NULL") if slot_path is None else query.where("slot_path = ?", slot_path)
    return query.order_by("id DESC").limit(1).one(conn)


def failed(conn: sqlite3.Connection) -> list[records.UpkeepRun]:
    """Each clone's and slot's newest run, of each kind, where that run failed.

    Returns:
        The runs, oldest first.
    """
    return (
        records.select(records.UpkeepRun)
        .where("id IN (SELECT MAX(id) FROM upkeep_runs GROUP BY kind, repo, slot_path)")
        .where("status = ?", UpkeepStatus.FAILED)
        .order_by("id")
        .all(conn)
    )


@dataclass(frozen=True)
class LastLeased(records.View):
    """When the journal last saw a slot leased: the end of the newest lease recorded on it, or its start while open."""

    slot_path: str
    at: str


def last_leased(conn: sqlite3.Connection) -> dict[str, str]:
    """When each slot a run, task run, review, or epic's plan run leased was last leased, by its path.

    A lease canopy did not make, such as the operator's own `treehouse get`, is not recorded; the caller checks that a
    slot is not leased now.

    Returns:
        The journal's time of each slot's newest lease's end, or of its start while it has not ended.
    """
    leases = sql.union(
        sql.select("s.slot_path AS slot_path, COALESCE(r.ended_at, r.started_at) AS at")
        .from_("run_slots s")
        .join("runs r ON r.id = s.run_id"),
        sql.select("slot_path, COALESCE(ended_at, started_at)").from_("task_runs"),
        sql.select("slot_path, COALESCE(ended_at, started_at)").from_("review_runs").where("slot_path IS NOT NULL"),
        sql.select("s.slot_path, COALESCE(r.ended_at, r.started_at)")
        .from_("epic_run_slots s")
        .join("epic_runs r ON r.id = s.run_id"),
        every=True,
    )
    query = sql.select("slot_path, MAX(at) AS at").from_("({}) AS u", leases).group_by("slot_path")
    return {found.slot_path: found.at for found in records.fetch_all(conn, LastLeased, query)}
