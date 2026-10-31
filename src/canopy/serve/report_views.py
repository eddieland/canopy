"""The reports, as the API sends them (DESIGN §11), by the backend's clock.

What each local calendar month cost and got done, how the last days' runs ended, as `canopy health` reads them, what
CI did on the PRs canopy observed, where their review feedback came from, and how plans were approved.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from canopy.core import ci, db, health, plan_report, review_report, runtime_sessions, spend
from canopy.core.config import CANOPY_REVIEWER
from canopy.serve import monthly
from canopy.serve.schema.ci import (
    CiCheck,
    CiDay,
    CiFix,
    CiFixedCheck,
    CiKick,
    CiKickedPullRequest,
    CiReport,
)
from canopy.serve.schema.health import (
    HealthCounts,
    HealthDay,
    HealthFailure,
    HealthOutcome,
    HealthRefusal,
    HealthReport,
)
from canopy.serve.schema.plan_report import PlanLevel, PlanOutcome, PlansGroup, PlansLength, PlansReport, PlansRow
from canopy.serve.schema.reports import (
    MonthlyReport,
    ReportKind,
    ReportModel,
    ReportMonth,
    ReportOutside,
    ReportTicket,
    ReportTokens,
)
from canopy.serve.schema.review_report import (
    ReviewsDay,
    ReviewsDismissals,
    ReviewsDrafts,
    ReviewsEffort,
    ReviewsPullRequest,
    ReviewsReport,
    ReviewsReviewer,
    ReviewsRound,
    ReviewsRunCount,
)
from canopy.serve.schema.spend import SpendUnpriced

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime, timedelta

    from canopy.core.context import Context
    from canopy.core.vocab import PlannerApproval
    from canopy.serve.backend import Backend


# How `canopy health` names a task's run's subject: its task's id after it.
_TASK = "task:"
# The guard whose refusals the CI page shows: a `resume` for `ci` alone held until its checks had time to run again.
_COOLDOWN = "cooldown"


def monthly_report(backend: Backend, ctx: Context, months: int) -> MonthlyReport:
    """The last `months` local calendar months, the current one so far included, by the backend's clock.

    Returns:
        Each month, oldest first.
    """
    with db.read_snapshot(ctx.conn):
        found = monthly.months(ctx.conn, backend.clock(), months, state_dir=ctx.state_dir)
        read = runtime_sessions.last_read(ctx.conn)
    return MonthlyReport(
        months=[_month(m) for m in found],
        sessions_read_at=db.parse_time(read.read_at) if read is not None else None,
    )


def health_report(backend: Backend, ctx: Context, days: int) -> HealthReport:
    """How the runs of the last `days` local days ended, by the backend's clock, as `canopy health` reads them.

    Returns:
        The report, with each day's ended and failed runs and how many runs reported no cost.
    """
    now = backend.clock()
    # One snapshot, so a run ending between two of the reads is in all of them or none.
    with db.read_snapshot(ctx.conn):
        found = health.report(ctx.conn, now, days)
        per_day = health.by_day(ctx.conn, now, days)
        unpriced = spend.unpriced(ctx.conn, found.since, found.until)
    return HealthReport(
        days=found.days,
        since=db.parse_time(found.since),
        until=db.parse_time(found.until),
        outcomes=[
            HealthOutcome(kind=o.kind, what=o.what, status=o.status, failed=o.failed, runs=o.runs, cost_usd=o.cost_usd)
            for o in found.outcomes
        ],
        failures=[_failure(f) for f in found.failures],
        refusals=[
            HealthRefusal(guard=r.guard, decisions=r.decisions, ticks=r.ticks, last_tick=r.last_tick)
            for r in found.refusals
        ],
        per_day=[
            HealthDay(day=d.day, start=db.parse_time(d.start), ended=_counts(d.ended), failed=_counts(d.failed))
            for d in per_day
        ],
        unpriced=[SpendUnpriced(kind=u.kind, runs=u.runs, unpriced=u.unpriced) for u in unpriced],
    )


def ci_report(backend: Backend, ctx: Context, days: int) -> CiReport:
    """What CI did over the last `days` local days, by the backend's clock, on the PRs canopy observed.

    Returns:
        The report, with `trust.max_flaky_kicks` and what the `cooldown` guard refused beside it.
    """
    now = backend.clock()
    # One snapshot, so a check run observed between the two reads is in both or neither.
    with db.read_snapshot(ctx.conn):
        found = ci.report(ctx.conn, now, days)
        refused = health.refusals(ctx.conn, found.since, found.until)
    cooldown = next((r for r in refused if r.guard == _COOLDOWN), None)
    return CiReport(
        days=found.days,
        since=db.parse_time(found.since),
        until=db.parse_time(found.until),
        heads=found.heads,
        green_first=found.green_first,
        checks=[
            CiCheck(name=c.name, runs=c.runs, red=c.red, green=c.green, followed=c.followed, passed=c.passed)
            for c in found.checks
        ],
        series=list(found.series),
        per_day=[CiDay(day=d.day, start=db.parse_time(d.start), red=list(d.red)) for d in found.per_day],
        fixes=[_fix(f) for f in found.fixes],
        kicks=[_kick(k) for k in found.kicks],
        kicked_pull_requests=[
            CiKickedPullRequest(
                url=p.url,
                ticket_key=p.ticket,
                phase=p.phase,
                kicks=p.kicks,
                most=p.most,
                still_red=p.still_red,
            )
            for p in found.kicked_prs
        ],
        max_flaky_kicks=ctx.config.trust.max_flaky_kicks,
        cooldown=None
        if cooldown is None
        else HealthRefusal(
            guard=cooldown.guard,
            decisions=cooldown.decisions,
            ticks=cooldown.ticks,
            last_tick=cooldown.last_tick,
        ),
    )


def reviews_report(backend: Backend, ctx: Context, days: int) -> ReviewsReport:
    """Where the last `days` local days' review feedback came from, by the backend's clock, and what answering cost.

    Returns:
        The report, each reviewer marked trusted or not by `trust.trusted_reviewers`.
    """
    found = review_report.report(ctx.conn, backend.clock(), days)
    trusted = set(ctx.config.trust.trusted_reviewers)
    return ReviewsReport(
        days=found.days,
        since=db.parse_time(found.since),
        until=db.parse_time(found.until),
        reviews=found.reviews,
        first_reviews=len(found.waits),
        median_first_review_hours=_hours(found.median_wait),
        untimed=found.untimed,
        waiting=found.waiting,
        per_day=[
            ReviewsDay(
                day=d.day,
                start=db.parse_time(d.start),
                first_reviews=list(d.first_reviews),
                median_wait_hours=_hours(d.median_wait),
            )
            for d in found.per_day
        ],
        reviewers=[
            ReviewsReviewer(
                author=r.author,
                trusted=r.author in trusted,
                reviews=r.reviews,
                changes_requested=r.changes_requested,
                comments=r.comments,
                pull_requests=r.prs,
                median_wait_hours=_hours(r.median_wait),
            )
            for r in found.reviewers
        ],
        pull_requests=[_reviewed(p) for p in found.prs],
        rounds=[_round(r) for r in found.rounds],
        efforts=[
            ReviewsEffort(effort=e.effort, plans=e.plans, resumes=e.resumes, resume_cost_usd=e.resume_cost_usd)
            for e in found.efforts
        ],
        review_runs=[
            ReviewsRunCount(purpose=r.purpose, status=r.status, runs=r.runs, cost_usd=r.cost_usd)
            for r in found.review_runs
        ],
        dismissals=[ReviewsDismissals(reason=d.reason, findings=d.findings) for d in found.dismissals],
        drafts=[ReviewsDrafts(status=d.status, drafts=d.drafts) for d in found.drafts],
        canopy_trusted=CANOPY_REVIEWER in trusted,
    )


def plans_report(backend: Backend, ctx: Context, days: int) -> PlansReport:
    """How the plans written over the last `days` local days were approved, by the backend's clock, and what followed.

    Returns:
        The report, with the level `policy.planner_may_approve` is at now.
    """
    found = plan_report.report(ctx.conn, backend.clock(), days)
    return PlansReport(
        days=found.days,
        since=db.parse_time(found.since),
        until=db.parse_time(found.until),
        level=cast("PlanLevel", str(ctx.config.policy.planner_may_approve)),
        plans=[_plan(p) for p in found.plans],
        groups=[
            PlansGroup(
                level=_level(g.level),
                outcome=_approved(g.outcome),
                plans=g.plans,
                median_hours_to_approve=_hours(g.median_to_approve),
                median_size=g.median_size,
                implemented=g.implemented,
                with_resume=g.with_resume,
                resumes=g.resumes,
                done=g.done,
            )
            for g in found.groups
        ],
        lengths=[
            PlansLength(
                low=n.low,
                high=n.high,
                plans=n.plans,
                median_hours_to_approve=_hours(n.median_to_approve),
                as_written=n.as_written,
            )
            for n in found.lengths
        ],
        outcomes={o: found.count(o) for o in plan_report.Outcome},
    )


def _month(found: monthly.Month) -> ReportMonth:
    return ReportMonth(
        month=found.month,
        since=db.parse_time(found.since),
        until=db.parse_time(found.until),
        runs=found.runs,
        cost_usd=found.cost_usd,
        tokens=_tokens(found.tokens),
        kinds=[
            ReportKind(kind=k.kind, runs=k.runs, cost_usd=k.cost_usd, tokens=_tokens(k.tokens)) for k in found.kinds
        ],
        outside=ReportOutside(
            sessions=found.outside.sessions,
            cost_usd=found.outside.cost_usd,
            tokens=_tokens(found.outside.tokens),
        ),
        models=[
            ReportModel(model=m.model, runs=m.runs, replies=m.replies, cost_usd=m.cost_usd, unread=m.unread)
            for m in found.models
        ],
        landed=[_ticket(t) for t in found.landed],
        closed=found.closed,
        pull_requests=found.pull_requests,
        per_landed_usd=found.per_landed,
        median_iterations=monthly.median(t.iterations for t in found.landed),
        median_pr_comments=monthly.median(t.pr_comments for t in found.landed),
        median_hours_to_land=monthly.median(_hours(t.to_land) for t in found.landed),
        median_review_wait_hours=monthly.median(_hours(t.review_wait) for t in found.landed),
    )


def _tokens(found: monthly.Tokens) -> ReportTokens:
    return ReportTokens(
        input=found.input,
        output=found.output,
        reasoning=found.reasoning,
        cache_read=found.cache_read,
        cache_write=found.cache_write,
        cache_hit=found.cache_hit,
    )


def _ticket(found: monthly.Landed) -> ReportTicket:
    return ReportTicket(
        key=found.key,
        title=found.title,
        landed_at=db.parse_time(found.landed_at),
        started_at=None if found.started_at is None else db.parse_time(found.started_at),
        iterations=found.iterations,
        pr_comments=found.pr_comments,
        reviews=found.reviews,
        changes_requested=found.changes_requested,
        cost_usd=found.cost_usd,
        hours_to_land=_hours(found.to_land),
        review_wait_hours=_hours(found.review_wait),
        merged_at=None if found.merged_at is None else db.parse_time(found.merged_at),
        awaiting_review_at=None if found.awaiting_review_at is None else db.parse_time(found.awaiting_review_at),
    )


def _hours(span: timedelta | None) -> float | None:
    return None if span is None else span.total_seconds() / 3600


# What a failure was about, by its kind, from the one subject `canopy health` gives it: a worker's or a plan's ticket,
# a review's PR, a task's `task:ID`, and a chore's name, which is its sort.
def _failure(found: health.Failure) -> HealthFailure:
    subject = found.subject
    task = subject.removeprefix(_TASK) if found.kind == "tasks" and subject is not None else None
    return HealthFailure(
        kind=found.kind,
        id=found.id,
        what=found.what,
        status=found.status,
        started_at=db.parse_time(found.started_at),
        ticket=subject if found.kind in {"workers", "plans"} else None,
        pr_url=subject if found.kind == "reviews" else None,
        chore=found.what if found.kind == "chores" else None,
        task_id=int(task) if task is not None and task.isdigit() else None,
        note=found.note,
        cost_usd=found.cost_usd,
    )


def _counts(found: Mapping[spend.Kind, int]) -> HealthCounts:
    return HealthCounts(
        overseer=found.get("overseer", 0),
        workers=found.get("workers", 0),
        plans=found.get("plans", 0),
        chores=found.get("chores", 0),
        reviews=found.get("reviews", 0),
        tasks=found.get("tasks", 0),
    )


def _fix(found: ci.Fix) -> CiFix:
    return CiFix(
        run_id=found.run_id,
        ticket_key=found.ticket,
        kind=found.kind,
        status=found.status,
        started_at=db.parse_time(found.started_at),
        cost_usd=found.cost_usd,
        checks=[CiFixedCheck(pr_url=c.pr_url, name=c.name, next=c.next) for c in found.checks],
    )


def _kick(found: ci.Kick) -> CiKick:
    return CiKick(
        run_id=found.run_id,
        repo=found.repo,
        branch=found.branch,
        pr_url=found.pr_url,
        kicked_at=db.parse_time(found.kicked_at),
        kick=found.kick,
        red_before=list(found.red_before),
        still_red=list(found.still_red),
        checked=found.checked,
    )


def _reviewed(found: review_report.ReviewedPr) -> ReviewsPullRequest:
    return ReviewsPullRequest(
        url=found.url,
        ticket_key=found.ticket,
        phase=found.phase,
        waiting_since=_time(found.waiting_since),
        first_review_at=_time(found.first_review_at),
        first_review_hours=_hours(found.first_review),
        reviews=found.reviews,
        changes_requested=found.changes_requested,
        comments=found.comments,
        rounds=found.rounds,
        cost_usd=found.cost_usd,
        ready_at=_time(found.ready_at),
        merged_at=_time(found.merged_at),
        hours_to_merge=_hours(found.to_merge),
    )


def _round(found: review_report.Round) -> ReviewsRound:
    return ReviewsRound(
        plan_id=found.plan_id,
        ticket_key=found.ticket,
        run_id=found.run_id,
        created_at=db.parse_time(found.created_at),
        status=found.status,
        approved_channel=found.approved_channel,
        effort=found.effort,
        pull_requests=list(found.prs),
        plan_cost_usd=found.plan_cost_usd,
        resumes=found.resumes,
        resume_cost_usd=found.resume_cost_usd,
    )


def _plan(found: plan_report.PlanRow) -> PlansRow:
    return PlansRow(
        plan_id=found.plan_id,
        ticket_key=found.ticket,
        run_id=found.run_id,
        created_at=db.parse_time(found.created_at),
        size=found.size,
        effort=found.effort,
        level=_level(found.level),
        outcome=_outcome(found.outcome),
        approved_at=_time(found.approved_at),
        hours_to_approve=_hours(found.to_approve),
        edited=found.edited,
        comments=found.comments,
        earlier=found.earlier,
        implemented=found.implemented,
        resumes=found.resumes,
        reasons={str(reason): n for reason, n in found.reasons.items()},
        done=found.done,
        cost_usd=found.cost_usd,
    )


# The vocabularies' values are the schema's literals, which `test_web_plan_report` holds them to.
def _level(level: PlannerApproval | None) -> PlanLevel | None:
    return cast("PlanLevel | None", None if level is None else str(level))


def _outcome(outcome: plan_report.Outcome) -> PlanOutcome:
    return cast("PlanOutcome", str(outcome))


# A group's outcome, one of `plan_report.APPROVED` by how the report builds its groups.
def _approved(outcome: plan_report.Outcome) -> Literal["planner", "as_written", "revised"]:
    return cast("Literal['planner', 'as_written', 'revised']", str(outcome))


def _time(stamp: str | None) -> datetime | None:
    return None if stamp is None else db.parse_time(stamp)
