"""The connectors' runs (DESIGN §30): recorded, raised as `connector_failed`, shown by `canopy status`.

A run is recorded in `connector_runs` whatever it read, a tick's or the loop's poll between ticks (DESIGN §6). A tick's
run that did not read everything it was asked raises the harness's `connector_failed` that tick, named in its detail;
the cause is gone at the first tick whose run reads everything. A poll raises nothing: the attention list is a tick's,
and the next tick runs the source again. An observation's age is read from its own row, so a subject a run did not
read whole keeps the age of the read that did.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast

from canopy.core import db, records, sql
from canopy.core.vocab import ConnectorRunStatus, SourceKind

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection

    from canopy.core.config import Config, Source
    from canopy.core.observe import Observed, Request

#: The attention reason a source's run that read less than it was asked raises (DESIGN §14, §30): the harness's.
FAILED_REASON = "connector_failed"


#: A table of what a connector observed.
type _Observed = Literal["observed_tickets", "observed_prs"]
#: The column naming each of its rows' subject.
type _Subject = Literal["key", "url"]


def record(
    conn: sqlite3.Connection,
    tick_id: int | None,
    *,
    name: str,
    source: Source,
    request: Request,
    observed: Observed,
) -> int:
    """Record one run of source `name` that tick `tick_id` made, or the loop's poll when `tick_id` is None.

    Returns:
        The run's id.
    """
    with db.transaction(conn):
        cur = sql.execute(
            conn,
            sql.insert(
                "connector_runs",
                tick_id=tick_id,
                source=name,
                kind=SourceKind(source.kind),
                started_at=observed.started_at,
                ended_at=observed.ended_at,
                status=observed.status,
                request=json.dumps(request.to_json()),
                recorded=json.dumps(dict(sorted(observed.recorded.items()))),
                refused=json.dumps(dict(sorted(observed.refused.items()))),
                missed=observed.missed,
                stderr=observed.stderr,
                query_result=None if observed.query_result is None else json.dumps(list(observed.query_result)),
                review_query_result=(
                    None if observed.review_query_result is None else json.dumps(list(observed.review_query_result))
                ),
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
        sql.select("*")
        .from_("connector_runs")
        .where("tick_id = ?", tick_id)
        .where("status != ?", ConnectorRunStatus.OK)
        .order_by("source, id"),
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
            sql.select("*").from_("connector_runs").where("source = ?", name).order_by("id DESC").limit(1),
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
    observed: tuple[tuple[_Observed, _Subject, list[str]], ...] = (
        ("observed_tickets", "key", tickets),
        ("observed_prs", "url", prs),
    )
    for table, column, subjects in observed:
        seen = _observed_at(conn, table, column, subjects)
        times.extend(seen.values())
        never += sum(subject not in seen for subject in subjects)
    return times, never


def _observed_at(
    conn: sqlite3.Connection,
    table: _Observed,
    column: _Subject,
    subjects: Collection[str],
) -> dict[str, str]:
    if not subjects:
        return {}
    rows = sql.execute(
        conn,
        sql.select("{}, observed_at", sql.name(column))
        .from_(table)
        .where("{} IN (SELECT value FROM json_each(?))", sql.name(column), json.dumps(sorted(subjects))),
    )
    return {str(r[0]): str(r[1]) for r in rows}
