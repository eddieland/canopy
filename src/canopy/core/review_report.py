"""Where review feedback came from and what answering it cost (DESIGN §11), for the web UI's Reviews page.

Reads only. Over the same window as `canopy spend` and `canopy health` (whole local days, today's so far included): the
PRs a run named that canopy observed and that saw something in the window, a run that named them, feedback, becoming
ready, a review asked for, or a merge; the feedback people other than each PR's author left in it, not bots'
(`pr_feedback`, as the monthly report counts it), by reviewer; how long each first review that arrived in it took from
when its PR began waiting, on GitHub's clock; the feedback plans made in it, how each was approved, and the resumes that
followed; and canopy's own reviewer's runs, the findings the operator dismissed, and its drafts.

A PR read before canopy kept GitHub's times, or still a draft, has no start, so its first review is counted apart and
never mixed into a median. The journal keeps no history of a ticket's phase, so time spent red in CI or conflicted is
not here.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from canopy.core import db, pr_feedback, records, spend, sql, tracked_prs
from canopy.core.vocab import (
    DismissalReason,
    PlanEffort,
    PlanStatus,
    PrState,
    ReviewDraftStatus,
    ReviewRunStatus,
    ReviewState,
    RunKind,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable, Mapping, Sequence
    from datetime import datetime

    from canopy.core.vocab import Phase

#: Where the waits chart cuts a first review's wait: under an hour, under four, under a day, and the rest.
WAIT_BOUNDS = (timedelta(hours=1), timedelta(hours=4), timedelta(days=1))


@dataclass(frozen=True)
class ReviewedPr:
    """A PR in the window, with its feedback in it and what answering that cost."""

    url: str
    #: The ticket that owns it, and its unit's phase, as `tracked_prs` reads them.
    ticket: str
    phase: Phase | None
    #: When it last became ready for review, and when it merged, as GitHub says; None where the reader kept none.
    ready_at: str | None
    merged_at: str | None
    #: When it began waiting on a review (`pr_feedback.waiting_since`); None without GitHub's times, or a draft.
    waiting_since: str | None
    #: When the first review at or after that came, in the window or before it; None with no start, or none yet.
    first_review_at: str | None
    #: Its feedback made in the window: reviews, those of them that asked for changes, and comments.
    reviews: int
    changes_requested: int
    comments: int
    #: The feedback plans made in the window that read it.
    rounds: int
    #: What those plans' runs and the resumes that went ahead on them cost; None when none reported a cost.
    cost_usd: float | None

    @property
    def first_review(self) -> timedelta | None:
        """From when it began waiting to its first review; None without both."""
        if self.waiting_since is None or self.first_review_at is None:
            return None
        return db.parse_time(self.first_review_at) - db.parse_time(self.waiting_since)

    @property
    def to_merge(self) -> timedelta | None:
        """From when it last became ready to its merge; None without both."""
        if self.ready_at is None or self.merged_at is None:
            return None
        return db.parse_time(self.merged_at) - db.parse_time(self.ready_at)


@dataclass(frozen=True)
class Reviewer:
    """Someone who left feedback in the window on its PRs, by login, the most reviews first."""

    author: str
    reviews: int
    changes_requested: int
    comments: int
    #: The PRs they reviewed.
    prs: int
    #: The median, over the PRs they reviewed that have a start, of the wait from it to their first review at or after
    #: it; None with no such PR.
    median_wait: timedelta | None


@dataclass(frozen=True)
class Day:
    """One local day of the window: the first reviews that arrived on it, by how long each waited."""

    #: The day, `YYYY-MM-DD`, as `spend.local_day` names it.
    day: str
    #: When it starts: its local midnight, a journal time.
    start: str
    #: Its first reviews by wait, one count per bucket `WAIT_BOUNDS` cuts, the quickest first.
    first_reviews: Sequence[int]
    #: Their median wait; None with none.
    median_wait: timedelta | None


@dataclass(frozen=True)
class Round:
    """A feedback plan made in the window (DESIGN §32), the newest first, with the resumes that went ahead on it."""

    plan_id: int
    ticket: str
    #: The feedback plan run that wrote it.
    run_id: int
    created_at: str
    status: PlanStatus
    #: Through which channel it was approved, `web`, `cli`, or `planner` (`plans.PLANNER`); None while not approved.
    approved_channel: str | None
    #: How much work its planner judged it; None when it gave no estimate.
    effort: PlanEffort | None
    #: The PRs it read.
    prs: Sequence[str]
    #: What its own run cost; None when it reported none.
    plan_cost_usd: float | None
    #: The `resume` runs that went ahead on it, and what they cost; None when none reported a cost.
    resumes: int
    resume_cost_usd: float | None


@dataclass(frozen=True)
class Effort:
    """The window's feedback plans of one effort as their planner judged it, beside the resumes that followed them."""

    #: None for the plans whose planner gave no estimate.
    effort: PlanEffort | None
    plans: int
    resumes: int
    #: What those resumes cost; None when none reported a cost.
    resume_cost_usd: float | None


@dataclass(frozen=True)
class ReviewRuns:
    """canopy's review runs that started in the window, of one purpose and one status."""

    #: Why they ran: `own` for a PR of a ticket's, `request` for one the operator asked for, `query` for the rest.
    purpose: str
    status: ReviewRunStatus
    runs: int
    #: What they cost; None when none reported a cost.
    cost_usd: float | None


@dataclass(frozen=True)
class Dismissals:
    """The findings of canopy's reviews the operator dismissed in the window, for one reason."""

    #: None for a dismissal from before canopy asked why.
    reason: DismissalReason | None
    findings: int


@dataclass(frozen=True)
class Drafts:
    """The drafts of canopy's reviews made in the window that stand at one status (DESIGN §34)."""

    status: ReviewDraftStatus
    drafts: int


@dataclass(frozen=True)
class Reviews:
    """Where the window's review feedback came from, how long it took, and what answering it cost."""

    since: str
    until: str
    days: int
    #: The PRs a run last named first, then by URL.
    prs: Sequence[ReviewedPr]
    #: The most reviews first, then the most comments, then by login.
    reviewers: Sequence[Reviewer]
    per_day: Sequence[Day]
    #: The wait of each first review that arrived in the window on a PR with a start, the quickest first.
    waits: Sequence[timedelta]
    #: The window's PRs reviewed in it that have no start, so no wait: read before canopy kept GitHub's times, or a
    #: draft. Counted apart, never in a median.
    untimed: int
    #: The window's open PRs that began waiting and have no review yet.
    waiting: int
    rounds: Sequence[Round]
    #: The planner's estimates, `small` to `large`, then no estimate; each one with a plan in the window.
    efforts: Sequence[Effort]
    #: By purpose, then by status.
    review_runs: Sequence[ReviewRuns]
    #: The most first.
    dismissals: Sequence[Dismissals]
    #: The most first.
    drafts: Sequence[Drafts]

    @property
    def reviews(self) -> int:
        """The reviews made in the window on its PRs."""
        return sum(p.reviews for p in self.prs)

    @property
    def median_wait(self) -> timedelta | None:
        """The median wait of the first reviews that arrived in the window; None with none."""
        return _median(self.waits)


def report(conn: sqlite3.Connection, now: datetime, days: int) -> Reviews:
    """Where review feedback came from over the last `days` local days, today's so far included.

    Returns:
        The report; a window with nothing in it has no PRs, reviewers, rounds, or runs, and each day at nothing.
    """
    start, end = spend.window(now, days)
    since, until = db.format_time(start), db.format_time(end)
    starts = spend.day_starts(start, days)
    with db.read_snapshot(conn):
        tracked = tracked_prs.tracked(conn, "", until)
        # Every PR a run ever named, which may be many: one parameter, not one each.
        named = records.select(records.ObservedPr).where(
            "url IN (SELECT value FROM json_each(?))",
            json.dumps(list(tracked)),
        )
        observed = {p.url: p for p in named.all(conn)}
        said = pr_feedback.feedback(conn, observed)
        plans = (
            records.select(records.FeedbackPlan)
            .where("created_at >= ? AND created_at < ?", since, until)
            .order_by("created_at DESC, id DESC")
            .all(conn)
        )
        plan_prs = records.select(records.FeedbackPlanPr).where_in("plan_id", [p.id for p in plans]).all(conn)
        plan_runs = _plan_runs(conn, plans)
        review_runs = _review_runs(conn, since, until)
        dismissals = _dismissals(conn, since, until)
        drafts = _drafts(conn, since, until)
    in_window = {url: [f for f in found if _within(f.created_at, since, until)] for url, found in said.items()}
    read_by: dict[int, list[str]] = {}
    for row in plan_prs:
        read_by.setdefault(row.plan_id, []).append(row.pr_url)
    rounds = [_round(p, read_by.get(p.id, []), plan_runs) for p in plans]
    prs = [
        _pr(tracked[url], pr, said.get(url, []), in_window.get(url, []), [r for r in rounds if url in r.prs])
        for url, pr in observed.items()
        if _active(tracked[url], pr, in_window.get(url, []), since, until)
    ]
    prs.sort(key=lambda p: p.url)
    prs.sort(key=lambda p: tracked[p.url].last_named, reverse=True)
    # Each first review that arrived in the window on a PR with a start: when, and its wait.
    arrived = [
        (at, wait)
        for p in prs
        if (wait := p.first_review) is not None and (at := p.first_review_at) is not None and _within(at, since, until)
    ]
    return Reviews(
        since=since,
        until=until,
        days=days,
        prs=prs,
        reviewers=_reviewers({p.url: p for p in prs}, in_window),
        per_day=_per_day(arrived, starts),
        waits=sorted(wait for _, wait in arrived),
        untimed=sum(1 for p in prs if p.waiting_since is None and p.reviews),
        waiting=sum(
            1
            for p in prs
            if p.waiting_since is not None and p.first_review_at is None and observed[p.url].state is PrState.OPEN
        ),
        rounds=rounds,
        efforts=_efforts(rounds),
        review_runs=review_runs,
        dismissals=dismissals,
        drafts=drafts,
    )


def _within(stamp: str | None, since: str, until: str) -> bool:
    return stamp is not None and since <= db.format_time(db.parse_time(stamp)) < until


# Whether a PR saw something in the window: a run that named it, feedback, becoming ready, a review asked, or a merge.
def _active(
    tracked: tracked_prs.TrackedPr,
    pr: records.ObservedPr,
    said: Collection[pr_feedback.Feedback],
    since: str,
    until: str,
) -> bool:
    times = (tracked.last_named, pr.ready_at, pr.review_requested_at, pr.merged_at)
    return bool(said) or any(_within(at, since, until) for at in times)


def _pr(
    tracked: tracked_prs.TrackedPr,
    pr: records.ObservedPr,
    said: Sequence[pr_feedback.Feedback],
    in_window: Sequence[pr_feedback.Feedback],
    rounds: Sequence[Round],
) -> ReviewedPr:
    start = pr_feedback.waiting_since(pr)
    first = None if start is None else pr_feedback.first_review(said, start)
    judged = [f for f in in_window if f.judged]
    return ReviewedPr(
        url=pr.url,
        ticket=tracked.ticket,
        phase=tracked.phase,
        ready_at=pr.ready_at,
        merged_at=pr.merged_at,
        waiting_since=start,
        first_review_at=None if first is None else first.created_at,
        reviews=len(judged),
        changes_requested=sum(1 for f in judged if f.state is ReviewState.CHANGES_REQUESTED),
        comments=len(in_window) - len(judged),
        rounds=len(rounds),
        cost_usd=_sum(cost for r in rounds for cost in (r.plan_cost_usd, r.resume_cost_usd)),
    )


# Each reviewer's feedback in the window, and their median wait over the PRs they reviewed that have a start.
def _reviewers(prs: Mapping[str, ReviewedPr], said: Mapping[str, Sequence[pr_feedback.Feedback]]) -> list[Reviewer]:
    by_author: dict[str, list[pr_feedback.Feedback]] = {}
    for url in prs:
        for f in said.get(url, []):
            if f.author is not None:
                by_author.setdefault(f.author, []).append(f)
    found: list[Reviewer] = []
    for author, theirs in by_author.items():
        judged = [f for f in theirs if f.judged]
        reviewed = sorted({f.pr_url for f in judged})
        waits: list[timedelta] = []
        for url in reviewed:
            start = prs[url].waiting_since
            first = None if start is None else pr_feedback.first_review([f for f in judged if f.pr_url == url], start)
            if start is not None and first is not None and first.created_at is not None:
                waits.append(db.parse_time(first.created_at) - db.parse_time(start))
        found.append(
            Reviewer(
                author=author,
                reviews=len(judged),
                changes_requested=sum(1 for f in judged if f.state is ReviewState.CHANGES_REQUESTED),
                comments=len(theirs) - len(judged),
                prs=len(reviewed),
                median_wait=_median(waits),
            ),
        )
    return sorted(found, key=lambda r: (-r.reviews, -r.comments, r.author))


def _per_day(arrived: Iterable[tuple[str, timedelta]], starts: Mapping[str, str]) -> list[Day]:
    waits: dict[str, list[timedelta]] = {day: [] for day in starts}
    for at, wait in arrived:
        day = waits.get(spend.local_day(at))
        if day is not None:
            day.append(wait)
    return [
        Day(
            day=day,
            start=at,
            first_reviews=_buckets(waits[day]),
            median_wait=_median(waits[day]),
        )
        for day, at in starts.items()
    ]


# How many of `waits` fall in each bucket `WAIT_BOUNDS` cuts, the quickest first.
def _buckets(waits: Iterable[timedelta]) -> list[int]:
    counts = [0] * (len(WAIT_BOUNDS) + 1)
    for wait in waits:
        counts[next((i for i, bound in enumerate(WAIT_BOUNDS) if wait < bound), len(WAIT_BOUNDS))] += 1
    return counts


@dataclass(frozen=True)
class _PlanRun(records.View):
    """A run a feedback plan's round spent: the plan's own run, or a `resume` that went ahead on it."""

    id: int
    kind: RunKind
    feedback_plan_id: int | None
    cost_usd: float | None


# The runs the plans' rounds spent: each plan's own, and the resumes that went ahead on one, by the plan they name or
# the approval they spent.
def _plan_runs(conn: sqlite3.Connection, plans: Sequence[records.FeedbackPlan]) -> list[_PlanRun]:
    ids = [run for p in plans for run in (p.run_id, p.spent_run_id) if run is not None]
    query = (
        sql.select("id, kind, feedback_plan_id, cost_usd")
        .from_("runs")
        .where(
            "(feedback_plan_id IN (SELECT value FROM json_each(?)) OR id IN (SELECT value FROM json_each(?)))",
            json.dumps([p.id for p in plans]),
            json.dumps(ids),
        )
        .order_by("id")
    )
    return records.fetch_all(conn, _PlanRun, query)


def _round(plan: records.FeedbackPlan, prs: Sequence[str], runs: Iterable[_PlanRun]) -> Round:
    resumes = [
        r for r in runs if r.kind is RunKind.RESUME and (r.feedback_plan_id == plan.id or r.id == plan.spent_run_id)
    ]
    wrote = next((r for r in runs if r.id == plan.run_id), None)
    return Round(
        plan_id=plan.id,
        ticket=plan.ticket_key,
        run_id=plan.run_id,
        created_at=plan.created_at,
        status=plan.status,
        approved_channel=plan.approved_channel,
        effort=plan.effort,
        prs=sorted(prs),
        plan_cost_usd=None if wrote is None else wrote.cost_usd,
        resumes=len(resumes),
        resume_cost_usd=_sum(r.cost_usd for r in resumes),
    )


def _efforts(rounds: Iterable[Round]) -> list[Effort]:
    by_effort: dict[PlanEffort | None, list[Round]] = {}
    for r in rounds:
        by_effort.setdefault(r.effort, []).append(r)
    order: list[PlanEffort | None] = [*PlanEffort, None]
    return [
        Effort(
            effort=effort,
            plans=len(found),
            resumes=sum(r.resumes for r in found),
            resume_cost_usd=_sum(r.resume_cost_usd for r in found),
        )
        for effort in order
        if (found := by_effort.get(effort))
    ]


@dataclass(frozen=True)
class _RunCount(records.View):
    """The review runs of one purpose and status, and what they cost."""

    purpose: str
    status: ReviewRunStatus
    runs: int
    cost_usd: float | None


def _review_runs(conn: sqlite3.Connection, since: str, until: str) -> list[ReviewRuns]:
    query = (
        sql.select("purpose, status, count(*) AS runs, SUM(cost_usd) AS cost_usd")
        .from_("review_runs")
        .where("started_at >= ? AND started_at < ?", since, until)
        .group_by("purpose, status")
        .order_by("purpose, status")
    )
    return [
        ReviewRuns(purpose=r.purpose, status=r.status, runs=r.runs, cost_usd=r.cost_usd)
        for r in records.fetch_all(conn, _RunCount, query)
    ]


@dataclass(frozen=True)
class _ReasonCount(records.View):
    """The dismissals of one reason."""

    reason: DismissalReason | None
    findings: int


def _dismissals(conn: sqlite3.Connection, since: str, until: str) -> list[Dismissals]:
    query = (
        sql.select("reason, count(*) AS findings")
        .from_("review_dismissals")
        .where("dismissed_at >= ? AND dismissed_at < ?", since, until)
        .group_by("reason")
        .order_by("findings DESC, reason")
    )
    return [Dismissals(reason=r.reason, findings=r.findings) for r in records.fetch_all(conn, _ReasonCount, query)]


@dataclass(frozen=True)
class _StatusCount(records.View):
    """The drafts at one status."""

    status: ReviewDraftStatus
    drafts: int


def _drafts(conn: sqlite3.Connection, since: str, until: str) -> list[Drafts]:
    query = (
        sql.select("status, count(*) AS drafts")
        .from_("review_drafts")
        .where("created_at >= ? AND created_at < ?", since, until)
        .group_by("status")
        .order_by("drafts DESC, status")
    )
    return [Drafts(status=r.status, drafts=r.drafts) for r in records.fetch_all(conn, _StatusCount, query)]


def _median(waits: Collection[timedelta]) -> timedelta | None:
    return timedelta(seconds=statistics.median(w.total_seconds() for w in waits)) if waits else None


# The sum of the values that are not None; None when every one is.
def _sum(values: Iterable[float | None]) -> float | None:
    parts = [float(v) for v in values if v is not None]
    return sum(parts) if parts else None
