"""What each local calendar month cost and got done (DESIGN §11), for the web UI's reports.

Reads only. A month's cost and tokens are what the agent runtime reported (§13) of each kind of run that started in
it, as `spend` counts them: the overseer of each tick, dry runs' among them, worker runs, plan runs, chore runs, review
runs, and task runs; and beside them the runtime's sessions outside canopy, as `runtime_sessions` tells them from
canopy's, so a month's cost and tokens are all its agent spend, as the budget counts it. Beside them, what the month
got done: the tickets marked done as merged in it, each with the
worker runs it took, the comments and reviews people other than the PR's author left on its PRs, how long it took
from its first worker run, and how long its PR waited for its first review. Each of those two ends at GitHub's times
where the `vcs` source read them (DESIGN §30): a ticket lands when its PRs merged, and its PR waits from when a review
of it was first asked for once it was ready, or from when it was ready. Where a PR has no such time read, as one read
before canopy read them, a proxy stands in: the tick that marked the ticket done, and the end of its first worker run
that ended `done`, until `canopy backfill` reads the PR's times. There is no history of a ticket's phase.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from canopy.core import contract, db, pr_feedback, records, run_models, runtime_sessions, sql, tracked_prs
from canopy.core.spend import KIND_TABLES, KINDS, done_in
from canopy.core.vocab import PrState, ReviewState, RunKind, RunStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from canopy.core.spend import Kind

#: The most months a report reads, and how many it reads unless asked.
MAX_MONTHS = 24
DEFAULT_MONTHS = 12

# A worker's attempt at a ticket's code: what a ticket's iterations count. A plan, a feedback plan, or an old split
# writes no code of the ticket's.
_WORK_KINDS = (RunKind.IMPLEMENT, RunKind.FIX_CI, RunKind.RESUME)
# The local month a row started in, as `YYYY-MM`: SQLite reads the journal's UTC time in the local time Python does.
_MONTH_FORMAT = "%Y-%m"
# A month's row by model: its model, and for no model, whether its runs are unread.
type _ModelKey = tuple[str | None, bool]


@dataclass(frozen=True)
class Tokens:
    """The tokens a month's runs reported, by kind, summed over their model calls; 0 where none reported any."""

    input: int = 0
    output: int = 0
    reasoning: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def sent(self) -> int:
        """What the model calls were sent, read from the cache or not."""
        return self.input + self.cache_read + self.cache_write

    @property
    def cache_hit(self) -> float | None:
        """The share of what was sent that was read from the cache; None when nothing was sent."""
        return self.cache_read / self.sent if self.sent else None

    def plus(self, other: Tokens) -> Tokens:
        """These tokens and `other`'s, summed.

        Returns:
            The sum, kind by kind.
        """
        return Tokens(
            input=self.input + other.input,
            output=self.output + other.output,
            reasoning=self.reasoning + other.reasoning,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
        )


@dataclass(frozen=True)
class KindMonth:
    """What one kind of run cost in a month."""

    kind: Kind
    #: How many of its runs started in the month: for the overseer, its ticks.
    runs: int
    #: What they cost, in US dollars; None when none of them reported a cost.
    cost_usd: float | None
    tokens: Tokens


@dataclass(frozen=True)
class Outside:
    """What the runtime's sessions outside canopy cost in a month: the operator's own, and other workspaces' runs."""

    #: How many started in the month.
    sessions: int = 0
    #: What they cost, in US dollars; None when none started.
    cost_usd: float | None = None
    tokens: Tokens = Tokens()


@dataclass(frozen=True)
class ModelMonth:
    """What one model's replies cost in a month, over every kind of run, as the runs' sessions name it (§13)."""

    #: The model; None for the runs no session named one for, at what they reported they cost, in two rows by `unread`.
    model: str | None
    #: The runs it wrote a reply of: a run on two models counts under each.
    runs: int
    replies: int
    cost_usd: float | None
    #: For a row of no model, whether canopy has yet to read its runs' sessions (`run_models.unread`); False for the
    #: runs read that named none, and for a model's row.
    unread: bool = False


@dataclass(frozen=True)
class Landed:
    """A ticket the loop marked done as merged in a month, and what getting there took."""

    key: str
    title: str | None
    #: When the loop marked it done, a journal time.
    landed_at: str
    #: When its first worker run started, a journal time; None for a ticket that landed with none.
    started_at: str | None
    #: Its worker runs, implement and resume, that started before it landed.
    iterations: int
    #: The comments on its PRs from people other than each PR's author: canopy posts as the author, so not its own.
    pr_comments: int
    #: The reviews of its PRs from people other than each PR's author, and how many of them asked for changes.
    reviews: int
    changes_requested: int
    #: What its runs and review runs that started before it landed cost; None when none reported a cost.
    cost_usd: float | None
    #: From its first worker run's start to its landing, its PRs' merge when known; None with no worker run.
    to_land: timedelta | None
    #: From when its PR began waiting on a review, or the end of its first worker run that ended `done`, to the first
    #: review after it; None with no start or no such review.
    review_wait: timedelta | None
    #: When its PRs merged, as GitHub says, the latest of them, where `to_land` ends; None when one merged with no merge
    #: time read, and `to_land` ends at `landed_at` instead.
    merged_at: str | None = None
    #: When its PRs began waiting on a review, as GitHub says: the first review asked for once one was ready, or when it
    #: was ready, the earliest of them, where `review_wait` starts; None when none has either time read, and it starts
    #: at the end of its first worker run that ended `done` instead.
    awaiting_review_at: str | None = None
    #: Its PRs, by URL, in order: those its units hold and those its runs named.
    pull_requests: Sequence[str] = ()


@dataclass(frozen=True)
class Month:
    """One local calendar month: what each kind of run cost, by model, and the tickets it landed."""

    #: The month, as `YYYY-MM`.
    month: str
    #: When it starts and ends, each a journal time: its first local midnight and the next month's.
    since: str
    until: str
    #: Each kind in `spend.KINDS` order, one that ran nothing among them.
    kinds: Sequence[KindMonth]
    #: The costliest first, the runs no session named a model for last, those unread before the rest.
    models: Sequence[ModelMonth]
    #: The latest first.
    landed: Sequence[Landed]
    #: How many tickets the loop marked done as closed in it, without a merge.
    closed: int
    #: How many PRs a run first named in it.
    pull_requests: int
    #: The runtime's sessions outside canopy that started in it.
    outside: Outside = Outside()

    @property
    def runs(self) -> int:
        """How many runs of every kind started in the month, a tick each for the overseer."""
        return sum(k.runs for k in self.kinds)

    @property
    def runs_cost_usd(self) -> float | None:
        """What every kind of canopy's runs cost, dry runs included; None when none reported."""
        return _sum(k.cost_usd for k in self.kinds)

    @property
    def cost_usd(self) -> float | None:
        """What every kind and the sessions outside canopy cost, as the budget counts a month; None when none did."""
        return _sum([self.runs_cost_usd, self.outside.cost_usd])

    @property
    def tokens(self) -> Tokens:
        """Every kind's tokens and the sessions outside canopy's, summed."""
        total = self.outside.tokens
        for k in self.kinds:
            total = total.plus(k.tokens)
        return total

    @property
    def per_landed(self) -> float | None:
        """What canopy's runs cost over the tickets the month landed; None with none landed, or no cost.

        The sessions outside canopy are left out: they landed nothing canopy knows of.
        """
        cost = self.runs_cost_usd
        return cost / len(self.landed) if self.landed and cost is not None else None


def months(conn: sqlite3.Connection, now: datetime, count: int = DEFAULT_MONTHS, *, state_dir: Path) -> list[Month]:
    """The last `count` local calendar months, the one holding `now` so far included, the oldest first.

    `state_dir` is the workspace's: a session of the runtime's that ran in it is canopy's, not outside.

    Returns:
        Each month, one with nothing in it among them.
    """
    firsts = _firsts(now.astimezone().date().replace(day=1), count)
    bounds = [(f.strftime(_MONTH_FORMAT), _midnight(f), _midnight(_next(f))) for f in firsts]
    since, until = bounds[0][1], bounds[-1][2]
    with db.read_snapshot(conn):
        kinds = _kinds(conn, since, until)
        models = _models(conn, since, until)
        prs = tracked_prs.tracked(conn, since, until)
        done = done_in(conn, since, until)
        landed = _landed(conn, {k: at for k, (how, at) in done.items() if how == "merged"})
        outside = _outside(conn, since, until, state_dir)
    closed = [_month_of(at) for how, at in done.values() if how == "closed"]
    return [
        Month(
            month=name,
            since=start,
            until=end,
            kinds=[
                kinds.get((name, kind), KindMonth(kind=kind, runs=0, cost_usd=None, tokens=Tokens())) for kind in KINDS
            ],
            models=_costliest(models.get(name, {})),
            landed=sorted(
                (t for t in landed if _month_of(t.landed_at) == name),
                key=lambda t: t.landed_at,
                reverse=True,
            ),
            closed=closed.count(name),
            pull_requests=sum(1 for pr in prs.values() if _month_of(pr.first_named) == name),
            outside=outside.get(name, Outside()),
        )
        for name, start, end in bounds
    ]


def median(values: Iterable[float | None]) -> float | None:
    """The median of the values that are not None.

    Returns:
        It, or None when every one is.
    """
    known = [v for v in values if v is not None]
    return statistics.median(known) if known else None


# The first day of `count` months, ending with `last`'s, the oldest first.
def _firsts(last: date, count: int) -> list[date]:
    index = last.year * 12 + last.month - 1
    return [date((i // 12), i % 12 + 1, 1) for i in range(index - count + 1, index + 1)]


def _next(first: date) -> date:
    return (first + timedelta(days=32)).replace(day=1)


# A day's local midnight, as a journal time. A naive time's `astimezone` reads it in this machine's local time.
def _midnight(day: date) -> str:
    return db.format_time(datetime.combine(day, time()).astimezone())


# The local month a journal time is in.
def _month_of(stamp: str) -> str:
    return db.parse_time(stamp).astimezone().strftime(_MONTH_FORMAT)


def _bucket(column: sql.Fragment) -> sql.Fragment:
    return sql.frag("strftime(?, {}, 'localtime')", _MONTH_FORMAT, column)


# Each kind's runs by the month they started in. The run table's `_spent` index on `started_at` leads.
def _kinds(conn: sqlite3.Connection, since: str, until: str) -> dict[tuple[str, Kind], KindMonth]:
    found: dict[tuple[str, Kind], KindMonth] = {}
    for kind, (table, which) in KIND_TABLES.items():
        by_month = (
            sql.select(
                "{} AS month, count(*), SUM(cost_usd), TOTAL(tokens_input), TOTAL(tokens_output), "
                "TOTAL(tokens_reasoning), TOTAL(tokens_cache_read), TOTAL(tokens_cache_write)",
                _bucket(sql.frag("started_at")),
            )
            .from_("{}", sql.name(table))
            .where("{}", which)
            .where("started_at >= ? AND started_at < ?", since, until)
            .group_by("month")
        )
        for month, runs, cost, sent, out, thought, read, written in sql.execute(conn, by_month):
            tokens = Tokens(
                input=int(sent),
                output=int(out),
                reasoning=int(thought),
                cache_read=int(read),
                cache_write=int(written),
            )
            found[str(month), kind] = KindMonth(kind=kind, runs=int(runs), cost_usd=cost, tokens=tokens)
    return found


# The runtime's sessions outside canopy by the month they started in.
def _outside(conn: sqlite3.Connection, since: str, until: str, state_dir: Path) -> dict[str, Outside]:
    by_month = (
        sql.select(
            "{} AS month, count(*), SUM(cost_usd), TOTAL(tokens_input), TOTAL(tokens_output), "
            "TOTAL(tokens_reasoning), TOTAL(tokens_cache_read), TOTAL(tokens_cache_write)",
            _bucket(sql.frag("started_at")),
        )
        .from_("({}) AS s", runtime_sessions.sessions_in(since, until, state_dir))
        .where("NOT ours")
        .group_by("month")
    )
    return {
        str(month): Outside(
            sessions=int(count),
            cost_usd=cost,
            tokens=Tokens(
                input=int(sent),
                output=int(out),
                reasoning=int(thought),
                cache_read=int(read),
                cache_write=int(written),
            ),
        )
        for month, count, cost, sent, out, thought, read, written in sql.execute(conn, by_month)
    }


# Each month's spend by model, every kind's summed, read as `spend` reads a kind's: the run table leads, and
# `run_models` is read by its key's prefix. Then the runs no session named a model for, under None, those canopy has
# yet to read apart from the rest.
def _models(conn: sqlite3.Connection, since: str, until: str) -> dict[str, dict[_ModelKey, ModelMonth]]:
    found: dict[str, dict[_ModelKey, ModelMonth]] = {}

    def add(month: str, model: str | None, runs: int, replies: int, cost: float | None, *, unread: bool) -> None:
        had = found.setdefault(month, {}).get((model, unread))
        if had is not None:
            runs, replies, cost = had.runs + runs, had.replies + replies, _sum([had.cost_usd, cost])
        found[month][model, unread] = ModelMonth(model=model, runs=runs, replies=replies, cost_usd=cost, unread=unread)

    for table, which in KIND_TABLES.values():
        named = (
            sql.select(
                "{} AS month, m.model, count(*), SUM(m.replies), SUM(m.cost_usd)",
                _bucket(sql.frag("r.started_at")),
            )
            .from_("{} r CROSS JOIN run_models m ON m.run_table = ? AND m.run_id = r.id", sql.name(table), table)
            .where("r.started_at >= ? AND r.started_at < ?", since, until)
            .where("{}", which)
            .group_by("month, m.model")
        )
        for month, model, runs, replies, cost in sql.execute(conn, named):
            add(str(month), str(model), int(runs), int(replies), cost, unread=False)
        unnamed = (
            sql.select(
                "{} AS month, {} AS unread, count(*), SUM(r.cost_usd)",
                _bucket(sql.frag("r.started_at")),
                run_models.unread(table),
            )
            .from_("{} r", sql.name(table))
            .where("r.started_at >= ? AND r.started_at < ?", since, until)
            .where("{}", which)
            .where("NOT EXISTS (SELECT 1 FROM run_models m WHERE m.run_table = ? AND m.run_id = r.id)", table)
            .group_by("month, unread")
        )
        for month, unread, runs, cost in sql.execute(conn, unnamed):
            add(str(month), None, int(runs), 0, cost, unread=bool(unread))
    return found


def _costliest(models: Mapping[_ModelKey, ModelMonth]) -> list[ModelMonth]:
    return sorted(
        models.values(),
        key=lambda m: (m.model is None, not m.unread, -(m.cost_usd or 0.0), m.model or ""),
    )


@dataclass(frozen=True)
class _Run:
    """A run on a landed ticket, or a review run of it."""

    kind: str | None
    started_at: datetime
    ended_at: datetime | None
    status: str
    cost_usd: float | None
    prs: Sequence[str]


# Each ticket that landed, by when, with what getting it there took.
def _landed(conn: sqlite3.Connection, landed: Mapping[str, str]) -> list[Landed]:
    keys = json.dumps(sorted(landed))
    in_keys = sql.frag("ticket_key IN (SELECT value FROM json_each(?))", keys)
    titled = sql.select("key, title").from_("tickets").where("key IN (SELECT value FROM json_each(?))", keys)
    titles = {str(key): None if title is None else str(title) for key, title in sql.execute(conn, titled)}
    runs: dict[str, list[_Run]] = {}
    of_runs = sql.select("ticket_key, kind, started_at, ended_at, status, cost_usd, result_json").from_("runs")
    of_reviews = sql.select("ticket_key, NULL, started_at, ended_at, status, cost_usd, NULL").from_("review_runs")
    for select in (of_runs.where("{}", in_keys), of_reviews.where("{}", in_keys)):
        for key, kind, started, ended, status, cost, result in sql.execute(conn, select):
            named = () if result is None else tuple(contract.stored_prs(contract.stored_object(result)))
            runs.setdefault(str(key), []).append(
                _Run(
                    kind=None if kind is None else str(kind),
                    started_at=db.parse_time(str(started)),
                    ended_at=None if ended is None else db.parse_time(str(ended)),
                    status=str(status),
                    cost_usd=cost,
                    prs=named,
                ),
            )
    units = sql.select("ticket_key, pr_url").from_("ticket_units").where("{} AND pr_url IS NOT NULL", in_keys)
    prs: dict[str, set[str]] = {}
    for key, url in sql.execute(conn, units):
        prs.setdefault(str(key), set()).add(str(url))
    for key, found in runs.items():
        prs.setdefault(key, set()).update(url for run in found for url in run.prs)
    urls = sorted({url for found in prs.values() for url in found})
    reviews = pr_feedback.feedback(conn, urls)
    observed = {p.url: p for p in records.select(records.ObservedPr).where_in("url", urls).all(conn)}
    return [
        _ticket(
            key,
            titles.get(key),
            at,
            runs.get(key, []),
            said=[r for url in sorted(prs.get(key, ())) for r in reviews.get(url, [])],
            prs=[observed[url] for url in sorted(prs.get(key, ())) if url in observed],
            urls=sorted(prs.get(key, ())),
        )
        for key, at in landed.items()
    ]


def _ticket(
    key: str,
    title: str | None,
    landed_at: str,
    runs: Sequence[_Run],
    *,
    said: Sequence[pr_feedback.Feedback],
    prs: Sequence[records.ObservedPr],
    urls: Sequence[str],
) -> Landed:
    landed = db.parse_time(landed_at)
    before = sorted((r for r in runs if r.started_at <= landed), key=lambda r: r.started_at)
    work = [r for r in before if r.kind in _WORK_KINDS]
    judged = [r for r in said if r.judged]
    merged = _merged(prs)
    # Each PR's start, as GitHub says: a review of it asked for once ready, or its ready time.
    starts = {p.url: db.parse_time(start) for p in prs if (start := pr_feedback.waiting_since(p)) is not None}
    awaiting = min(starts.values(), default=None)
    # Without GitHub's times, a PR of the ticket is ready when its first worker run ends `done`.
    ready = next((r.ended_at for r in work if r.status == RunStatus.DONE and r.ended_at is not None), None)
    # Each PR starts on GitHub's clock where the reader kept it, else on the proxy: a PR read before canopy kept its
    # times still counts its reviews beside one read after.
    begun = {url: starts.get(url) or ready for url in {p.url for p in prs} | {r.pr_url for r in judged}}
    waited_from = min((start for start in begun.values() if start is not None), default=None)
    first_review = _first_review(judged, begun)
    return Landed(
        key=key,
        title=title,
        landed_at=landed_at,
        started_at=db.format_time(work[0].started_at) if work else None,
        iterations=len(work),
        pr_comments=sum(1 for r in said if not r.judged),
        reviews=len(judged),
        changes_requested=sum(1 for r in judged if r.state is ReviewState.CHANGES_REQUESTED),
        cost_usd=_sum(r.cost_usd for r in before),
        to_land=(merged or landed) - work[0].started_at if work else None,
        review_wait=first_review - waited_from if first_review is not None and waited_from is not None else None,
        merged_at=None if merged is None else db.format_time(merged),
        awaiting_review_at=None if awaiting is None else db.format_time(awaiting),
        pull_requests=tuple(urls),
    )


def _first_review(
    judged: Sequence[pr_feedback.Feedback],
    starts: Mapping[str, datetime | None],
) -> datetime | None:
    """The first review at or after its PR's start; a review of a PR with no start counts for nothing.

    Returns:
        Its time; None with no such review.
    """
    firsts = (
        pr_feedback.first_review([r for r in judged if r.pr_url == url], db.format_time(start))
        for url, start in starts.items()
        if start is not None
    )
    return min(
        (db.parse_time(r.created_at) for r in firsts if r is not None and r.created_at is not None),
        default=None,
    )


def _merged(prs: Sequence[records.ObservedPr]) -> datetime | None:
    """When a landed ticket's PRs merged, as GitHub says: the latest merge of those observed merged.

    Returns:
        It; None when none was observed merged, or one was with no merge time read.
    """
    merges = [p.merged_at for p in prs if p.state is PrState.MERGED]
    if not merges or None in merges:
        return None
    return max(db.parse_time(at) for at in merges if at is not None)


# The sum of the values that are not None; None when every one is.
def _sum(values: Iterable[float | None]) -> float | None:
    parts = [float(v) for v in values if v is not None]
    return sum(parts) if parts else None
