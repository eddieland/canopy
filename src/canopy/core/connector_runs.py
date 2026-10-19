"""Each tick's runs of the connectors (DESIGN §30): recorded, raised as `connector_failed`, shown by `canopy status`.

A run is recorded in `connector_runs` whatever it read. One that did not read everything it was asked raises the
harness's `connector_failed` that tick, about the source and named in its detail; the cause is gone at the first run
that reads everything. An observation's age is read from its own row, so a subject a run did not read whole keeps the
age of the read that did.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast

from canopy.core import db, records
from canopy.core.vocab import ConnectorRunStatus, SourceKind

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection

    from canopy.core.config import Config, Source
    from canopy.core.observe import Observed, Request

#: The attention reason a source's run that read less than it was asked raises (DESIGN §14, §30): the harness's.
FAILED_REASON = "connector_failed"


def record(
    conn: sqlite3.Connection, tick_id: int, *, name: str, source: Source, request: Request, observed: Observed
) -> int:
    """Record one run of source `name` that tick `tick_id` made.

    Returns:
        The run's id.
    """
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, "
            "refused, missed, stderr, query_result, review_query_result) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tick_id,
                name,
                SourceKind(source.kind),
                observed.started_at,
                observed.ended_at,
                observed.status,
                json.dumps(request.to_json()),
                json.dumps(dict(sorted(observed.recorded.items()))),
                json.dumps(dict(sorted(observed.refused.items()))),
                observed.missed,
                observed.stderr,
                None if observed.query_result is None else json.dumps(list(observed.query_result)),
                None if observed.review_query_result is None else json.dumps(list(observed.review_query_result)),
            ),
        )
    return int(cur.lastrowid or 0)


@dataclass(frozen=True)
class Failure:
    """One `connector_failed` item: the source's name and kind, and the detail that says what it did not read."""

    source: str
    kind: SourceKind
    detail: str


def failures(conn: sqlite3.Connection, tick_id: int) -> list[Failure]:
    """The runs tick `tick_id` made that did not read everything they were asked, by source.

    Returns:
        A failure for each such run, its detail naming the source and what it missed, with the tail of its stderr.
    """
    rows = records.fetch_all(
        conn,
        records.ConnectorRun,
        "SELECT * FROM connector_runs WHERE tick_id = ? AND status != ? ORDER BY source, id",
        (tick_id, ConnectorRunStatus.OK),
    )
    found: list[Failure] = []
    for run in rows:
        detail = f"{run.source} ({run.kind}) {run.status}: {run.missed}"
        if run.stderr and run.stderr not in (run.missed or ""):
            detail += f"; it said: {run.stderr}"
        found.append(Failure(run.source, run.kind, detail))
    return found


@dataclass(frozen=True)
class SourceStatus:
    """A source as `canopy status` names it: its latest run, and the oldest observation of what that run asked about."""

    name: str
    kind: SourceKind
    latest: records.ConnectorRun | None
    #: When the oldest observation of a subject the latest run asked about was made; None when there is none.
    oldest: str | None
    #: How many subjects the latest run asked about have never been observed.
    never: int
    stale: bool


def statuses(conn: sqlite3.Connection, config: Config, now: datetime) -> list[SourceStatus]:
    """Each source that reads, in the order a tick runs them, with its latest run and the age of its observations.

    An observation is stale once it is older than `connect.max_age_minutes`, and so is a subject never observed.

    Returns:
        One status per source.
    """
    found: list[SourceStatus] = []
    cutoff = now - timedelta(minutes=config.connect.max_age_minutes)
    for name, source in config.connect.named().items():
        latest = records.fetch_one(
            conn,
            records.ConnectorRun,
            "SELECT * FROM connector_runs WHERE source = ? ORDER BY id DESC LIMIT 1",
            (name,),
        )
        times, never = _ages(conn, None if latest is None else latest.request)
        oldest = min(times) if times else None
        stale = never > 0 or (oldest is not None and db.parse_time(oldest) < cutoff)
        found.append(SourceStatus(name, SourceKind(source.kind), latest, oldest, never, stale))
    return found


def _ages(conn: sqlite3.Connection, request: str | None) -> tuple[list[str], int]:
    """When each ticket and PR a recorded request named was last observed, and how many never were.

    A repository's branches are left out: a repository with none has no row to date.

    Returns:
        The times found, and the count of subjects with none.
    """
    none: list[object] = []
    asked = cast("dict[str, list[object]]", json.loads(request)) if request is not None else {"tickets": none}
    tickets = [str(cast("dict[str, object]", t)["key"]) for t in asked.get("tickets", none) if isinstance(t, dict)]
    prs = [p for p in asked.get("prs", none) if isinstance(p, str)]
    times: list[str] = []
    never = 0
    for table, column, subjects in (("observed_tickets", "key", tickets), ("observed_prs", "url", prs)):
        seen = _observed_at(conn, table, column, subjects)
        times.extend(seen.values())
        never += sum(subject not in seen for subject in subjects)
    return times, never


def _observed_at(conn: sqlite3.Connection, table: str, column: str, subjects: Collection[str]) -> dict[str, str]:
    if not subjects:
        return {}
    rows = conn.execute(
        f"SELECT {column}, observed_at FROM {table} WHERE {column} IN (SELECT value FROM json_each(?))",  # noqa: S608
        (json.dumps(sorted(subjects)),),
    )
    return {str(r[0]): str(r[1]) for r in rows}
