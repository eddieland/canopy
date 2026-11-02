"""What agent runs cost, by what they bought (DESIGN §11; ROADMAP M33), for `canopy spend`, the web UI, and digests.

Reads only. Every cost is what the agent runtime reported (§13), summed by the local day a run started on, or by the
local hour for a window in hours: the overseer of each tick, worker runs (old split runs among them), plan runs (§25,
old triage runs before a plan among them), chore runs, review runs, and task runs (§36). A dry run's overseer is kept
apart from the live ones', and idle ticks' (§6, Idle pacing) are a series of their own within the live overseer's.
Beside what the window
cost, what it got done: the tickets marked done in it, and what each ticket and PR's own runs cost.
And what each kind of run's first model call was sent, by the definitions snapshot it loaded: its fixed overhead, and
how often it started cold; and by week, each chore's and each model's apart, with how much of it was read from the cache
and where the runtime's version or the snapshot changed. And what each kind's tool calls put into its context, by tool:
the reads that each later model call reads again. And what each kind spent on each model, as the runs' own sessions
say (§13), the workspace's or one ticket's beside it. And the local calendar month so far against the operator's
monthly budget, which nothing enforces. And what every session the runtime keeps cost, canopy's apart from the rest,
as the runtime's record says (`runtime_sessions`). A figure of all spend, the month's against its budget and
`spent_since`'s, is canopy's runs and the sessions outside canopy together: canopy's own sessions are its runs, so they
are counted once.
"""

from __future__ import annotations

import dataclasses
import json
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Literal, LiteralString

from canopy.core import contract, db, records, run_models, runtime_sessions, sql
from canopy.core.vocab import RunKind, SessionsRead

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
    from collections.abc import Set as AbstractSet
    from pathlib import Path

    from canopy.core import config

type Group = Literal["idle", "busy", "hand_run", "not_ok", "dry_run"]
type Kind = Literal["overseer", "workers", "plans", "chores", "reviews", "tasks"]
type Done = Literal["merged", "closed"]
#: What a weekly series of first calls follows within a kind: every run of it, those of one chore, or one model's.
type By = Literal["kind", "chore", "model"]
#: A table of agent runs, each with a `started_at` and a `cost_usd`: the overseer's ticks, and the others'.
type _Table = Literal["ticks", "runs", "chore_runs", "review_runs", "task_runs"]

# Every tick that ended is in exactly one group, in this order: a dry run first, whatever the loop said of it, then a
# live tick that did not close `ok`, then the loop's word on an `ok` one, idle or not, and last a tick no loop ran. A
# tick from before migration 0013 has no word from the loop either, so it reads as hand-run: nothing can tell.
GROUPS: tuple[Group, ...] = ("idle", "busy", "hand_run", "not_ok", "dry_run")
KINDS: tuple[Kind, ...] = ("overseer", "workers", "plans", "chores", "reviews", "tasks")
#: Each kind's weekly series of first calls, in the order `Breakdown.first_call_weeks` lists them.
BY: tuple[By, ...] = ("kind", "chore", "model")
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
_PLANS = (RunKind.PLAN, RunKind.NEEDS_PLAN)
_EVERY = sql.frag("1")
_TABLES: Mapping[Kind, tuple[_Table, sql.Fragment]] = {
    "workers": ("runs", sql.not_in("kind", _PLANS)),
    "plans": ("runs", sql.in_("kind", _PLANS)),
    "chores": ("chore_runs", _EVERY),
    "reviews": ("review_runs", _EVERY),
    "tasks": ("task_runs", _EVERY),
}
#: Every kind of agent run by its table and the condition on the table's rows, the overseer's ticks included.
KIND_TABLES: Mapping[Kind, tuple[_Table, sql.Fragment]] = {"overseer": ("ticks", _EVERY), **_TABLES}
# The run tables whose rows name a ticket: a worker's or a plan's run, and a review's of the ticket's PR.
_TICKET_TABLES: AbstractSet[_Table] = frozenset({"runs", "review_runs"})
#: The budget whole, as a percentage of it: the alert always sent.
FULL = 100
# About how many characters make a token: what a tool's result is counted in, as an estimate of its tokens.
CHARS_PER_TOKEN = 4
# The overseer's series, each from the ticks.
_SERIES = ("overseer", "idle", "dry_run")
# What a run's row, `r`, says of its first model call, and when it started; then, from the read of its session
# (`canopy.core.run_models`), the runtime's version its record named and the one model it named, None for none or more
# than one, each for a `?` the run's table fills; and the chore it ran, for the `{}`.
_FIRST_CALL: LiteralString = (
    "r.definitions_digest, r.tokens_first_call, r.tokens_first_cache_write, r.tokens_first_cache_read, r.started_at, "
    "(SELECT m.runtime_version FROM run_model_reads m WHERE m.run_table = ? AND m.run_id = r.id), "
    "(SELECT CASE WHEN count(*) = 1 THEN max(m.model) END FROM run_models m "
    "WHERE m.run_table = ? AND m.run_id = r.id), {}"
)
# The chore a run ran: only a chore's run names one. Fixed, never input (D125).
_CHORE = sql.frag("r.chore")
_NO_CHORE = sql.frag("NULL")
#: The local day a row started on, as `YYYY-MM-DD`: SQLite reads the journal's UTC time in the local time Python does.
DAY = sql.frag("date(started_at, 'localtime')")
# The local hour a row started on, as `YYYY-MM-DDTHH`, read the same way.
_HOUR_FORMAT = "%Y-%m-%dT%H"
_HOUR = sql.frag("strftime(?, started_at, 'localtime')", _HOUR_FORMAT)


@dataclass(frozen=True)
class Costs:
    """What each kind of agent run cost, in US dollars; None for a kind none of whose runs reported a cost.

    `overseer` is the live ticks' overseers, `idle` the part of it idle ticks spent, and `dry_run` the dry runs'
    overseers, apart from it. `outside` is no run of canopy's but the runtime's sessions outside canopy.
    """

    overseer: float | None = None
    idle: float | None = None
    dry_run: float | None = None
    workers: float | None = None
    plans: float | None = None
    chores: float | None = None
    reviews: float | None = None
    #: The operator's one-off tasks' runs (DESIGN §36).
    tasks: float | None = None
    #: The runtime's sessions outside canopy, as `runtime_sessions.spend` tells them from canopy's; None when none.
    outside: float | None = None

    @property
    def runs(self) -> float | None:
        """Every kind of canopy's runs, dry runs included; None when none reported a cost."""
        return _sum([self.overseer, self.dry_run, self.workers, self.plans, self.chores, self.reviews, self.tasks])

    @property
    def total(self) -> float | None:
        """Everything, canopy's runs and the sessions outside canopy, as the budget and the web UI's counters count it.

        None when nothing reported a cost.
        """
        return _sum([self.runs, self.outside])


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
    #: How many of them ran no overseer, left nothing to judge or halted before it (§39): each counted at nothing.
    without_overseer: int = 0


@dataclass(frozen=True)
class Woken:
    """How many of the loop's ticks one cause woke (`ticks.woken_by`, §6), and what their overseers cost."""

    by: str
    ticks: int
    cost_usd: float | None
    #: How many of them ran no overseer, left nothing to judge or halted before it (§39): each counted at nothing.
    without_overseer: int = 0


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
    reading less than half of what it was sent from the cache, or, for a run recorded before canopy kept what it read,
    writing more than half of it. `first_started` and `last_started` are when the first and the last of them started.
    `digest` is None for runs that reported a first call and no snapshot.
    """

    kind: Kind
    digest: str | None
    runs: int
    first_call: int
    cold_share: float
    first_started: str
    last_started: str
    #: What their first calls read from the cache over what they were sent, summed over the runs that recorded both;
    #: None when none did.
    hit_rate: float | None = None
    #: The runtime's versions their sessions' records named, in the order their runs first ran on each: a second one
    #: is a change of the runtime within the snapshot, which may change the prefix the runs share.
    runtime_versions: Sequence[str] = ()


@dataclass(frozen=True)
class FirstCallWeek:
    """The first model calls of one kind's runs that started in one local ISO week of the window (§13).

    One week of a series: with `by` `kind`, every run of the kind; `chore`, those of the chore `name`; `model`, those
    the model `name` alone served, `name` None for the runs no session was read for or more than one model served. A
    fall in `hit_rate` from one week to the next is a prefix the runs share that their first calls no longer read from
    the cache, as a change of the runtime or of canopy's definitions can make, which the week's `new_runtime_versions`
    and `new_digests` name.
    """

    kind: Kind
    by: By
    name: str | None
    #: The ISO week, `2026-W41`, of this machine's local time: Monday to Sunday.
    week: str
    #: How many of the runs reported a first call.
    runs: int
    #: The median of what their first calls were sent, the lower middle one of an even count.
    first_call: int
    #: What their first calls read from the cache over what they were sent, summed over the runs that recorded both;
    #: None when none did.
    hit_rate: float | None
    #: The runtime's versions their sessions' records named that no run of the series' earlier weeks in the window
    #: did, in the order the runs first ran on each; the series' first week names none, having none before it.
    new_runtime_versions: Sequence[str] = ()
    #: The definitions snapshots their runs loaded that no run of the series' earlier weeks did, the same way.
    new_digests: Sequence[str] = ()


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
class ModelSpend:
    """What one kind's runs that started in the window spent on one model, as each run's session says (§13).

    `runs` counts the runs one of whose replies the model wrote, so a run on two models counts under each, `replies`
    the replies it wrote, and `cost_usd` what the session priced them at. `model` is None for the kind's runs whose
    sessions named no model, in two rows by `unread`; their cost is what the runs themselves reported, and `replies`
    is 0.
    """

    kind: Kind
    model: str | None
    runs: int
    replies: int
    cost_usd: float | None
    #: For a row of no model, whether its runs' sessions canopy has yet to read: running, not read yet, or a read that
    #: failed (`run_models.unread`). False for the rest: no longer kept, no session to read, or no model call; and for
    #: a model's row.
    unread: bool = False
    #: For a row narrowed to a ticket (`models`), the workspace's runs of its kind on its model in the window, the
    #: ticket's among them, to compare with; None for a row of the whole workspace.
    workspace_runs: int | None = None
    #: What those runs spent on the model, as `cost_usd` counts it; None as `workspace_runs` is.
    workspace_cost_usd: float | None = None


@dataclass(frozen=True)
class Breakdown:
    """The window's spend: per day, oldest first, every day in it listed; in total; and by what the ticks bought.

    The window is `[since, until)`, each a journal time: local midnight on its first day, and after its last. A window
    in `hours` has `days` None and lists each hour in `per_day`, from its first hour's start to the end of its last.
    What it got done is `done`, the tickets marked done in it, and `per_done`, its runs' spend over them: the overseer,
    chores, and the runs of tickets still open are what it cost to get those done. `tickets` and `pull_requests` list
    what each one's own runs cost, the most first. `first_calls` is each kind's first model calls by snapshot, the
    kinds in `KINDS` order and each kind's snapshots by when their first run started; the overseer's include dry runs,
    whose first call is a live tick's. `tools` is what each kind's tool calls returned, by tool, the most characters
    first; the overseer's include dry runs too. `models` is what each kind spent on each model, the kinds in `KINDS`
    order and each kind's models the most costly first, its runs no session named a model for last, those unread
    before the rest; the overseer's include dry runs too. `sessions` is what every session the runtime keeps cost,
    canopy's apart from the rest.
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
    models: Sequence[ModelSpend] = ()
    sessions: runtime_sessions.SessionsSpend | None = None
    #: Each kind's first model calls by local ISO week: the kinds in `KINDS` order, each kind's series in `BY` order,
    #: its chores' and models' by name, the runs no single model served last, and each series' weeks oldest first. The
    #: overseer's include dry runs, as its `first_calls` do.
    first_call_weeks: Sequence[FirstCallWeek] = ()


@dataclass(frozen=True)
class Month:
    """The local calendar month so far, against the operator's monthly budget (`spend.monthly_budget_usd`)."""

    #: The month, `YYYY-MM`, in this machine's local time.
    month: str
    #: When it starts and ends, each a journal time: local midnight on its first day, and on the next month's.
    since: str
    until: str
    #: The budget, in whole US dollars.
    budget_usd: int
    #: What it has cost so far: `runs_usd` and `outside_usd` together; None when neither reported a cost.
    spent_usd: float | None
    #: How much of the month has gone by, from 0 to 1.
    elapsed: float
    #: What the month will cost if the rest of it spends as it has so far; None in its first day, when a few runs would
    #: read as a month's worth, or when nothing reported a cost.
    projected_usd: float | None
    #: The percentages of the budget a sink hears the month reach, lowest first: 100 and `spend.budget_alerts`.
    alerts: Sequence[int] = (FULL,)
    #: What every run that started in it so far cost, dry runs included, as `Costs.total` counts it; None when none
    #: reported a cost.
    runs_usd: float | None = None
    #: What the runtime's sessions outside canopy that started in it cost, as `runtime_sessions.spend` counts them.
    outside_usd: float = 0.0
    #: When the runtime's sessions were last read, a journal time; None when they never were, and `outside_usd` is 0.
    sessions_read_at: str | None = None
    #: How that read ended: after a `failed` one, `outside_usd` is what an earlier read found; None when none ran.
    sessions_read: SessionsRead | None = None

    @property
    def share(self) -> float:
        """What the month has spent so far over its budget: 1 or more once it reached the budget."""
        return (self.spent_usd or 0.0) / self.budget_usd

    @property
    def percent(self) -> int:
        """What the month has spent of its budget, as a whole percentage, floored: 99 until it reaches the budget."""
        # In whole cents, so a float a hair under a cent's worth, `0.29 * 100`, never floors a point away.
        return self._cents // self.budget_usd

    @property
    def over(self) -> bool:
        """Whether the month has spent its budget."""
        return self.reached_percent(FULL)

    @property
    def reached(self) -> int | None:
        """The highest of `alerts` the month's spend has reached; None before it reaches the lowest."""
        return max((p for p in self.alerts if self.reached_percent(p)), default=None)

    def reached_percent(self, percent: int) -> bool:
        """Whether the month's spend has reached `percent` of its budget, to the cent.

        Returns:
            True once it spent that much or more.
        """
        return self._cents * 100 >= self.budget_usd * percent * 100

    @property
    def _cents(self) -> int:
        return round((self.spent_usd or 0.0) * 100)


def budget_month(conn: sqlite3.Connection, now: datetime, budget: config.Spend, *, state_dir: Path) -> Month | None:
    """The local month holding `now` against the operator's budget and alerts, from their `[spend]` table.

    `state_dir` is the workspace's, as `month` takes it.

    Returns:
        The month, or None when no budget is set.
    """
    if budget.monthly_budget_usd is None:
        return None
    return month(conn, now, budget.monthly_budget_usd, budget.budget_alerts, state_dir=state_dir)


def month(
    conn: sqlite3.Connection,
    now: datetime,
    budget_usd: int,
    alerts: Iterable[int] = (),
    *,
    state_dir: Path,
) -> Month:
    """What the local calendar month holding `now` has cost so far, against `budget_usd`.

    Its runs, and the runtime's sessions outside canopy: `state_dir` is the workspace's, whose sessions are canopy's.

    Returns:
        The month, its spend so far, where that spend is headed, and the percentages of the budget a sink hears of:
        100, and each of `alerts`.
    """
    today = now.astimezone().date()
    first = today.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    start, end = _midnight(first), _midnight(following)
    since, until = db.format_time(start), db.format_time(end)
    with db.read_snapshot(conn):
        found = costs(conn, since, until, state_dir=state_dir)
        read = runtime_sessions.last_read(conn)
    spent = found.total
    gone = now - start
    elapsed = min(1.0, max(0.0, gone / (end - start)))
    projected = spent / elapsed if spent is not None and gone >= timedelta(days=1) else None
    return Month(
        month=first.strftime("%Y-%m"),
        since=db.format_time(start),
        until=db.format_time(end),
        budget_usd=budget_usd,
        spent_usd=spent,
        elapsed=elapsed,
        projected_usd=projected,
        alerts=tuple(sorted({FULL, *alerts})),
        runs_usd=found.runs,
        outside_usd=found.outside or 0.0,
        sessions_read_at=read.read_at if read is not None else None,
        sessions_read=read.status if read is not None else None,
    )


def spent_since(conn: sqlite3.Connection, since: str, *, state_dir: Path) -> float | None:
    """What every agent session that started at or after `since`, a journal time, cost: the web UI's counters.

    canopy's runs, as `db.spent_since` sums them, and the runtime's sessions outside canopy, as `month` adds them;
    `since` the empty string sums everything.

    Returns:
        The total in US dollars; None when nothing reported a cost.
    """
    with db.read_snapshot(conn):
        runs = db.spent_since(conn, since)
        outside = runtime_sessions.outside(conn, since, state_dir=state_dir)
    return _sum([runs, outside.cost_usd if outside.sessions else None])


def window(now: datetime, days: int) -> tuple[datetime, datetime]:
    """The window `[start, until)`: `days` whole days of this machine's local time, ending with `now`'s day.

    A day is from one local midnight to the next, so a day that a clock change shortens or lengthens is still one day.

    Returns:
        Its start and its end, each an aware UTC datetime.
    """
    today = now.astimezone().date()
    return _midnight(today - timedelta(days=days - 1)), _midnight(today + timedelta(days=1))


def days_between(start: datetime, end: datetime) -> int:
    """How many local days a window from one local midnight, `start`, to another, `end`, holds.

    Returns:
        The count, by the local calendar, so a day that a clock change shortens or lengthens is still one day.
    """
    return (end.astimezone().date() - start.astimezone().date()).days


def window_before(since: str, days: int) -> tuple[datetime, datetime]:
    """The window of `days` local days that ends where one starting at `since`, a journal time, starts.

    A report's window before, to compare it with: as many days, so a day a clock change shortens is still one day.

    Returns:
        Its start and its end, each an aware UTC datetime.
    """
    start = db.parse_time(since)
    return _midnight(start.astimezone().date() - timedelta(days=days)), start


def day_starts(start: datetime, days: int) -> dict[str, str]:
    """Each local day of a window that `window` began at `start`, by its name, with when it starts.

    Returns:
        The days oldest first, each named `YYYY-MM-DD` as `local_day` names it, with its local midnight, a journal time.
    """
    first = start.astimezone().date()
    each = [first + timedelta(days=i) for i in range(days)]
    return {day.isoformat(): db.format_time(_midnight(day)) for day in each}


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


def breakdown(
    conn: sqlite3.Connection,
    now: datetime,
    days: int,
    *,
    state_dir: Path,
    ticket: str | None = None,
) -> Breakdown:
    """What the last `days` local days cost, today's so far included, by day, by kind, and by what the ticks bought.

    `state_dir` is the workspace's: a session of the runtime's that ran in it is canopy's (`runtime_sessions.spend`).
    `ticket` narrows `models` alone to that ticket's runs, as `models` does; every other figure is the workspace's.

    Returns:
        The breakdown; a window with nothing in it lists each day with no costs.
    """
    start, end = window(now, days)
    buckets = _Buckets(expression=DAY, starts=day_starts(start, days), name_of=local_day)
    return _breakdown(conn, start, end, buckets, state_dir=state_dir, days=days, ticket=ticket)


def breakdown_hours(
    conn: sqlite3.Connection,
    now: datetime,
    hours: int,
    *,
    state_dir: Path,
    ticket: str | None = None,
) -> Breakdown:
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
    return _breakdown(conn, start, end, buckets, state_dir=state_dir, hours=hours, ticket=ticket)


@dataclass(frozen=True)
class Headline:
    """A span's headline figures, as a breakdown's: what it cost, and what it got done for that."""

    totals: Costs
    #: The tickets marked done in it, merged or closed.
    done: int
    #: Its runs' spend over them; None when none was, or none reported a cost.
    per_done: float | None


def headline(conn: sqlite3.Connection, since: str, until: str, *, state_dir: Path) -> Headline:
    """What `[since, until)`, each a journal time, cost and got done, summed as a breakdown's are: a window before.

    Returns:
        The figures; a span with nothing in it has every cost None and nothing done.
    """
    with db.read_snapshot(conn):
        totals = costs(conn, since, until, state_dir=state_dir)
        done = done_in(conn, since, until)
    runs = totals.runs
    return Headline(totals=totals, done=len(done), per_done=runs / len(done) if done and runs is not None else None)


def costs(conn: sqlite3.Connection, since: str, until: str, *, state_dir: Path) -> Costs:
    """What each kind of agent run that started in `[since, until)`, each a journal time, cost: a sink's digest (§20).

    Summed as a breakdown's `totals` are, but over any span rather than whole local days or hours, the sessions outside
    canopy among them: `state_dir` is the workspace's, whose sessions are canopy's.

    Returns:
        The costs; a kind none of whose runs in the span reported a cost is None.
    """
    found: dict[str, float | None] = {}
    with db.read_snapshot(conn):
        rows = _tick_rows(conn, since, until, DAY)
        for kind, (table, which) in _TABLES.items():
            summed = (
                sql.select("SUM(cost_usd)")
                .from_(table)
                .where("{}", which)
                .where("started_at >= ? AND started_at < ?", since, until)
            )
            found[kind] = sql.execute(conn, summed).fetchone()[0]
        outside = runtime_sessions.outside(conn, since, until, state_dir=state_dir)
    found["outside"] = outside.cost_usd if outside.sessions else None
    for name in _SERIES:
        found[name] = _sum([r.cost_usd for r in rows if _in_series(r, name)])
    return _costs(found)


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
    state_dir: Path,
    days: int | None = None,
    hours: int | None = None,
    ticket: str | None = None,
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
        outside = (
            sql.select("{} AS day, SUM(cost_usd)", buckets.expression)
            .from_("({}) AS s", runtime_sessions.sessions_in(since, until, state_dir))
            .where("NOT ours")
            .group_by("day")
        )
        for day, cost in sql.execute(conn, outside):
            by_day.setdefault(str(day), {})["outside"] = cost
        unpriced = _unpriced(conn, since, until, rows)
        done = done_in(conn, since, until)
        tickets = _tickets(conn, since, until, done)
        pull_requests = _pull_requests(conn, since, until)
        calls = _first_call_rows(conn, since, until)
        tools = _tools(conn, since, until)
        by_model = models(conn, since, until, ticket=ticket)
        sessions = runtime_sessions.spend(conn, since, until, state_dir=state_dir)
    for row in rows:
        day = by_day.setdefault(row.day, {})
        for name in _SERIES:
            if _in_series(row, name):
                day[name] = _sum([day.get(name), row.cost_usd])
    starts = buckets.starts
    done_on = Counter(buckets.name_of(at) for _, at in done.values())
    per_day = [Day(day=d, start=s, costs=_costs(by_day.get(d, {})), done=done_on[d]) for d, s in starts.items()]
    totals = _costs({n: _sum([by_day.get(d, {}).get(n) for d in starts]) for n in (*_SERIES, *_TABLES, "outside")})
    ticks = _groups(rows)
    # What canopy's runs cost to get them done: the sessions outside canopy did nothing canopy knows of.
    runs = totals.runs
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
        per_done=runs / len(done) if done and runs is not None else None,
        tickets=tickets,
        pull_requests=pull_requests,
        first_calls=_first_calls(calls),
        tools=tools,
        hours=hours,
        models=by_model,
        sessions=sessions,
        first_call_weeks=_first_call_weeks(calls),
    )


def local_day(stamp: str) -> str:
    """The local day a journal time is on, as the window's days are named.

    Returns:
        The day, `YYYY-MM-DD`.
    """
    return db.parse_time(stamp).astimezone().date().isoformat()


def idle_ticks(
    conn: sqlite3.Connection,
    since: str,
    until: str,
    limit: int = IDLE_TICKS,
) -> list[tuple[records.Tick, int]]:
    """The newest live idle ticks that started in `[since, until)`, newest first, each with how many decisions it made.

    Returns:
        At most `limit` ticks, as `db.recent_ticks` reads them.
    """
    found = (
        records.select(records.Tick)
        .where("started_at >= ? AND started_at < ? AND dry_run = 0 AND idle = 1", since, until)
        .order_by("id DESC")
        .limit(limit)
        .all(conn)
    )
    return db.with_decision_counts(conn, found)


@dataclass(frozen=True)
class _TickRow:
    """Ticks of one bucket that share a group, a status, and a cause: how many, their cost, and how many had none."""

    day: str
    dry: bool
    group: Group | None
    woken_by: str | None
    #: Whether they ran their overseer: False for ticks the harness left it nothing (§39), whose cost is nothing.
    ran: bool
    ticks: int
    cost_usd: float | None
    unpriced: int

    @property
    def live_loop(self) -> bool:
        """Whether these ended live ticks the loop ran: what `woken_by` counts."""
        return self.woken_by is not None and self.group not in {None, "dry_run"}


def _tick_rows(conn: sqlite3.Connection, since: str, until: str, bucket: sql.Fragment) -> list[_TickRow]:
    # A tick from before `overseer_ran` was recorded ran its overseer if it got that far. One that ran none spent
    # nothing, so it counts at nothing, and never among the runs that reported no cost (§39).
    grouped = (
        sql.select(
            "{} AS day, dry_run, status, idle, woken_by, overseer_ran IS NOT 0 AS ran, count(*), SUM(cost_usd), "
            "count(*) - count(cost_usd)",
            bucket,
        )
        .from_("ticks")
        .where("started_at >= ? AND started_at < ?", since, until)
        .group_by("day, dry_run, status, idle, woken_by, ran")
    )
    rows = sql.execute(conn, grouped).fetchall()
    return [
        _TickRow(
            day=str(day),
            dry=bool(dry),
            group=_group(str(status), idle, dry=bool(dry)),
            woken_by=None if woken is None else str(woken),
            ran=bool(ran),
            ticks=int(count),
            cost_usd=cost if ran else (cost or 0.0),
            unpriced=int(unpriced) if ran else 0,
        )
        for day, dry, status, idle, woken, ran, count, cost, unpriced in rows
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
            without_overseer=sum(r.ticks for r in rows if r.group == g and not r.ran),
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
        Woken(
            by=cause,
            ticks=sum(r.ticks for r in caused),
            cost_usd=_sum([r.cost_usd for r in caused]),
            without_overseer=sum(r.ticks for r in caused if not r.ran),
        )
        for cause, caused in sorted(by_cause.items())
    ]
    return sorted(found, key=lambda w: -w.ticks)


# Idle ticks' share of what the live ticks that ended cost: a tick still running has reported its cost and has no
# group yet, so it is in neither part. None when they cost nothing or reported nothing, as no share of zero exists.
def _idle_share(ticks: Collection[TickGroup]) -> float | None:
    live = _sum([g.cost_usd for g in ticks if g.group != "dry_run"])
    idle = next((g.cost_usd for g in ticks if g.group == "idle"), None)
    return (idle or 0.0) / live if live else None


def unpriced(conn: sqlite3.Connection, since: str, until: str) -> list[Unpriced]:
    """How many of each kind's runs that started in `[since, until)`, each a journal time, and ended, reported no cost.

    Counted as `breakdown` counts them: a tick that ran no overseer costs nothing, so it is never among them.

    Returns:
        A row per kind, in `KINDS` order, those with no runs among them.
    """
    return _unpriced(conn, since, until, _tick_rows(conn, since, until, DAY))


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


def done_in(conn: sqlite3.Connection, since: str, until: str) -> dict[str, tuple[Done, str]]:
    """The tickets marked done in `[since, until)`, each a journal time, with how and when.

    A ticket's newest `done` decision, as `recently_done` reads it (§7), but `closed` ones too, since a tracker that
    closes a ticket when its PR merges closes most that landed. Not one marked done before the operator last forgot
    it, nor one reopened since, which is no longer done.

    Returns:
        Each ticket's key, with `merged` or `closed` and when the decision was made.
    """
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
    conn: sqlite3.Connection,
    since: str,
    until: str,
    done: Mapping[str, tuple[Done, str]],
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
    conn: sqlite3.Connection,
    table: Literal["runs", "review_runs"],
    since: str,
    until: str,
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


@dataclass(frozen=True)
class _FirstCall:
    """One run's first model call, as its row and the read of its session recorded it."""

    kind: Kind
    #: The definitions snapshot the run loaded; None for a run that reported none.
    digest: str | None
    #: What the call was sent, from the cache or not.
    sent: int
    #: Whether it started cold (`_cold`).
    cold: bool
    started: str
    #: What it read from the cache; None for a run recorded before canopy kept it.
    read: int | None
    #: The runtime's version its session's record named; None where no read found one.
    runtime_version: str | None
    #: The chore it ran; None for a run of any other kind.
    chore: str | None
    #: The one model its session named; None when no read found it, or more than one model served it.
    model: str | None


# Each kind's first model calls in the window, the kinds in `KINDS` order and each kind's by when its run started. A run
# recorded before canopy kept the first call, or that made none, has none.
def _first_call_rows(conn: sqlite3.Connection, since: str, until: str) -> list[_FirstCall]:
    found: list[_FirstCall] = []
    for kind in KINDS:
        table, which = KIND_TABLES[kind]
        first = (
            sql.select(_FIRST_CALL, table, table, _CHORE if kind == "chores" else _NO_CHORE)
            .from_("{} r", sql.name(table))
            .where("{}", which)
            .where("r.started_at >= ? AND r.started_at < ? AND r.tokens_first_call IS NOT NULL", since, until)
            .order_by("r.started_at, r.id")
        )
        for digest, sent, written, was_read, started, version, model, chore in sql.execute(conn, first):
            read = None if was_read is None else int(was_read)
            found.append(
                _FirstCall(
                    kind=kind,
                    digest=None if digest is None else str(digest),
                    sent=int(sent),
                    cold=_cold(int(sent), int(written or 0), read),
                    started=str(started),
                    read=read,
                    runtime_version=None if version is None else str(version),
                    chore=None if chore is None else str(chore),
                    model=None if model is None else str(model),
                ),
            )
    return found


# Each kind's first calls grouped by the snapshot their runs loaded, in the order the calls come.
def _first_calls(calls: Iterable[_FirstCall]) -> list[FirstCalls]:
    by_snapshot: dict[tuple[Kind, str | None], list[_FirstCall]] = {}
    for call in calls:
        by_snapshot.setdefault((call.kind, call.digest), []).append(call)
    return [
        FirstCalls(
            kind=kind,
            digest=digest,
            runs=len(group),
            first_call=statistics.median_low(c.sent for c in group),
            cold_share=sum(c.cold for c in group) / len(group),
            first_started=group[0].started,
            last_started=group[-1].started,
            hit_rate=_hit_rate([(c.sent, c.read) for c in group if c.read is not None]),
            runtime_versions=tuple(dict.fromkeys(c.runtime_version for c in group if c.runtime_version is not None)),
        )
        for (kind, digest), group in by_snapshot.items()
    ]


# Each kind's first calls by local ISO week, in each of its series: the kind's, each chore's, and each model's.
def _first_call_weeks(calls: Iterable[_FirstCall]) -> list[FirstCallWeek]:
    series: dict[tuple[Kind, By, str | None], dict[str, list[_FirstCall]]] = {}
    for call in calls:
        week = _iso_week(call.started)
        for by, name in _series_of(call):
            series.setdefault((call.kind, by, name), {}).setdefault(week, []).append(call)
    found: list[FirstCallWeek] = []
    for (kind, by, name), weeks in sorted(series.items(), key=lambda s: _series_order(*s[0])):
        # What the series' earlier weeks used, all of them: a kind's runs use many snapshots side by side, one for each
        # prompt, persona, and model its runs rendered, so one the week before missed is not one the series never had.
        seen_versions: set[str | None] | None = None
        seen_digests: set[str | None] | None = None
        for week, group in sorted(weeks.items()):
            found.append(
                FirstCallWeek(
                    kind=kind,
                    by=by,
                    name=name,
                    week=week,
                    runs=len(group),
                    first_call=statistics.median_low(c.sent for c in group),
                    hit_rate=_hit_rate([(c.sent, c.read) for c in group if c.read is not None]),
                    new_runtime_versions=_new([c.runtime_version for c in group], seen_versions),
                    new_digests=_new([c.digest for c in group], seen_digests),
                ),
            )
            seen_versions = (seen_versions or set()) | {c.runtime_version for c in group}
            seen_digests = (seen_digests or set()) | {c.digest for c in group}
    return found


# The local ISO week a journal time is in, as `2026-W41`.
def _iso_week(stamp: str) -> str:
    year, week, _ = db.parse_time(stamp).astimezone().isocalendar()
    return f"{year}-W{week:02d}"


# The series a first call is in beside its kind's: its chore's, for a chore's run, and its model's.
def _series_of(call: _FirstCall) -> list[tuple[By, str | None]]:
    return [("kind", None), *([("chore", call.chore)] if call.chore is not None else []), ("model", call.model)]


# Where a series goes among the others: by its kind, then by whether it is the kind's, a chore's, or a model's, then
# by name.
def _series_order(kind: Kind, by: By, name: str | None) -> tuple[int, int, bool, str]:
    return KINDS.index(kind), BY.index(by), name is None, name or ""


# The values runs used, in the order they first used them, that `before` does not hold; none with `before` None, for a
# series' first week, which has no week before it to differ from.
def _new(used: Iterable[str | None], before: AbstractSet[str | None] | None) -> tuple[str, ...]:
    if before is None:
        return ()
    return tuple(v for v in dict.fromkeys(used) if v is not None and v not in before)


# What first calls read from the cache over what they were sent, each `(sent, read)`; None for none, or none sent.
def _hit_rate(calls: Sequence[tuple[int, int]]) -> float | None:
    sent = sum(s for s, _ in calls)
    return sum(r for _, r in calls) / sent if sent else None


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
                ),
            )
    return sorted(found, key=lambda t: (-t.result_chars, KINDS.index(t.kind), t.tool))


# One kind's tool calls in a window, from its runs that started in it. The run table leads, through its `_spent` index
# on `started_at` (migration 0022), and `run_tools` is read by its key's prefix: `CROSS JOIN` keeps SQLite from
# reordering them, which with no statistics it would, reading every `run_tools` row of the kind ever recorded. The
# kind's condition names only the run table's columns, which `run_tools` shares none of.
def _tools_of(kind: Kind, since: str, until: str) -> sql.Select:
    table, which = KIND_TABLES[kind]
    return (
        sql.select("t.tool, count(*), SUM(t.calls), SUM(t.errors), SUM(t.result_chars)")
        .from_("{} r CROSS JOIN run_tools t ON t.run_table = ? AND t.run_id = r.id", sql.name(table), table)
        .where("r.started_at >= ? AND r.started_at < ?", since, until)
        .where("{}", which)
        .group_by("t.tool")
    )


def models(
    conn: sqlite3.Connection,
    since: str,
    until: str,
    *,
    ticket: str | None = None,
    kind: Kind | None = None,
) -> list[ModelSpend]:
    """What each kind's runs that started in `[since, until)`, each a journal time, spent on each model (§13).

    As a breakdown's `models` lists them, the kinds in `KINDS` order and each kind's models the most costly first, its
    runs no session named a model for last, those unread before the rest. `kind` keeps one kind's rows. `ticket` keeps
    that ticket's runs, its workers', plans', and reviews', since no other kind's run names a ticket; each row then
    carries the workspace's runs of its kind on its model too, the ticket's among them, so a model the ticket was moved
    to reads against what it costs everywhere else.

    Returns:
        A row per kind and model; none for a kind with no runs in the window.
    """
    found: list[ModelSpend] = []
    with db.read_snapshot(conn):
        for each in KINDS if kind is None else (kind,):
            if ticket is None:
                found.extend(_models_of(conn, each, since, until, None))
            elif KIND_TABLES[each][0] in _TICKET_TABLES:
                workspace = {(m.model, m.unread): m for m in _models_of(conn, each, since, until, None)}
                found.extend(
                    _beside(m, workspace.get((m.model, m.unread))) for m in _models_of(conn, each, since, until, ticket)
                )
    return found


# One kind's spend by model in the window, from its runs that started in it, `ticket`'s alone when one is given; then
# those of its runs no session named a model for, under None, the unread ones first.
def _models_of(conn: sqlite3.Connection, kind: Kind, since: str, until: str, ticket: str | None) -> list[ModelSpend]:
    found = [
        ModelSpend(kind=kind, model=str(model), runs=int(runs), replies=int(replies), cost_usd=float(cost))
        for model, runs, replies, cost in sql.execute(conn, _named_models(kind, since, until, ticket))
    ]
    found.extend(
        ModelSpend(kind=kind, model=None, runs=int(runs), replies=0, cost_usd=cost, unread=bool(unread))
        for unread, runs, cost in sql.execute(conn, _unnamed_models(kind, since, until, ticket))
    )
    return found


# A ticket's row with the workspace's for the same kind and model beside it. The ticket's runs are among the
# workspace's, read in the same snapshot, so there is always one.
def _beside(row: ModelSpend, workspace: ModelSpend | None) -> ModelSpend:
    if workspace is None:
        return row
    return dataclasses.replace(row, workspace_runs=workspace.runs, workspace_cost_usd=workspace.cost_usd)


# One kind's spend by model in a window, read as `_tools_of` reads `run_tools`: the run table leads, by its `_spent`
# index, and `run_models` is read by its key's prefix. With a ticket, only the runs naming it.
def _named_models(kind: Kind, since: str, until: str, ticket: str | None = None) -> sql.Select:
    table, which = KIND_TABLES[kind]
    return (
        sql.select("m.model, count(*), SUM(m.replies), SUM(m.cost_usd)")
        .from_("{} r CROSS JOIN run_models m ON m.run_table = ? AND m.run_id = r.id", sql.name(table), table)
        .where("r.started_at >= ? AND r.started_at < ?", since, until)
        .where("{}", which)
        .where("{}", _of_ticket(ticket))
        .group_by("m.model")
        .order_by("SUM(m.cost_usd) DESC, m.model")
    )


# One kind's runs in a window that no session named a model for, and what they reported they cost: those canopy has
# yet to read, then the rest, a row each of them that has a run.
def _unnamed_models(kind: Kind, since: str, until: str, ticket: str | None = None) -> sql.Select:
    table, which = KIND_TABLES[kind]
    return (
        sql.select("{} AS unread, count(*), SUM(r.cost_usd)", run_models.unread(table))
        .from_("{} r", sql.name(table))
        .where("r.started_at >= ? AND r.started_at < ?", since, until)
        .where("{}", which)
        .where("{}", _of_ticket(ticket))
        .where("NOT EXISTS (SELECT 1 FROM run_models m WHERE m.run_table = ? AND m.run_id = r.id)", table)
        .group_by("unread")
        .order_by("unread DESC")
    )


# The condition keeping a run table's rows, `r`, that name `ticket`; every row for None.
def _of_ticket(ticket: str | None) -> sql.Fragment:
    return _EVERY if ticket is None else sql.frag("r.ticket_key = ?", ticket)


# Whether a first call started cold: it read less than half of what it was sent from the cache, where a warm one reads
# the fixed prefix (the system prompt, the agent's body, the tools) from it. A provider that reports no cache writes,
# as OpenAI's, still reports reads. A run recorded before canopy kept the read (`read` None) is cold when it wrote most
# of what it was sent to the cache instead.
def _cold(sent: int, written: int, read: int | None) -> bool:
    return 2 * read < sent if read is not None else 2 * written > sent


def _costs(found: Mapping[str, float | None]) -> Costs:
    return Costs(
        overseer=found.get("overseer"),
        idle=found.get("idle"),
        dry_run=found.get("dry_run"),
        workers=found.get("workers"),
        plans=found.get("plans"),
        chores=found.get("chores"),
        reviews=found.get("reviews"),
        tasks=found.get("tasks"),
        outside=found.get("outside"),
    )


# The sum of the values that are not None; None when every one is.
def _sum(values: Iterable[float | None]) -> float | None:
    parts = [float(v) for v in values if v is not None]
    return sum(parts) if parts else None
