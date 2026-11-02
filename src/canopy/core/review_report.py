"""Where review feedback came from and what answering it cost (DESIGN §11), for the web UI's Reviews page.

Reads only. Over the same window as `canopy spend` and `canopy health` (whole local days, today's so far included): the
PRs a run named that canopy observed and that saw something in the window, a run that named them, feedback, becoming
ready, a review asked for, or a merge; the feedback people other than each PR's author left in it, not bots'
(`pr_feedback`, as the monthly report counts it), by reviewer; how long each first review that arrived in it took from
when its PR began waiting, on GitHub's clock; the feedback plans made in it, how each was approved, and the resumes that
followed; how long each round took to answer, from the feedback that started it to the push after its resume; the
approvals each PR and reviewer gave; and canopy's own reviewer's runs, the findings the operator dismissed, and its
drafts.

A round starts at the earliest feedback, not an approval, that its plan's PRs had before it was written and after the
last plan before it that went ahead (was approved). It is answered when a source first observed a check run on one of
its PRs, after its resume started, on a head other than the one its plan read: the push. A PR whose checks no source
observed has no push on record, so its round is not timed.

A PR read before canopy kept GitHub's times, and not read since by `canopy backfill`, or still a draft, has no start,
so its first review is counted apart and never mixed into a median. The journal keeps no history of a ticket's phase,
so time spent red in CI or conflicted is not here.
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
    #: Its reviews made in the window that approved it.
    approved: int
    #: When its first approval came, in the window or before it; None with none.
    approved_at: str | None
    #: The plans that read it and were approved before its first approval, any time; None without an approval.
    rounds_to_approval: int | None

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
    #: Of their reviews, the ones that approved.
    approved: int
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
class Turnaround:
    """How long a feedback round took to answer, in its four parts, end to end from the feedback to the push."""

    #: From the feedback that started it to its plan.
    to_plan: timedelta
    #: From its plan to the plan's approval.
    to_approval: timedelta
    #: From the approval to its resume's start.
    to_resume: timedelta
    #: From its resume's start to the push that answered it.
    to_push: timedelta

    @property
    def whole(self) -> timedelta:
        """From the feedback that started it to the push that answered it."""
        return self.to_plan + self.to_approval + self.to_resume + self.to_push


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
    #: When the feedback that started it was made; None when its PRs had none it could have read.
    review_at: str | None
    #: When it was approved; None while not.
    approved_at: str | None
    #: When the resume that went ahead on it started and ended: the one that spent its approval, else the first; None
    #: without one, or while it runs.
    resume_started_at: str | None
    resume_ended_at: str | None
    #: When a source first observed a new head on one of its PRs after that resume started; None while none.
    answered_at: str | None

    @property
    def turnaround(self) -> Turnaround | None:
        """How long it took to answer, in parts; None until it is answered, or without the feedback that started it."""
        stamps = (self.review_at, self.created_at, self.approved_at, self.resume_started_at, self.answered_at)
        times = [db.parse_time(s) for s in stamps if s is not None]
        if len(times) < len(stamps):
            return None
        review, plan, approved, resumed, answered = times
        return Turnaround(
            to_plan=plan - review,
            to_approval=approved - plan,
            to_resume=resumed - approved,
            to_push=answered - resumed,
        )


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

    @property
    def turnarounds(self) -> list[Turnaround]:
        """The turnaround of each of the window's rounds that was answered, the newest round first."""
        return [t for r in self.rounds if (t := r.turnaround) is not None]

    @property
    def median_turnaround(self) -> Turnaround | None:
        """The median of each part over the answered rounds; None with none. Its parts need not sum to the median."""
        found = self.turnarounds
        if not found:
            return None
        return Turnaround(
            to_plan=_middle(t.to_plan for t in found),
            to_approval=_middle(t.to_approval for t in found),
            to_resume=_middle(t.to_resume for t in found),
            to_push=_middle(t.to_push for t in found),
        )

    @property
    def median_turnaround_whole(self) -> timedelta | None:
        """The median, over the answered rounds, of each one's whole turnaround; None with none."""
        return _median([t.whole for t in self.turnarounds])


def report(conn: sqlite3.Connection, now: datetime, days: int) -> Reviews:
    """Where review feedback came from over the last `days` local days, today's so far included.

    Returns:
        The report; a window with nothing in it has no PRs, reviewers, rounds, or runs, and each day at nothing.
    """
    return between(conn, *spend.window(now, days))


def between(conn: sqlite3.Connection, start: datetime, end: datetime) -> Reviews:
    """Where review feedback came from, from one local midnight, `start`, to another, `end`.

    Returns:
        The report, as `report` gives it for any such window: a calendar month's, or the one before a page's.
    """
    since, until = db.format_time(start), db.format_time(end)
    days = spend.days_between(start, end)
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
        pr_plans = _pr_plans(conn, observed)
        checked = (
            records.select(records.ObservedCheckRun)
            .where_in("pr_url", sorted({row.pr_url for row in plan_prs}))
            .order_by("observed_at, run_id")
            .all(conn)
        )
        review_runs = _review_runs(conn, since, until)
        dismissals = _dismissals(conn, since, until)
        drafts = _drafts(conn, since, until)
    in_window = {url: [f for f in found if _within(f.created_at, since, until)] for url, found in said.items()}
    read_by: dict[int, list[records.FeedbackPlanPr]] = {}
    for row in plan_prs:
        read_by.setdefault(row.plan_id, []).append(row)
    gone_ahead: dict[str, list[_PrPlan]] = {}
    for row in pr_plans:
        if row.approved_at is not None:
            gone_ahead.setdefault(row.pr_url, []).append(row)
    checks: dict[str, list[records.ObservedCheckRun]] = {}
    for run in checked:
        checks.setdefault(run.pr_url, []).append(run)
    rounds = [
        _round(p, read_by.get(p.id, []), plan_runs, _Reads(said=said, gone_ahead=gone_ahead, checks=checks))
        for p in plans
    ]
    prs = [
        _pr(
            tracked[url],
            pr,
            said.get(url, []),
            in_window.get(url, []),
            [r for r in rounds if url in r.prs],
            gone_ahead=gone_ahead.get(url, []),
        )
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
    *,
    gone_ahead: Iterable[_PrPlan],
) -> ReviewedPr:
    start = pr_feedback.waiting_since(pr)
    first = None if start is None else pr_feedback.first_review(said, start)
    judged = [f for f in in_window if f.judged]
    approvals = sorted(f.created_at for f in said if f.state is ReviewState.APPROVED and f.created_at is not None)
    approved_at = approvals[0] if approvals else None
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
        approved=sum(1 for f in judged if f.state is ReviewState.APPROVED),
        approved_at=approved_at,
        rounds_to_approval=None
        if approved_at is None
        else sum(1 for p in gone_ahead if p.approved_at and db.parse_time(p.approved_at) < db.parse_time(approved_at)),
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
                approved=sum(1 for f in judged if f.state is ReviewState.APPROVED),
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
    started_at: str
    ended_at: str | None


# The runs the plans' rounds spent: each plan's own, and the resumes that went ahead on one, by the plan they name or
# the approval they spent.
def _plan_runs(conn: sqlite3.Connection, plans: Sequence[records.FeedbackPlan]) -> list[_PlanRun]:
    ids = [run for p in plans for run in (p.run_id, p.spent_run_id) if run is not None]
    query = (
        sql.select("id, kind, feedback_plan_id, cost_usd, started_at, ended_at")
        .from_("runs")
        .where(
            "(feedback_plan_id IN (SELECT value FROM json_each(?)) OR id IN (SELECT value FROM json_each(?)))",
            json.dumps([p.id for p in plans]),
            json.dumps(ids),
        )
        .order_by("id")
    )
    return records.fetch_all(conn, _PlanRun, query)


@dataclass(frozen=True)
class _PrPlan(records.View):
    """A feedback plan that read a PR, and when it was written and approved."""

    pr_url: str
    plan_id: int
    created_at: str
    approved_at: str | None


# Every feedback plan that read one of `urls`, in the window or before it, the oldest first.
def _pr_plans(conn: sqlite3.Connection, urls: Collection[str]) -> list[_PrPlan]:
    query = (
        sql.select("pp.pr_url, p.id AS plan_id, p.created_at, p.approved_at")
        .from_("feedback_plan_prs pp")
        .join("feedback_plans p ON p.id = pp.plan_id")
        .where("pp.pr_url IN (SELECT value FROM json_each(?))", json.dumps(sorted(urls)))
        .order_by("p.created_at, p.id")
    )
    return records.fetch_all(conn, _PrPlan, query)


@dataclass(frozen=True)
class _Reads:
    """What a round's turnaround reads beside its plan, each by PR URL."""

    #: The feedback on each PR, any time.
    said: Mapping[str, Sequence[pr_feedback.Feedback]]
    #: The plans that read each PR and went ahead, the oldest first.
    gone_ahead: Mapping[str, Sequence[_PrPlan]]
    #: The check runs observed on each PR, the first observed first.
    checks: Mapping[str, Sequence[records.ObservedCheckRun]]


def _round(
    plan: records.FeedbackPlan,
    prs: Sequence[records.FeedbackPlanPr],
    runs: Sequence[_PlanRun],
    reads: _Reads,
) -> Round:
    resumes = [
        r for r in runs if r.kind is RunKind.RESUME and (r.feedback_plan_id == plan.id or r.id == plan.spent_run_id)
    ]
    wrote = next((r for r in runs if r.id == plan.run_id), None)
    resume = next((r for r in resumes if r.id == plan.spent_run_id), resumes[0] if resumes else None)
    return Round(
        plan_id=plan.id,
        ticket=plan.ticket_key,
        run_id=plan.run_id,
        created_at=plan.created_at,
        status=plan.status,
        approved_channel=plan.approved_channel,
        effort=plan.effort,
        prs=sorted(p.pr_url for p in prs),
        plan_cost_usd=None if wrote is None else wrote.cost_usd,
        resumes=len(resumes),
        resume_cost_usd=_sum(r.cost_usd for r in resumes),
        review_at=_earliest(_started_by(plan, p.pr_url, reads) for p in prs),
        approved_at=plan.approved_at,
        resume_started_at=None if resume is None else resume.started_at,
        resume_ended_at=None if resume is None else resume.ended_at,
        answered_at=None if resume is None else _earliest(_pushed(p, resume, reads) for p in prs),
    )


# The earliest feedback on `url` that `plan` could have answered: made before it, after the last plan before it that
# read the PR and went ahead, and not an approval.
def _started_by(plan: records.FeedbackPlan, url: str, reads: _Reads) -> str | None:
    written = db.parse_time(plan.created_at)
    before = [p for p in reads.gone_ahead.get(url, ()) if db.parse_time(p.created_at) < written]
    after = db.parse_time(before[-1].created_at) if before else None
    return _earliest(
        f.created_at
        for f in reads.said.get(url, ())
        if f.created_at is not None
        and f.state is not ReviewState.APPROVED
        and db.parse_time(f.created_at) < written
        and (after is None or db.parse_time(f.created_at) > after)
    )


# When a source first observed a check run on `read`'s PR after `resume` started, on a head other than the one the plan
# read, else the PR's last head observed before it started; None with none.
def _pushed(read: records.FeedbackPlanPr, resume: _PlanRun, reads: _Reads) -> str | None:
    runs = reads.checks.get(read.pr_url, ())
    began = db.parse_time(resume.started_at)
    head = read.head_sha
    if head is None:
        before = [r for r in runs if db.parse_time(r.observed_at) <= began]
        head = before[-1].head_sha if before else None
    return next(
        (r.observed_at for r in runs if db.parse_time(r.observed_at) > began and r.head_sha != head),
        None,
    )


# The earliest of the journal times that are not None, as it was written; None when every one is.
def _earliest(stamps: Iterable[str | None]) -> str | None:
    return min((s for s in stamps if s is not None), key=db.parse_time, default=None)


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
    return _middle(waits) if waits else None


# The median of `spans`, which must hold one at least.
def _middle(spans: Iterable[timedelta]) -> timedelta:
    return timedelta(seconds=statistics.median(w.total_seconds() for w in spans))


# The sum of the values that are not None; None when every one is.
def _sum(values: Iterable[float | None]) -> float | None:
    parts = [float(v) for v in values if v is not None]
    return sum(parts) if parts else None
