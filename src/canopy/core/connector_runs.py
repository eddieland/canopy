"""The connectors' runs (DESIGN §30): recorded, raised as `connector_failed`, shown by `canopy status`.

A run is recorded in `connector_runs` whatever it read, a tick's or the loop's poll between ticks (DESIGN §6). A tick's
run that did not read everything it was asked raises the harness's `connector_failed` that tick, named in its detail;
the cause is gone at the first tick whose run reads everything. A poll raises nothing: the attention list is a tick's,
and the next tick runs the source again. An observation's age is read from its own row, so a subject a run did not
read whole keeps the age of the read that did.

Beside them, for the web UI's Connectors report, each source's runs over a window of local days, as `canopy health`
reads its window (DESIGN §11): how they ended, a tick's apart from a poll's, how long they took against the source's
timeout, the lines they recorded and canopy refused, each day's that read less than asked, and the newest of those.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, NamedTuple, cast

from canopy.core import db, records, spend, sql
from canopy.core.vocab import ConnectorRunStatus, SourceKind

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable, Mapping, Sequence

    from canopy.core.config import Config, Source
    from canopy.core.observe import Observed, Request

#: The attention reason a source's run that read less than it was asked raises (DESIGN §14, §30): the harness's.
FAILED_REASON = "connector_failed"
#: The newest runs that read less than asked a report lists, across every source.
NEWEST = 20


#: A table of what a connector observed.
type _Observed = Literal["observed_tickets", "observed_prs"]
#: The column naming each of its rows' subject.
type _Subject = Literal["key", "url"]
#: A run's lines by kind: those it recorded, or those canopy refused.
type _Lines = Literal["recorded", "refused"]


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
        cur = records.insert(
            records.ConnectorRun,
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
        ).run(conn)
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
    rows = (
        records.select(records.ConnectorRun)
        .where("tick_id = ?", tick_id)
        .where("status != ?", ConnectorRunStatus.OK)
        .order_by("source, id")
        .all(conn)
    )
    found: list[Failure] = []
    for run in rows:
        detail = f"{run.source} ({run.kind}) {run.status}: {run.missed}"
        if run.stderr and run.stderr not in (run.missed or ""):
            detail += f"; it said: {run.stderr}"
        found.append(Failure(run.source, run.kind, detail))
    return found


def query_result(conn: sqlite3.Connection) -> list[str]:
    """The keys the tracker query returned on the newest run that read it to the end.

    Returns:
        The keys; none when no run has.
    """
    row = sql.execute(
        conn,
        sql.select("query_result")
        .from_("connector_runs")
        .where("query_result IS NOT NULL")
        .order_by("id DESC")
        .limit(1),
    ).fetchone()
    return [str(k) for k in json.loads(str(row[0]))] if row is not None else []


def read_whole(conn: sqlite3.Connection, tick_id: int) -> bool | None:
    """Whether tick `tick_id` read every source whole: what the loop's polls after it go on from (DESIGN §39).

    Returns:
        True when each of its runs read everything it was asked, False when one did not, and None when it ran no
        source: none is configured, or its reconcile failed.
    """
    rows = sql.execute(conn, sql.select("status").from_("connector_runs").where("tick_id = ?", tick_id)).fetchall()
    if not rows:
        return None
    return all(row[0] == ConnectorRunStatus.OK for row in rows)


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
    #: For an `artifacts` source, the feed's cursor: the change it has read through. None for the others.
    through: int | None = None


def statuses(conn: sqlite3.Connection, config: Config, now: datetime) -> list[SourceStatus]:
    """Each source that reads, in the order a tick runs them, with its latest run and the age of its observations.

    An observation is stale once it is older than `connect.max_age_minutes`, and so is a subject never observed. An
    `artifacts` source's one subject is its feed, observed when a run last read it to its end with nothing refused.

    Returns:
        One status per source.
    """
    found: list[SourceStatus] = []
    cutoff = now - timedelta(minutes=config.connect.max_age_minutes)
    for name, source in config.connect.named().items():
        latest = records.select(records.ConnectorRun).where("source = ?", name).order_by("id DESC").limit(1).one(conn)
        kind = SourceKind(source.kind)
        through = None
        if kind is SourceKind.ARTIFACTS:
            feed = records.select(records.ObservedFeed).where("source = ?", name).one(conn)
            through = 0 if feed is None else feed.through
            times: list[str] = [] if feed is None or feed.read_at is None else [feed.read_at]
            never = 0 if times else 1
        else:
            times, never = _ages(conn, None if latest is None else latest.request)
        oldest = min(times) if times else None
        stale = never > 0 or (oldest is not None and db.parse_time(oldest) < cutoff)
        found.append(SourceStatus(name, kind, latest, oldest, never, stale, through))
    return found


@dataclass(frozen=True)
class Lines:
    """One kind of line a source's runs in a window recorded, or canopy refused: how many, in how many runs."""

    source: str
    #: The kind of line, as the connectors' contract names it: `ticket`, `pr`, `comment`.
    line: str
    #: How many lines of it.
    lines: int
    #: In how many runs.
    runs: int
    #: When the latest of those runs started.
    last_at: str


@dataclass(frozen=True)
class SourceRuns:
    """One source's runs that started in a window: how they ended, how long they took, and the lines they read."""

    source: str
    #: The kind of its newest run in the window.
    kind: SourceKind
    #: Its runs.
    runs: int
    #: Of those, the ones a tick made; the rest are the loop's polls between ticks.
    ticks: int
    #: The ones that read everything they were asked.
    ok: int
    #: The ones that ended with their `end` line but read less than asked.
    partial: int
    #: The ones that recorded nothing.
    failed: int
    #: Their median length, in minutes.
    median_minutes: float
    #: The length nine in ten of them came in at or under, by nearest rank, in minutes.
    p90_minutes: float
    #: The longest of them, in minutes.
    longest_minutes: float
    #: The source's `timeout_minutes` as configured now; None for a source no longer configured.
    limit_minutes: int | None
    #: The lines its runs recorded, by kind of line.
    recorded: Mapping[str, int]
    #: The lines canopy refused of its runs, by kind of line.
    refused: Mapping[str, int]

    @property
    def polls(self) -> int:
        """Its runs the loop's polls between ticks made."""
        return self.runs - self.ticks

    @property
    def short(self) -> int:
        """Its runs that read less than they were asked: `partial` and `failed` together."""
        return self.partial + self.failed


@dataclass(frozen=True)
class Day:
    """One local day of a window: each source's runs that started in it and read less than they were asked."""

    #: The day, `YYYY-MM-DD`, as `spend.local_day` names it.
    day: str
    #: When it starts: its local midnight, a journal time.
    start: str
    #: Each source's runs that ended `partial` or `failed`, in `Connectors.sources` order.
    short: Sequence[int]


@dataclass(frozen=True)
class Connectors:
    """The sources' runs that started in a window, `[since, until)`: by source, by day, and the newest short of it."""

    since: str
    until: str
    days: int
    #: A row per source that ran in the window, in the order a tick runs them, then any no longer configured, by name.
    sources: Sequence[SourceRuns] = ()
    #: Every day of the window, oldest first.
    per_day: Sequence[Day] = ()
    #: The newest runs that read less than asked, at most `NEWEST`, the newest first.
    newest: Sequence[records.ConnectorRun] = ()
    #: The kinds of line canopy refused, by source in `sources` order, then the most lines first.
    refusals: Sequence[Lines] = ()

    @property
    def runs(self) -> int:
        """The window's runs, of every source."""
        return sum(s.runs for s in self.sources)

    @property
    def short(self) -> int:
        """Of those, the ones that read less than they were asked."""
        return sum(s.short for s in self.sources)

    @property
    def refused(self) -> int:
        """The lines canopy refused of them."""
        return sum(r.lines for r in self.refusals)


def report(conn: sqlite3.Connection, config: Config, now: datetime, days: int) -> Connectors:
    """The sources' runs of the last `days` local days, today's so far included, by start.

    Returns:
        The report; a window with no run in it has every day, and empty lists.
    """
    return between(conn, config, *spend.window(now, days))


def between(conn: sqlite3.Connection, config: Config, start: datetime, end: datetime) -> Connectors:
    """The sources' runs that started from one local midnight, `start`, to another, `end`.

    Each source is held to its `timeout_minutes` as `config` sets it now.

    Returns:
        The report, as `report` gives it for any such window: the one before a page's among them.
    """
    since = db.format_time(start)
    until = db.format_time(end)
    window = ("started_at >= ? AND started_at < ?", since, until)
    each = (
        sql.select(
            "source, kind, status, tick_id IS NOT NULL, (julianday(ended_at) - julianday(started_at)) * 1440, {}",
            spend.DAY,
        )
        .from_("connector_runs")
        .where(*window)
        .order_by("id")
    )
    with db.read_snapshot(conn):
        ran = [_ran(row) for row in sql.execute(conn, each)]
        recorded = _lines(conn, "recorded", since, until)
        refused = _lines(conn, "refused", since, until)
        newest = (
            records.select(records.ConnectorRun)
            .where(*window)
            .where("status != ?", ConnectorRunStatus.OK)
            .order_by("started_at DESC, id DESC")
            .limit(NEWEST)
            .all(conn)
        )
    configured = config.connect.named()
    names = _ordered({r.source for r in ran}, configured)
    return Connectors(
        since=since,
        until=until,
        days=spend.days_between(start, end),
        sources=[
            _source_runs([r for r in ran if r.source == name], configured.get(name), recorded, refused)
            for name in names
        ],
        per_day=_per_day(ran, names, start, end),
        newest=newest,
        refusals=[r for name in names for r in sorted(refused.get(name, ()), key=lambda r: (-r.lines, r.line))],
    )


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


class _Ran(NamedTuple):
    """One run of a window, as `between` reads it."""

    source: str
    kind: SourceKind
    status: ConnectorRunStatus
    #: Whether a tick made it, rather than a poll.
    by_tick: bool
    #: Its length, in minutes; a clock that went back reads 0.
    minutes: float
    #: The local day it started on, as `spend.local_day` names it.
    day: str


# A row of `between`'s read: source, kind, status, whether a tick made it, its length in minutes, and its local day.
def _ran(row: Sequence[object]) -> _Ran:
    source, kind, status, by_tick, minutes, day = row
    return _Ran(
        source=str(source),
        kind=SourceKind(str(kind)),
        status=ConnectorRunStatus(str(status)),
        by_tick=bool(by_tick),
        minutes=max(float(minutes) if isinstance(minutes, (int, float)) else 0.0, 0.0),
        day=str(day),
    )


# The sources that ran, in the order a tick runs those configured, then those no longer configured, by name.
def _ordered(ran: Collection[str], configured: Mapping[str, Source]) -> list[str]:
    return [name for name in configured if name in ran] + sorted(name for name in ran if name not in configured)


# One source's row, from its runs of the window, oldest first, and every source's lines by kind.
def _source_runs(
    ran: Sequence[_Ran],
    source: Source | None,
    recorded: Mapping[str, Sequence[Lines]],
    refused: Mapping[str, Sequence[Lines]],
) -> SourceRuns:
    name = ran[-1].source
    statuses = Counter(r.status for r in ran)
    minutes = sorted(r.minutes for r in ran)
    return SourceRuns(
        source=name,
        kind=ran[-1].kind,
        runs=len(ran),
        ticks=sum(r.by_tick for r in ran),
        ok=statuses[ConnectorRunStatus.OK],
        partial=statuses[ConnectorRunStatus.PARTIAL],
        failed=statuses[ConnectorRunStatus.FAILED],
        median_minutes=statistics.median(minutes),
        p90_minutes=minutes[math.ceil(0.9 * len(minutes)) - 1],
        longest_minutes=minutes[-1],
        limit_minutes=None if source is None else source.timeout_minutes,
        recorded={r.line: r.lines for r in recorded.get(name, ())},
        refused={r.line: r.lines for r in refused.get(name, ())},
    )


# Every day of the window, oldest first, with each source's runs that started in it and read less than asked.
def _per_day(ran: Iterable[_Ran], names: Sequence[str], start: datetime, end: datetime) -> list[Day]:
    starts = spend.day_starts(start, spend.days_between(start, end))
    short = {day: [0] * len(names) for day in starts}
    for run in ran:
        # A day the clock puts outside the window's names is in none of them, as `spend` leaves it.
        if run.status is not ConnectorRunStatus.OK and run.day in short:
            short[run.day][names.index(run.source)] += 1
    return [Day(day=day, start=at, short=short[day]) for day, at in starts.items()]


# The lines the window's runs recorded, or canopy refused, by source, each kind with its lines, the runs that had any,
# and when the latest of those started.
def _lines(conn: sqlite3.Connection, column: _Lines, since: str, until: str) -> dict[str, list[Lines]]:
    summed = (
        sql.select("r.source, j.key, sum(j.value), count(DISTINCT r.id), max(r.started_at)")
        .from_("connector_runs AS r, json_each(r.{}) AS j", sql.name(column))
        .where("r.started_at >= ? AND r.started_at < ?", since, until)
        .where("j.value > 0")
        .group_by("r.source, j.key")
    )
    found: dict[str, list[Lines]] = {}
    for source, line, lines, runs, last in sql.execute(conn, summed):
        found.setdefault(str(source), []).append(Lines(str(source), str(line), int(lines), int(runs), str(last)))
    return found
