"""What agent runs cost, by what they bought (DESIGN §11; ROADMAP M33), read by `canopy spend` and the web UI.

Reads only. Every cost is what the agent runtime reported (§13), summed by the local day a run started on, or by the
local hour for a window in hours: the overseer of each tick, worker runs (old split runs among them), plan runs (§25,
old triage runs before a plan among them), chore runs, and review runs. A dry run's overseer is kept apart from the live
ones', and idle ticks' (§6, Idle pacing) are a series of their own within the live overseer's. Beside what the window
cost, what it got done: the tickets marked done in it, and what each ticket and PR's own runs cost.
And what each kind of run's first model call was sent, by the definitions snapshot it loaded: its fixed overhead, and
how often it started cold. And what each kind's tool calls put into its context, by tool: the reads that each later
model call reads again.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Literal, LiteralString

from canopy.core import contract, db, records, sql
from canopy.core.vocab import RunKind

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

type Group = Literal["idle", "busy", "hand_run", "not_ok", "dry_run"]
type Kind = Literal["overseer", "workers", "plans", "chores", "reviews"]
type Done = Literal["merged", "closed"]
#: A table of agent runs, each with a `started_at` and a `cost_usd`: the overseer's ticks, and the others'.
type _Table = Literal["ticks", "runs", "chore_runs", "review_runs"]

# Every tick that ended is in exactly one group, in this order: a dry run first, whatever the loop said of it, then a
# live tick that did not close `ok`, then the loop's word on an `ok` one, idle or not, and last a tick no loop ran. A
# tick from before migration 0013 has no word from the loop either, so it reads as hand-run: nothing can tell.
GROUPS: tuple[Group, ...] = ("idle", "busy", "hand_run", "not_ok", "dry_run")
KINDS: tuple[Kind, ...] = ("overseer", "workers", "plans", "chores", "reviews")
# The longest window `canopy spend` and the web UI read, in days; a year keeps the per-day lines bounded.
MAX_DAYS = 366
DEFAULT_DAYS = 7
# The longest window in hours the web UI reads: a week, by the hour.
MAX_HOURS = 7 * 24
# The idle ticks the web UI links to: the newest in the window.
IDLE_TICKS = 20

# Each kind of agent run but the overseer's, by its table and which of the table's rows it counts: a plan run (§25), an
# old triage before a plan among them (M55), is a row of `runs`, a kind of its own, and every other row there a
# worker's, an old split's among them. Then every kind, the overseer's ticks included. The tables and conditions are
# fixed, never input (D125).
_PLANS = sql.in_("kind", (RunKind.PLAN, RunKind.NEEDS_PLAN))
_EVERY = sql.frag("1")
_TABLES: Mapping[Kind, tuple[_Table, sql.Fragment]] = {
    "workers": ("runs", sql.frag("NOT ({})", _PLANS)),
    "plans": ("runs", _PLANS),
    "chores": ("chore_runs", _EVERY),
    "reviews": ("review_runs", _EVERY),
}
_ALL_TABLES: Mapping[Kind, tuple[_Table, sql.Fragment]] = {"overseer": ("ticks", _EVERY), **_TABLES}
# About how many characters make a token: what a tool's result is counted in, as an estimate of its tokens.
CHARS_PER_TOKEN = 4
# The overseer's series, each from the ticks.
_SERIES = ("overseer", "idle", "dry_run")
# What a run's row says of its first model call, and when it started.
_FIRST_CALL: LiteralString = "definitions_digest, tokens_first_call, tokens_first_cache_write, started_at"
# The local day a row started on, as `YYYY-MM-DD`: SQLite reads the journal's UTC time in the local time Python does.
_DAY = sql.frag("date(started_at, 'localtime')")
# The local hour a row started on, as `YYYY-MM-DDTHH`, read the same way.
_HOUR_FORMAT = "%Y-%m-%dT%H"
_HOUR = sql.frag("strftime(?, started_at, 'localtime')", _HOUR_FORMAT)


@dataclass(frozen=True)
class Costs:
    """What each kind of agent run cost, in US dollars; None for a kind none of whose runs reported a cost.

    `overseer` is the live ticks' overseers, `idle` the part of it idle ticks spent, and `dry_run` the dry runs'
    overseers, apart from it.
    """

    overseer: float | None = None
    idle: float | None = None
    dry_run: float | None = None
    workers: float | None = None
    plans: float | None = None
    chores: float | None = None
    reviews: float | None = None

    @property
    def total(self) -> float | None:
        """Everything, dry runs included, as the web UI's 24 hour and 30 day counters count it; None when none did."""
        return _sum([self.overseer, self.dry_run, self.workers, self.plans, self.chores, self.reviews])


@dataclass(frozen=True)
class Day:
    """One local day's costs, `day` as `YYYY-MM-DD`, and how many tickets were marked done on it.

    In a window in hours it is one local hour's, `day` as `YYYY-MM-DDTHH`. `start` is when it starts, a journal time:
    the day's local midnight, or the hour's start, the first of an hour the clock goes back over.
    """

    day: str
    start: str
    costs: Costs
    done: int = 0


@dataclass(frozen=True)
class TickGroup:
    """How many ended ticks of the window are in a group, and what their overseers cost."""

    group: Group
    ticks: int
    cost_usd: float | None


@dataclass(frozen=True)
class Woken:
    """How many of the loop's ticks one cause woke (`ticks.woken_by`, §6), and what their overseers cost."""

    by: str
    ticks: int
    cost_usd: float | None


@dataclass(frozen=True)
class Unpriced:
    """How many of a kind's ended runs in the window reported no cost, of how many."""

    kind: Kind
    runs: int
    unpriced: int


@dataclass(frozen=True)
class TicketSpend:
    """What one ticket's runs that started in the window cost, and whether it was marked done in the window.

    `runs` counts its worker runs, `reviews` the review runs naming it, running ones included; `done` is how
    the loop marked it done (`merged`, or `closed` in the tracker, §7) and `done_at` when, both None when it was not
    marked done in the window. Not the overseer's: a tick decides for the whole workspace, so its cost is no ticket's.
    """

    key: str
    title: str | None
    runs: int
    reviews: int
    cost_usd: float | None
    done: Done | None = None
    done_at: str | None = None


@dataclass(frozen=True)
class PullRequestSpend:
    """What the runs that pushed to one PR and the review runs of it, started in the window, cost.

    `ticket` owns it: its unit's, else the ticket a run or a review named; None for a PR canopy only reviewed. `phase`
    is its unit's (§7), None for a PR no unit has. A run that pushed to two PRs counts on each.
    """

    url: str
    ticket: str | None
    phase: str | None
    runs: int
    reviews: int
    cost_usd: float | None


@dataclass(frozen=True)
class FirstCalls:
    """The first model calls of one kind's runs that loaded one definitions snapshot and started in the window (§13).

    `runs` counts those that reported a first call; `first_call` is the median of what it was sent, from the cache or
    not, the lower middle one of an even count; `cold_share` the share of them that started cold, their first call
    writing more than half of what it was sent to the cache. `first_started` and `last_started` are when the first and
    the last of them started. `digest` is None for runs that reported a first call and no snapshot.
    """

    kind: Kind
    digest: str | None
    runs: int
    first_call: int
    cold_share: float
    first_started: str
    last_started: str


@dataclass(frozen=True)
class ToolSpend:
    """What one tool's calls in one kind's runs that started in the window put into their context (§13).

    `runs` counts the runs that called it, `calls` its calls that ended, and `errors` those that ended in an error.
    `result_chars` is the characters they returned, output or error, and `est_tokens` those over `CHARS_PER_TOKEN`: an
    estimate, since the runtime does not say which of a model call's tokens a tool's result was. Each later model call
    of the run reads them again, from the cache or not.
    """

    kind: Kind
    tool: str
    runs: int
    calls: int
    errors: int
    result_chars: int
    est_tokens: int


@dataclass(frozen=True)
class Breakdown:
    """The window's spend: per day, oldest first, every day in it listed; in total; and by what the ticks bought.

    The window is `[since, until)`, each a journal time: local midnight on its first day, and after its last. A window
    in `hours` has `days` None and lists each hour in `per_day`, from its first hour's start to the end of its last.
    What it got done is `done`, the tickets marked done in it, and `per_done`, its whole spend over them: the overseer,
    chores, and the runs of tickets still open are what it cost to get those done. `tickets` and `pull_requests` list
    what each one's own runs cost, the most first. `first_calls` is each kind's first model calls by snapshot, the
    kinds in `KINDS` order and each kind's snapshots by when their first run started; the overseer's include dry runs,
    whose first call is a live tick's. `tools` is what each kind's tool calls returned, by tool, the most characters
    first; the overseer's include dry runs too.
    """

    since: str
    until: str
    days: int | None
    per_day: Sequence[Day]
    totals: Costs
    ticks: Sequence[TickGroup]
    woken: Sequence[Woken]
    unpriced: Sequence[Unpriced]
    idle_share: float | None = None
    done: int = 0
    per_done: float | None = None
    tickets: Sequence[TicketSpend] = ()
    pull_requests: Sequence[PullRequestSpend] = ()
    first_calls: Sequence[FirstCalls] = ()
    tools: Sequence[ToolSpend] = ()
    hours: int | None = None


def window(now: datetime, days: int) -> tuple[datetime, datetime]:
    """The window `[start, until)`: `days` whole days of this machine's local time, ending with `now`'s day.

    A day is from one local midnight to the next, so a day that a clock change shortens or lengthens is still one day.

    Returns:
        Its start and its end, each an aware UTC datetime.
    """
    today = now.astimezone().date()
    return _midnight(today - timedelta(days=days - 1)), _midnight(today + timedelta(days=1))


# A day's local midnight. A naive time's `astimezone` reads it in this machine's local time, with its own DST rules.
def _midnight(day: date) -> datetime:
    return datetime.combine(day, time()).astimezone().astimezone(UTC)


def hour_window(now: datetime, hours: int) -> tuple[datetime, datetime]:
    """The window `[start, until)`: `hours` whole local clock hours, ending with `now`'s.

    Floored on this machine's clock, not UTC's, so in a zone a half hour off UTC each hour is still the one its runs
    are summed by.

    Returns:
        Its start and its end, each an aware UTC datetime.
    """
    this_hour = now.astimezone().replace(minute=0, second=0, microsecond=0).astimezone(UTC)
    return this_hour - timedelta(hours=hours - 1), this_hour + timedelta(hours=1)


def breakdown(conn: sqlite3.Connection, now: datetime, days: int) -> Breakdown:
    """What the last `days` local days cost, today's so far included, by day, by kind, and by what the ticks bought.

    Returns:
        The breakdown; a window with nothing in it lists each day with no costs.
    """
    start, end = window(now, days)
    first = start.astimezone().date()
    each = [first + timedelta(days=i) for i in range(days)]
    starts = {day.isoformat(): db.format_time(_midnight(day)) for day in each}
    return _breakdown(conn, start, end, _Buckets(expression=_DAY, starts=starts, name_of=local_day), days=days)


def breakdown_hours(conn: sqlite3.Connection, now: datetime, hours: int) -> Breakdown:
    """What the last `hours` clock hours cost, the current one's so far included, by local hour, as `breakdown` does.

    An hour the clock goes back over is one local hour twice, so the window lists it once, with both in it.

    Returns:
        The breakdown; a window with nothing in it lists each hour with no costs.
    """
    start, end = hour_window(now, hours)
    starts: dict[str, str] = {}
    for at in (start + timedelta(hours=i) for i in range(hours)):
        starts.setdefault(_local_hour(at), db.format_time(at))
    buckets = _Buckets(expression=_HOUR, starts=starts, name_of=lambda stamp: _local_hour(db.parse_time(stamp)))
    return _breakdown(conn, start, end, buckets, hours=hours)


@dataclass(frozen=True)
class _Buckets:
    """What a window sums its costs by: its days, or its hours."""

    #: The SQL that names the bucket a row started in, from its `started_at`.
    expression: sql.Fragment
    #: Every bucket's name, oldest first, and when it starts, a journal time.
    starts: Mapping[str, str]
    #: The name of the bucket a journal time is in.
    name_of: Callable[[str], str]


def _local_hour(at: datetime) -> str:
    return at.astimezone().strftime(_HOUR_FORMAT)


def _breakdown(
    conn: sqlite3.Connection,
    start: datetime,
    end: datetime,
    buckets: _Buckets,
    *,
    days: int | None = None,
    hours: int | None = None,
) -> Breakdown:
    since = db.format_time(start)
    # Bounded at the window's end too, so a row the clock puts after today is in no figure rather than in some.
    until = db.format_time(end)
    # One read transaction, so a run or tick ending between two of the reads is in all of them or none.
    with db.read_snapshot(conn):
        rows = _tick_rows(conn, since, until, buckets.expression)
        by_day: dict[str, dict[str, float | None]] = {}
        for kind, (table, which) in _TABLES.items():
            costs = (
                sql.select("{} AS day, SUM(cost_usd)", buckets.expression)
                .from_(table)
                .where("{}", which)
                .where("started_at >= ? AND started_at < ?", since, until)
                .group_by("day")
            )
            for day, cost in sql.execute(conn, costs):
                by_day.setdefault(str(day), {})[kind] = cost
        unpriced = _unpriced(conn, since, until, rows)
        done = _done(conn, since, until)
        tickets = _tickets(conn, since, until, done)
        pull_requests = _pull_requests(conn, since, until)
        first_calls = _first_calls(conn, since, until)
        tools = _tools(conn, since, until)
    for row in rows:
        day = by_day.setdefault(row.day, {})
        for name in _SERIES:
            if _in_series(row, name):
                day[name] = _sum([day.get(name), row.cost_usd])
    starts = buckets.starts
    done_on = Counter(buckets.name_of(at) for _, at in done.values())
    per_day = [Day(day=d, start=s, costs=_costs(by_day.get(d, {})), done=done_on[d]) for d, s in starts.items()]
    totals = _costs({n: _sum([by_day.get(d, {}).get(n) for d in starts]) for n in (*_SERIES, *_TABLES)})
    ticks = _groups(rows)
    total = totals.total
    return Breakdown(
        since=since,
        until=until,
        days=days,
        per_day=per_day,
        totals=totals,
        ticks=ticks,
        woken=_woken(rows),
        unpriced=unpriced,
        idle_share=_idle_share(ticks),
        done=len(done),
        per_done=total / len(done) if done and total is not None else None,
        tickets=tickets,
        pull_requests=pull_requests,
        first_calls=first_calls,
        tools=tools,
        hours=hours,
    )


def local_day(stamp: str) -> str:
    """The local day a journal time is on, as the window's days are named.

    Returns:
        The day, `YYYY-MM-DD`.
    """
    return db.parse_time(stamp).astimezone().date().isoformat()


def idle_ticks(
    conn: sqlite3.Connection, since: str, until: str, limit: int = IDLE_TICKS
) -> list[tuple[records.Tick, int]]:
    """The newest live idle ticks that started in `[since, until)`, newest first, each with how many decisions it made.

    Returns:
        At most `limit` ticks, as `db.recent_ticks` reads them.
    """
    found = records.fetch_all(
        conn,
        records.Tick,
        sql.select("*")
        .from_("ticks")
        .where("started_at >= ? AND started_at < ? AND dry_run = 0 AND idle = 1", since, until)
        .order_by("id DESC")
        .limit(limit),
    )
    return db.with_decision_counts(conn, found)


@dataclass(frozen=True)
class _TickRow:
    """Ticks of one bucket that share a group, a status, and a cause: how many, their cost, and how many had none."""

    day: str
    dry: bool
    group: Group | None
    woken_by: str | None
    ticks: int
    cost_usd: float | None
    unpriced: int

    @property
    def live_loop(self) -> bool:
        """Whether these ended live ticks the loop ran: what `woken_by` counts."""
        return self.woken_by is not None and self.group not in {None, "dry_run"}


def _tick_rows(conn: sqlite3.Connection, since: str, until: str, bucket: sql.Fragment) -> list[_TickRow]:
    grouped = (
        sql.select(
            "{} AS day, dry_run, status, idle, woken_by, count(*), SUM(cost_usd), count(*) - count(cost_usd)", bucket
        )
        .from_("ticks")
        .where("started_at >= ? AND started_at < ?", since, until)
        .group_by("day, dry_run, status, idle, woken_by")
    )
    rows = sql.execute(conn, grouped).fetchall()
    return [
        _TickRow(
            day=str(day),
            dry=bool(dry),
            group=_group(str(status), idle, dry=bool(dry)),
            woken_by=None if woken is None else str(woken),
            ticks=int(count),
            cost_usd=cost,
            unpriced=int(unpriced),
        )
        for day, dry, status, idle, woken, count, cost, unpriced in rows
    ]


# A still running tick is in no group yet.
def _group(status: str, idle: int | None, *, dry: bool) -> Group | None:
    if status == "running":
        return None
    if dry:
        return "dry_run"
    if status != "ok":
        return "not_ok"
    if idle is None:
        return "hand_run"
    return "idle" if idle else "busy"


# Whether a tick row's cost counts toward the `overseer`, `idle`, or `dry_run` cost of its day. A dry run is never the
# live overseer's, running or not: its cost is recorded before it closes.
def _in_series(row: _TickRow, name: str) -> bool:
    if name == "dry_run":
        return row.dry
    if name == "idle":
        return row.group == "idle"
    return not row.dry


def _groups(rows: Collection[_TickRow]) -> list[TickGroup]:
    return [
        TickGroup(
            group=g,
            ticks=sum(r.ticks for r in rows if r.group == g),
            cost_usd=_sum([r.cost_usd for r in rows if r.group == g]),
        )
        for g in GROUPS
    ]


# The live ticks the loop ran, by what ended the wait before each, the most common first.
def _woken(rows: Iterable[_TickRow]) -> list[Woken]:
    by_cause: dict[str, list[_TickRow]] = {}
    for row in rows:
        if row.live_loop and row.woken_by is not None:
            by_cause.setdefault(row.woken_by, []).append(row)
    found = [
        Woken(by=cause, ticks=sum(r.ticks for r in caused), cost_usd=_sum([r.cost_usd for r in caused]))
        for cause, caused in sorted(by_cause.items())
    ]
    return sorted(found, key=lambda w: -w.ticks)


# Idle ticks' share of what the live ticks that ended cost: a tick still running has reported its cost and has no
# group yet, so it is in neither part. None when they cost nothing or reported nothing, as no share of zero exists.
def _idle_share(ticks: Collection[TickGroup]) -> float | None:
    live = _sum([g.cost_usd for g in ticks if g.group != "dry_run"])
    idle = next((g.cost_usd for g in ticks if g.group == "idle"), None)
    return (idle or 0.0) / live if live else None


def _unpriced(conn: sqlite3.Connection, since: str, until: str, rows: Iterable[_TickRow]) -> list[Unpriced]:
    ended = [r for r in rows if r.group is not None]
    found = [Unpriced(kind="overseer", runs=sum(r.ticks for r in ended), unpriced=sum(r.unpriced for r in ended))]
    for kind, (table, which) in _TABLES.items():
        counted = (
            sql.select("count(*), count(*) - count(cost_usd)")
            .from_(table)
            .where("{}", which)
            .where("started_at >= ? AND started_at < ? AND status != 'running'", since, until)
        )
        runs, unpriced = sql.execute(conn, counted).fetchone()
        found.append(Unpriced(kind=kind, runs=int(runs), unpriced=int(unpriced)))
    return found


# The tickets marked done in the window, each with how and when: its newest `done` decision, as `recently_done` reads
# it (§7), but `closed` ones too, since a tracker that closes a ticket when its PR merges closes most that landed. Not
# one marked done before the operator last forgot it, nor one reopened since, which is no longer done.
def _done(conn: sqlite3.Connection, since: str, until: str) -> dict[str, tuple[Done, str]]:
    marked = (
        sql.select("t.key, d.rationale, d.created_at")
        .from_("tickets t")
        .join("decisions d ON d.id = (SELECT max(id) FROM decisions WHERE ticket_key = t.key AND action = 'done')")
        .where("t.done = 1 AND d.created_at >= ? AND d.created_at < ?", since, until)
        .where("t.forgotten_at IS NULL OR d.created_at > t.forgotten_at")
    )
    rows = sql.execute(conn, marked).fetchall()
    return {
        str(key): ("closed" if rationale == db.CLOSED_RATIONALE else "merged", str(at)) for key, rationale, at in rows
    }


# Each ticket with a run or a review run that started in the window, or marked done in it, the costliest first.
def _tickets(
    conn: sqlite3.Connection, since: str, until: str, done: Mapping[str, tuple[Done, str]]
) -> list[TicketSpend]:
    runs = _by_ticket(conn, "runs", since, until)
    reviews = _by_ticket(conn, "review_runs", since, until)
    keys = sorted({*runs, *reviews, *done})
    named = sql.select("key, title").from_("tickets").where("key IN (SELECT value FROM json_each(?))", json.dumps(keys))
    titles = {str(key): None if title is None else str(title) for key, title in sql.execute(conn, named)}
    found = [
        TicketSpend(
            key=key,
            title=titles.get(key),
            runs=runs.get(key, (0, None))[0],
            reviews=reviews.get(key, (0, None))[0],
            cost_usd=_sum([runs.get(key, (0, None))[1], reviews.get(key, (0, None))[1]]),
            done=done[key][0] if key in done else None,
            done_at=done[key][1] if key in done else None,
        )
        for key in keys
    ]
    return sorted(found, key=lambda t: -(t.cost_usd or 0.0))


def _by_ticket(
    conn: sqlite3.Connection, table: Literal["runs", "review_runs"], since: str, until: str
) -> dict[str, tuple[int, float | None]]:
    by_key = (
        sql.select("ticket_key, count(*), SUM(cost_usd)")
        .from_(table)
        .where("started_at >= ? AND started_at < ? AND ticket_key IS NOT NULL", since, until)
        .group_by("ticket_key")
    )
    return {str(key): (int(count), cost) for key, count, cost in sql.execute(conn, by_key)}


# Each PR a run that started in the window pushed to, as its result names it, or a review run of it started in the
# window, the costliest first. A run still running names no PR yet, so it counts on its ticket and on none of these.
def _pull_requests(conn: sqlite3.Connection, since: str, until: str) -> list[PullRequestSpend]:
    runs: dict[str, list[tuple[str, float | None]]] = {}
    pushed = (
        sql.select("ticket_key, result_json, cost_usd")
        .from_("runs")
        .where("started_at >= ? AND started_at < ?", since, until)
    )
    for key, result, cost in sql.execute(conn, pushed):
        for url in dict.fromkeys(contract.stored_prs(contract.stored_object(result))):
            runs.setdefault(url, []).append((str(key), cost))
    reviews: dict[str, list[tuple[str | None, float | None]]] = {}
    reviewed = (
        sql.select("pr_url, ticket_key, cost_usd")
        .from_("review_runs")
        .where("started_at >= ? AND started_at < ?", since, until)
    )
    for url, key, cost in sql.execute(conn, reviewed):
        reviews.setdefault(str(url), []).append((None if key is None else str(key), cost))
    urls = sorted({*runs, *reviews})
    of_units = (
        sql.select("pr_url, ticket_key, phase")
        .from_("ticket_units")
        .where("pr_url IN (SELECT value FROM json_each(?))", json.dumps(urls))
    )
    units = {
        str(url): (str(key), None if phase is None else str(phase)) for url, key, phase in sql.execute(conn, of_units)
    }
    found = [
        PullRequestSpend(
            url=url,
            ticket=units[url][0] if url in units else _first_key([*runs.get(url, []), *reviews.get(url, [])]),
            phase=units[url][1] if url in units else None,
            runs=len(runs.get(url, [])),
            reviews=len(reviews.get(url, [])),
            cost_usd=_sum([cost for _, cost in [*runs.get(url, []), *reviews.get(url, [])]]),
        )
        for url in urls
    ]
    return sorted(found, key=lambda p: -(p.cost_usd or 0.0))


def _first_key(named: Iterable[tuple[str | None, float | None]]) -> str | None:
    return next((key for key, _ in named if key is not None), None)


# Each kind's first model calls in the window, grouped by the snapshot their runs loaded. A run recorded before canopy
# kept the first call, or that made none, is in no group.
def _first_calls(conn: sqlite3.Connection, since: str, until: str) -> list[FirstCalls]:
    found: list[FirstCalls] = []
    for kind in KINDS:
        table, which = _ALL_TABLES[kind]
        by_digest: dict[str | None, list[tuple[int, bool, str]]] = {}
        first = (
            sql.select(_FIRST_CALL)
            .from_(table)
            .where("{}", which)
            .where("started_at >= ? AND started_at < ? AND tokens_first_call IS NOT NULL", since, until)
            .order_by("started_at, id")
        )
        for digest, sent, written, started in sql.execute(conn, first):
            call = (int(sent), _cold(int(sent), int(written or 0)), str(started))
            by_digest.setdefault(None if digest is None else str(digest), []).append(call)
        found.extend(
            FirstCalls(
                kind=kind,
                digest=digest,
                runs=len(calls),
                first_call=statistics.median_low(sent for sent, _, _ in calls),
                cold_share=sum(cold for _, cold, _ in calls) / len(calls),
                first_started=calls[0][2],
                last_started=calls[-1][2],
            )
            for digest, calls in by_digest.items()
        )
    return found


# Each kind's tool calls in the window, by tool, the most characters first. A run whose template printed no events, or
# recorded before canopy kept its tools, called none.
def _tools(conn: sqlite3.Connection, since: str, until: str) -> list[ToolSpend]:
    found: list[ToolSpend] = []
    for kind in KINDS:
        for tool, runs, calls, errors, chars in sql.execute(conn, _tools_of(kind, since, until)):
            found.append(
                ToolSpend(
                    kind=kind,
                    tool=str(tool),
                    runs=int(runs),
                    calls=int(calls),
                    errors=int(errors),
                    result_chars=int(chars),
                    est_tokens=int(chars) // CHARS_PER_TOKEN,
                )
            )
    return sorted(found, key=lambda t: (-t.result_chars, KINDS.index(t.kind), t.tool))


# One kind's tool calls in a window, from its runs that started in it. The run table leads, through its `_spent` index
# on `started_at` (migration 0022), and `run_tools` is read by its key's prefix: `CROSS JOIN` keeps SQLite from
# reordering them, which with no statistics it would, reading every `run_tools` row of the kind ever recorded. The
# kind's condition names only the run table's columns, which `run_tools` shares none of.
def _tools_of(kind: Kind, since: str, until: str) -> sql.Select:
    table, which = _ALL_TABLES[kind]
    return (
        sql.select("t.tool, count(*), SUM(t.calls), SUM(t.errors), SUM(t.result_chars)")
        .from_("{} r CROSS JOIN run_tools t ON t.run_table = ? AND t.run_id = r.id", sql.name(table), table)
        .where("r.started_at >= ? AND r.started_at < ?", since, until)
        .where("{}", which)
        .group_by("t.tool")
    )


# Whether a first call started cold: it wrote most of what it was sent to the cache, where a warm one reads the fixed
# prefix (the system prompt, the agent's body, the tools) from it and writes only what is new.
def _cold(sent: int, written: int) -> bool:
    return 2 * written > sent


def _costs(found: Mapping[str, float | None]) -> Costs:
    return Costs(
        overseer=found.get("overseer"),
        idle=found.get("idle"),
        dry_run=found.get("dry_run"),
        workers=found.get("workers"),
        plans=found.get("plans"),
        chores=found.get("chores"),
        reviews=found.get("reviews"),
    )


# The sum of the values that are not None; None when every one is.
def _sum(values: Iterable[float | None]) -> float | None:
    parts = [float(v) for v in values if v is not None]
    return sum(parts) if parts else None
