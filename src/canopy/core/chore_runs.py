"""Chore runs (DESIGN §19): each run of a chore, what it cost, and the findings the operator dismissed.

A chore run's lifecycle, from its claim to its close, is the one every run table shares (`db.claim_run`,
`db.finish_run`); what is here is the chore's own: its runs as a chore reads them, and the operator's dismissals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, records, sql

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path


def insert_chore_run(
    conn: sqlite3.Connection,
    *,
    tick_id: int | None,
    chore: str,
    logs_dir: Path,
    model: str | None = None,
) -> int:
    """Insert a `running` chore run with no pid yet, logging to `<logs_dir>/<id>.log`, and return its id.

    `tick_id` is the tick whose overseer started the run, or None for one the operator started with `canopy chore try`.
    `model` is the one its agent asks for (DESIGN §13), None for the runtime's default or the operator's own agent's.

    Returns:
        The new chore run's id.
    """
    with db.transaction(conn):
        run = records.insert(
            records.ChoreRun,
            tick_id=tick_id,
            chore=chore,
            started_at=db.now(),
            log_path="",
            model=model,
        )
        run_id = db.rowid(run.run(conn))
        log_path = str(logs_dir / f"{run_id}.log")
        records.update(records.ChoreRun).set(log_path=log_path).where("id = ?", run_id).run(conn)
    return run_id


def get_chore_run(conn: sqlite3.Connection, run_id: int) -> records.ChoreRun | None:
    """Return the chore run with `run_id`, or None."""
    return records.select(records.ChoreRun).where("id = ?", run_id).one(conn)


def chore_runs(
    conn: sqlite3.Connection,
    chore: str,
    limit: int = 1000,
    *,
    before: int | None = None,
) -> list[records.ChoreRun]:
    """Return `chore`'s runs, newest first: at most `limit`, and only those before run id `before` if it is given."""
    return (
        records.select(records.ChoreRun)
        .where("chore = ? AND id < ?", chore, before if before is not None else 2**63 - 1)
        .order_by("id DESC")
        .limit(limit)
        .all(conn)
    )


def chore_costs_since(conn: sqlite3.Connection, chore: str, since: str) -> tuple[int, list[float]]:
    """How many of `chore`'s runs started at or after `since`, and what each of those that reported a cost cost (§13).

    Returns:
        The runs, a running one included, and the costs reported, in US dollars, cheapest first.
    """
    query = sql.select("cost_usd").from_("chore_runs").where("chore = ? AND started_at >= ?", chore, since)
    rows = sql.execute(conn, query).fetchall()
    return len(rows), sorted(float(r[0]) for r in rows if r[0] is not None)


def dismissals(conn: sqlite3.Connection, chore: str) -> dict[str, str]:
    """Return when the operator dismissed each of `chore`'s findings it dismissed, by finding id (DESIGN §19)."""
    query = sql.select("finding_id, dismissed_at").from_("finding_dismissals").where("chore = ?", chore)
    return {str(r["finding_id"]): str(r["dismissed_at"]) for r in sql.execute(conn, query)}


def set_dismissal(conn: sqlite3.Connection, chore: str, finding_id: str, *, channel: str) -> None:
    """Record that the operator dismissed `chore`'s finding `finding_id` now, replacing an earlier dismissal of it."""
    records.insert(
        records.FindingDismissal,
        chore=chore,
        finding_id=finding_id,
        dismissed_at=db.now(),
        channel=channel,
    ).on_conflict(
        "(chore, finding_id) DO UPDATE SET dismissed_at = excluded.dismissed_at, channel = excluded.channel",
    ).run(conn)


def delete_dismissal(conn: sqlite3.Connection, chore: str, finding_id: str) -> bool:
    """Take back the operator's dismissal of `chore`'s finding `finding_id`.

    Returns:
        Whether there was one to take back.
    """
    taken = records.delete(records.FindingDismissal).where("chore = ? AND finding_id = ?", chore, finding_id)
    return taken.run(conn).rowcount > 0
