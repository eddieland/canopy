"""How the loop's agent runs ended, and what its guards refused (DESIGN §11), read by `canopy health`.

Reads only. Over the same window as `canopy spend` (whole local days, today's so far included, by start): how many of
each kind's runs ended each way and what they cost, the newest of those that ended other than as they should, those
failures grouped by the harness's note, the overseer's asks a guard refused, by guard and by what each asked for, and,
for the web UI's health page, how many ended and failed each day. It is what a chore that looks at canopy itself reads,
beside `canopy spend`, to say which failures recur and what they cost.
"""

from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from canopy.core import contract, db, spend, sql
from canopy.core.vocab import ChoreRunStatus, ReviewRunStatus, RunKind, RunStatus, TickStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from canopy.core.config import Config
    from canopy.core.spend import Kind

# The newest failures a report lists, across every kind.
FAILURES = 20
# What a failure's note is cut to: enough to tell one cause from another, which `canopy show` and the web UI give whole.
NOTE_LIMIT = 300
REFUSED = "refused:"
#: The asks a refusal lists of what its guard refused, the most often refused first.
ASKS = 5


# The statuses each kind of run ends in when it did not do what it was started for. A worker that asked a question
# (`blocked`) or that the operator stopped did, as did a tick that closed `ok`. A plan run (§25), an old triage before
# a plan among them, is a run of the `runs` table, and fails as a worker does.
_WORKER_FAILED = frozenset(
    {RunStatus.FAILED, RunStatus.UNKNOWN, RunStatus.UNPUSHED, RunStatus.CRASHED, RunStatus.TIMEOUT},
)
_FAILED: dict[Kind, frozenset[str]] = {
    "overseer": frozenset(TickStatus) - {TickStatus.RUNNING, TickStatus.OK},
    "workers": _WORKER_FAILED,
    "plans": _WORKER_FAILED,
    "chores": frozenset(ChoreRunStatus) - {ChoreRunStatus.RUNNING, ChoreRunStatus.OK},
    "reviews": frozenset(ReviewRunStatus) - {ReviewRunStatus.RUNNING, ReviewRunStatus.DONE},
    # A task's run fails as a worker's does (DESIGN §36).
    "tasks": _WORKER_FAILED,
}
# Each kind's runs as one shape: its id, what it was (a tick's `live` or `dry run`, a run's kind, a chore's name, or
# `review`), its status, when it started and ended, what it was about, its note, and its cost. A plan run is a row of
# `runs`, a kind of its own, an old triage among them, as `canopy spend` counts them. The tables are fixed, never input,
# and each is built from literal SQL (D125).
_RUN_ROWS = sql.select(
    "id, kind AS what, status, started_at, ended_at, ticket_key AS subject, result_json AS note, cost_usd",
).from_("runs")
_PLAN_KINDS = (RunKind.PLAN, RunKind.NEEDS_PLAN)
_ROWS: Mapping[Kind, sql.Select] = {
    "overseer": sql.select(
        "id, CASE WHEN dry_run THEN 'dry run' WHEN overseer_ran = 0 THEN 'no overseer' ELSE 'live' END AS what, "
        "status, started_at, ended_at, NULL AS subject, summary AS note, cost_usd",
    ).from_("ticks"),
    "workers": _RUN_ROWS.where_not_in("kind", _PLAN_KINDS),
    "plans": _RUN_ROWS.where_in("kind", _PLAN_KINDS),
    "chores": sql.select(
        "id, chore AS what, status, started_at, ended_at, NULL AS subject, result_json AS note, cost_usd",
    ).from_("chore_runs"),
    "reviews": sql.select(
        "id, 'review' AS what, status, started_at, ended_at, pr_url AS subject, result_json AS note, cost_usd",
    ).from_("review_runs"),
    "tasks": sql.select(
        "id, 'task' AS what, status, started_at, ended_at, 'task:' || task_id AS subject, result_json AS note, "
        "cost_usd",
    ).from_("task_runs"),
}
#: What each band of `Bins` holds: a run whose length, over its kind's limit, is under the first, then the next; a run
#: at or past its limit is over it.
BANDS = (0.25, 0.5, 0.75, 1.0)
# A tick that ran no overseer has no timeout of its own.
_NO_OVERSEER = "no overseer"


@dataclass(frozen=True)
class Outcome:
    """How many of one kind's runs that started in the window, of one sort, ended in one status, and what they cost.

    `what` is the sort: `live`, `dry run`, or `no overseer` (§39) for a tick, the run's kind for a worker (`implement`,
    `plan`), the chore's name, or `review`. `failed` says the status is one the run did not end in as it should have.
    """

    kind: Kind
    what: str
    status: str
    failed: bool
    runs: int
    cost_usd: float | None


@dataclass(frozen=True)
class Failure:
    """One run of the window that ended in a failed status (`Outcome.failed`), for `canopy show` to read whole.

    `id` is the tick's for the overseer and the run's otherwise (`canopy decisions ID`, `canopy show run:ID`).
    `subject` is the worker's ticket or the review's PR, None for a tick or a chore. `note` is the tick's summary or
    the result's harness note or summary, on one line and cut to `NOTE_LIMIT`: agents wrote some of it, so it is data.
    """

    kind: Kind
    id: int
    what: str
    status: str
    started_at: str
    subject: str | None
    note: str
    cost_usd: float | None


@dataclass(frozen=True)
class Cause:
    """The window's failures that the harness explained alike: one of its notes, or `other` for the agents' own words.

    A failure's note is the harness's when canopy wrote it, a tick's summary or a result's harness note, and those
    repeat, a template filled the same way; one an agent wrote, its summary, never does, so those are counted together.
    """

    #: The harness's note, on one line and cut as `Failure.note`; None for `other`: an agent's summary, or no note.
    note: str | None
    #: How many failed so.
    runs: int
    #: The kinds of run among them, in `spend.KINDS` order.
    kinds: Sequence[Kind]
    #: The newest of them, to open.
    latest: Failure


@dataclass(frozen=True)
class Ask:
    """One thing the overseer, or the harness, asked for that a guard refused in the window, and how often."""

    #: The ticket it named; None for a chore's run, or a review of a PR no ticket of the loop's holds.
    ticket: str | None
    #: The chore it would have run; None for the rest.
    chore: str | None
    #: The PR it named, for a review; None for the rest.
    pr: str | None
    #: The kind of run a dispatch asked for; None for any other ask, and for a refusal recorded before it was kept.
    kind: RunKind | None
    #: How many of the guard's decisions refused it.
    decisions: int
    #: The latest tick that asked for it.
    last_tick: int


@dataclass(frozen=True)
class Refusal:
    """How often a guard refused what a tick asked for in the window (DESIGN §4): its decisions and their ticks."""

    guard: str
    decisions: int
    ticks: int
    last_tick: int
    #: What it refused most often, at most `ASKS`, the most often first, then the latest.
    asks: Sequence[Ask] = ()


@dataclass(frozen=True)
class Health:
    """The window's runs by how they ended, its newest failures, and its refusals, as `canopy health` reports them.

    The window is `spend.breakdown`'s, `[since, until)`. `outcomes` is in `spend.KINDS` order, then by sort and status;
    `failures` the newest first, at most `FAILURES`; `refusals` the most frequent first.
    """

    since: str
    until: str
    days: int
    outcomes: Sequence[Outcome] = ()
    failures: Sequence[Failure] = ()
    refusals: Sequence[Refusal] = ()
    #: Every failure of the window by its cause: the harness's notes the most runs first, then the newest, and `other`
    #: last.
    causes: Sequence[Cause] = ()

    @property
    def ended(self) -> int:
        """The window's runs that ended, of every kind."""
        return sum(o.runs for o in self.outcomes)

    @property
    def failed(self) -> int:
        """Of those, the ones that ended in a failed status."""
        return sum(o.runs for o in self.outcomes if o.failed)

    @property
    def failed_cost_usd(self) -> float | None:
        """What the failed ones cost; None when none of them reported a cost."""
        costs = [o.cost_usd for o in self.outcomes if o.failed and o.cost_usd is not None]
        return sum(costs) if costs else None


@dataclass(frozen=True)
class Bins:
    """A sort's ended runs by their length's share of its limit, in the bands of `BANDS`."""

    #: Under a quarter of it.
    under_quarter: int = 0
    #: From a quarter to under half.
    under_half: int = 0
    #: From half to under three quarters.
    under_three_quarters: int = 0
    #: From three quarters to under the limit.
    under_limit: int = 0
    #: At the limit or past it: a run timed out, or the harness took a while to stop it.
    over_limit: int = 0


@dataclass(frozen=True)
class Duration:
    """How long one sort of run took, of those that started in the window and ended, against its kind's timeout."""

    kind: Kind
    #: The sort, as `Outcome.what` names it.
    what: str
    #: How many ended.
    runs: int
    #: Their median length.
    median_minutes: float
    #: The length nine in ten of them came in at or under, by nearest rank.
    p90_minutes: float
    #: The longest of them.
    longest_minutes: float
    #: How many ended `timeout`.
    timeouts: int
    #: The timeout, in minutes, from `[runtime]` or the chore's own; None for a sort with none, a tick that ran no
    #: overseer or a chore no longer in the config.
    limit_minutes: int | None
    #: The runs by their share of the limit; None when there is no limit.
    bins: Bins | None


@dataclass(frozen=True)
class Day:
    """One local day of the window: how many of each kind's runs that started in it ended, and how many failed.

    Every kind in `spend.KINDS` is in both, 0 for none; a run still running has not ended any way yet.
    """

    #: The day, `YYYY-MM-DD`, as `spend.local_day` names it.
    day: str
    #: When it starts: its local midnight, a journal time.
    start: str
    #: Each kind's runs that ended, by kind.
    ended: Mapping[Kind, int]
    #: Each kind's runs that ended in a failed status (`Outcome.failed`), by kind.
    failed: Mapping[Kind, int]


def report(conn: sqlite3.Connection, now: datetime, days: int) -> Health:
    """How the runs of the last `days` local days ended, today's so far included, and what guards refused.

    Returns:
        The report; a window with nothing in it has empty lists.
    """
    return between(conn, *spend.window(now, days))


def between(conn: sqlite3.Connection, start: datetime, end: datetime) -> Health:
    """How the runs that started from one local midnight, `start`, to another, `end`, ended, and what guards refused.

    Returns:
        The report, as `report` gives it for any such window: a calendar month's, or the one before a page's.
    """
    since = db.format_time(start)
    until = db.format_time(end)
    days = spend.days_between(start, end)
    with db.read_snapshot(conn):
        outcomes = [o for kind in spend.KINDS for o in _outcomes(conn, kind, since, until)]
        failed = [f for kind in spend.KINDS for f in _failures(conn, kind, since, until)]
        refused = refusals(conn, since, until)
    failed.sort(key=lambda f: (f[0].started_at, spend.KINDS.index(f[0].kind), f[0].id), reverse=True)
    return Health(
        since=since,
        until=until,
        days=days,
        outcomes=outcomes,
        failures=[f for f, _ in failed[:FAILURES]],
        refusals=refused,
        causes=_causes(failed),
    )


def by_day(conn: sqlite3.Connection, now: datetime, days: int) -> list[Day]:
    """How many runs of the last `days` local days ended, and failed, each day, by kind, over `report`'s window.

    Returns:
        Every day of the window, oldest first, a day with nothing in it among them.
    """
    start, end = spend.window(now, days)
    starts = spend.day_starts(start, days)
    since = db.format_time(start)
    until = db.format_time(end)
    ended: dict[str, dict[Kind, int]] = {day: dict.fromkeys(spend.KINDS, 0) for day in starts}
    failed: dict[str, dict[Kind, int]] = {day: dict.fromkeys(spend.KINDS, 0) for day in starts}
    with db.read_snapshot(conn):
        for kind in spend.KINDS:
            counted = (
                sql.select("{} AS day, status, count(*)", spend.DAY)
                .from_("({})", _ROWS[kind])
                .where("started_at >= ? AND started_at < ? AND status != 'running'", since, until)
                .group_by("day, status")
            )
            for day, status, runs in sql.execute(conn, counted):
                # A day the clock puts outside the window's names is in none of them, as `spend` leaves it.
                if str(day) not in ended:
                    continue
                ended[str(day)][kind] += int(runs)
                if str(status) in _FAILED[kind]:
                    failed[str(day)][kind] += int(runs)
    return [Day(day=day, start=at, ended=ended[day], failed=failed[day]) for day, at in starts.items()]


def durations(conn: sqlite3.Connection, now: datetime, days: int, config: Config) -> list[Duration]:
    """How long the runs of the last `days` local days took, by kind and sort, over `report`'s window, by start.

    A tick is held to the overseer's timeout; a worker, a plan, and a task's run to the worker's, a review to the
    reviewer's, and a chore to its own, as `config` sets them.

    Returns:
        A row per sort that ended a run, in `spend.KINDS` order, then by sort.
    """
    start, end = spend.window(now, days)
    since = db.format_time(start)
    until = db.format_time(end)
    lengths: dict[tuple[Kind, str], list[tuple[float, bool]]] = {}
    with db.read_snapshot(conn):
        for kind in spend.KINDS:
            ended = (
                sql.select("what, (julianday(ended_at) - julianday(started_at)) * 1440, status = 'timeout'")
                .from_("({})", _ROWS[kind])
                .where("started_at >= ? AND started_at < ?", since, until)
                .where("status != 'running' AND ended_at IS NOT NULL")
                .order_by("what")
            )
            for what, minutes, timed_out in sql.execute(conn, ended):
                if minutes is not None:
                    lengths.setdefault((kind, str(what)), []).append((max(float(minutes), 0.0), bool(timed_out)))
    return [_duration(kind, what, ran, _limit(config, kind, what)) for (kind, what), ran in lengths.items()]


def refusals(conn: sqlite3.Connection, since: str, until: str) -> list[Refusal]:
    """What each guard refused the overseer in `[since, until)`, each a journal time, by when the decision was made.

    Returns:
        A row per guard, the most frequent first, each with what it refused most often.
    """
    window = ("action LIKE ? AND created_at >= ? AND created_at < ?", f"{REFUSED}%", since, until)
    refused = (
        sql.select("substr(action, ?), count(*), count(DISTINCT tick_id), max(tick_id)", len(REFUSED) + 1)
        .from_("decisions")
        .where(*window)
        .group_by("action")
        .order_by("count(*) DESC, action")
    )
    # What each guard refused, by what the decision named, the most often first; a guard's first `ASKS` are its asks.
    named = (
        sql.select("substr(action, ?), ticket_key, chore, pr, kind, count(*), max(tick_id)", len(REFUSED) + 1)
        .from_("decisions")
        .where(*window)
        .group_by("action, ticket_key, chore, pr, kind")
        .order_by("count(*) DESC, max(tick_id) DESC")
    )
    with db.read_snapshot(conn):
        rows = list(sql.execute(conn, refused))
        asks: dict[str, list[Ask]] = {}
        for guard, ticket, chore, pr, kind, n, last in sql.execute(conn, named):
            found = asks.setdefault(str(guard), [])
            if len(found) < ASKS:
                found.append(
                    Ask(
                        ticket=_text(ticket),
                        chore=_text(chore),
                        pr=_text(pr),
                        kind=None if kind is None else RunKind(str(kind)),
                        decisions=int(n),
                        last_tick=int(last),
                    ),
                )
    return [
        Refusal(
            guard=str(guard),
            decisions=int(n),
            ticks=int(ticks),
            last_tick=int(last),
            asks=asks.get(str(guard), []),
        )
        for guard, n, ticks, last in rows
    ]


# One kind's ended runs in the window, by sort and status. A run still running has not ended any way yet.
def _outcomes(conn: sqlite3.Connection, kind: Kind, since: str, until: str) -> list[Outcome]:
    ended = (
        sql.select("what, status, count(*), SUM(cost_usd)")
        .from_("({})", _ROWS[kind])
        .where("started_at >= ? AND started_at < ? AND status != 'running'", since, until)
        .group_by("what, status")
        .order_by("what, status")
    )
    rows = sql.execute(conn, ended)
    return [
        Outcome(
            kind=kind,
            what=str(what),
            status=str(status),
            failed=str(status) in _FAILED[kind],
            runs=int(runs),
            cost_usd=cost,
        )
        for what, status, runs, cost in rows
    ]


def _duration(kind: Kind, what: str, ran: Sequence[tuple[float, bool]], limit: int | None) -> Duration:
    minutes = sorted(m for m, _ in ran)
    bins = None
    if limit is not None:
        counts = [0] * (len(BANDS) + 1)
        for m in minutes:
            counts[bisect.bisect_right(BANDS, m / limit)] += 1
        bins = Bins(*counts)
    return Duration(
        kind=kind,
        what=what,
        runs=len(minutes),
        median_minutes=statistics.median(minutes),
        p90_minutes=minutes[math.ceil(0.9 * len(minutes)) - 1],
        longest_minutes=minutes[-1],
        timeouts=sum(timed_out for _, timed_out in ran),
        limit_minutes=limit,
        bins=bins,
    )


# The timeout a sort of run is held to: the overseer's for a tick that ran it, the worker's for every run of a worker's
# agent, the reviewer's, and a chore's own.
def _limit(config: Config, kind: Kind, what: str) -> int | None:
    runtime = config.runtime
    match kind:
        case "overseer":
            return None if what == _NO_OVERSEER else runtime.overseer_timeout_minutes
        case "workers" | "plans" | "tasks":
            return runtime.worker_timeout_minutes
        case "reviews":
            return runtime.review_timeout_minutes
        case "chores":
            chore = config.chores.get(what)
            return None if chore is None else chore.timeout_minutes
        case _:
            assert_never(kind)


# Every failure of one kind in the window, the newest first, each with its cause: the harness's note, or None.
def _failures(conn: sqlite3.Connection, kind: Kind, since: str, until: str) -> Iterable[tuple[Failure, str | None]]:
    failed = (
        sql.select("id, what, status, started_at, subject, note, cost_usd")
        .from_("({})", _ROWS[kind])
        .where("started_at >= ? AND started_at < ?", since, until)
        .where_in("status", sorted(_FAILED[kind]))
        .order_by("started_at DESC, id DESC")
    )
    rows = sql.execute(conn, failed)
    for run_id, what, status, started, subject, stored, cost in rows:
        note, harness = _note(kind, stored)
        failure = Failure(
            kind=kind,
            id=int(run_id),
            what=str(what),
            status=str(status),
            started_at=str(started),
            subject=None if subject is None else str(subject),
            note=note,
            cost_usd=cost,
        )
        yield failure, note if harness and note else None


# A tick's note is its summary, canopy's, which quotes the overseer's reason for a skip; a run's is in its stored
# result, the harness's note or else the agent's summary. The note on one line, and whether the harness wrote it.
def _note(kind: Kind, stored: object) -> tuple[str, bool]:
    if kind == "overseer":
        return _one_line(str(stored or "")), True
    result = contract.stored_object(_text(stored))
    return _one_line(contract.stored_note(result)), bool(result.get("harness"))


# The failures, the newest first, by their cause: the harness's notes the most runs first, then the newest, then the
# rest as `other`.
def _causes(failed: Sequence[tuple[Failure, str | None]]) -> list[Cause]:
    grouped: dict[str | None, list[Failure]] = {}
    for failure, cause in failed:
        grouped.setdefault(cause, []).append(failure)
    causes = [
        Cause(
            note=note,
            runs=len(runs),
            kinds=[k for k in spend.KINDS if any(f.kind == k for f in runs)],
            latest=runs[0],
        )
        for note, runs in grouped.items()
    ]
    # `grouped` is in the order each cause's newest failure came, so a stable sort keeps the newest first among ties.
    causes.sort(key=lambda c: (c.note is None, -c.runs))
    return causes


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _one_line(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= NOTE_LIMIT else text[: NOTE_LIMIT - 3] + "..."
