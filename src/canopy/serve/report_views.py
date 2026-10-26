"""What each local calendar month cost and got done, as the API sends it (DESIGN §11), by the backend's clock."""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, monthly, runtime_sessions
from canopy.serve.schema.reports import (
    MonthlyReport,
    ReportKind,
    ReportModel,
    ReportMonth,
    ReportOutside,
    ReportTicket,
    ReportTokens,
)

if TYPE_CHECKING:
    from datetime import timedelta

    from canopy.core.context import Context
    from canopy.serve.backend import Backend


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
        models=[ReportModel(model=m.model, runs=m.runs, replies=m.replies, cost_usd=m.cost_usd) for m in found.models],
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
    )


def _hours(span: timedelta | None) -> float | None:
    return None if span is None else span.total_seconds() / 3600
