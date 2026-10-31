"""The reports, as the API sends them (DESIGN §11), by the backend's clock.

What each local calendar month cost and got done, how the last days' runs ended, as `canopy health` reads them, and
what CI did on the PRs canopy observed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import ci, db, health, runtime_sessions, spend
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
from canopy.serve.schema.reports import (
    MonthlyReport,
    ReportKind,
    ReportModel,
    ReportMonth,
    ReportOutside,
    ReportTicket,
    ReportTokens,
)
from canopy.serve.schema.spend import SpendUnpriced

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import timedelta

    from canopy.core.context import Context
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
