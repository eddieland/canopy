"""The passes of garbage collection the journal records (DESIGN §26), and what they removed.

The loop's pass records itself here once a day; the web UI reads here whether a run's or a tick's missing file went by
retention, so a page says "removed after N days" rather than that the file is gone for no reason it knows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, assert_never

from canopy.core import db, records, sql
from canopy.core.vocab import GcPassStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from datetime import datetime

#: Which retention keeps a row's files: a run's, which a chore run, a review, and a tick not `ok` share, or an `ok`
#: tick's (DESIGN §26).
type Rule = Literal["run_files_days", "tick_files_days"]


@dataclass(frozen=True)
class Removed:
    """What a pass removed of one kind: how many, and their bytes."""

    count: int
    bytes: int
    #: What `count` counts: files, or the journal's rows.
    unit: Literal["files", "rows"] = "files"


def record(
    conn: sqlite3.Connection,
    *,
    tick_id: int | None,
    started_at: datetime,
    run_files_days: int,
    tick_files_days: int,
    run_cutoff: str | None,
    tick_cutoff: str | None,
    removed: Mapping[str, Removed],
    failures: int,
    error: str | None,
) -> int:
    """Record a pass that started at `started_at` and ends now, `failed` when `error` says what it raised.

    `removed` is kept as a JSON object, each kind's count under its unit: `{"files": n, "bytes": b}`, or
    `{"rows": n, "bytes": b}`.

    Returns:
        The pass's id.
    """
    status = GcPassStatus.OK if error is None else GcPassStatus.FAILED
    counted = {kind: {r.unit: r.count, "bytes": r.bytes} for kind, r in removed.items()}
    statement = records.insert(
        records.GcPass,
        tick_id=tick_id,
        started_at=db.format_time(started_at),
        ended_at=db.now(),
        status=status,
        run_files_days=run_files_days,
        tick_files_days=tick_files_days,
        run_cutoff=run_cutoff,
        tick_cutoff=tick_cutoff,
        removed=json.dumps(counted, sort_keys=True),
        failures=failures,
        error=error,
    ).returning("id")
    return int(statement.run(conn).fetchone()[0])


def latest(conn: sqlite3.Connection) -> records.GcPass | None:
    """The newest pass, whatever its status.

    Returns:
        The pass, or None before the first.
    """
    return records.select(records.GcPass).order_by("id DESC").limit(1).one(conn)


def removed_after(conn: sqlite3.Connection, ended_at: str | None, rule: Rule) -> int | None:
    """How many days `rule` kept the files of a row that ended at `ended_at`, if a pass has since passed its end.

    Only the caller knows the file is gone: a pass whose cutoff is after the row's end removed it, or would have.

    Returns:
        The days of the first such pass, or None while the row has not ended, or no pass has reached its end.
    """
    if ended_at is None:
        return None
    match rule:
        case "run_files_days":
            query = sql.select("run_files_days").from_("gc_passes").where("run_cutoff > ?", ended_at)
        case "tick_files_days":
            query = sql.select("tick_files_days").from_("gc_passes").where("tick_cutoff > ?", ended_at)
        case _:
            assert_never(rule)
    found = sql.execute(conn, query.order_by("id").limit(1)).fetchone()
    return int(found[0]) if found is not None else None
