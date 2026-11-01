"""What agent runs cost, as the API sends it (DESIGN §11): the last day's and 30 days' spend, and the breakdown.

The figures are `canopy spend`'s, by the backend's clock, with the idle ticks in the window as the ticks list has them.
The last day's, 30 days', and all time's are all agent spend: canopy's runs and the runtime's sessions outside canopy.
The breakdown carries each kind's first model calls by week too, for the page's chart of their cache hit rate.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import starmap
from typing import TYPE_CHECKING

from canopy.core import db, runtime_sessions
from canopy.core import spend as spending
from canopy.serve.schema.spend import (
    Spend,
    SpendBreakdown,
    SpendCosts,
    SpendDay,
    SpendDirectory,
    SpendFirstCallWeek,
    SpendMonth,
    SpendPrevious,
    SpendPullRequest,
    SpendSessions,
    SpendShare,
    SpendTicket,
    SpendTicks,
    SpendTool,
    SpendUnpriced,
    SpendWindow,
    SpendWoken,
)
from canopy.serve.tick_views import tick_of
from canopy.serve.views import SPEND_DAY_HOURS, SPEND_MONTH_HOURS, spend_model

if TYPE_CHECKING:
    from datetime import datetime

    from canopy.core.context import Context
    from canopy.serve.backend import Backend


def spend(backend: Backend, ctx: Context) -> Spend:
    """What the last day and the last 30 days cost, by the backend's clock, what everything ever cost, and the month.

    Returns:
        The cost the journal recorded in each window, with the window's start, its total, and the calendar month
        against its budget when one is set.
    """
    now = backend.clock()
    # One snapshot, so a month never shows less than its day.
    with db.read_snapshot(ctx.conn):
        read = runtime_sessions.last_read(ctx.conn)
        budget = spending.budget_month(ctx.conn, now, ctx.config.spend, state_dir=ctx.state_dir)
        return Spend(
            day=_spent(ctx, now, SPEND_DAY_HOURS),
            month=_spent(ctx, now, SPEND_MONTH_HOURS),
            # Every recorded time sorts after the empty string.
            total_usd=spending.spent_since(ctx.conn, "", state_dir=ctx.state_dir),
            sessions_read_at=db.parse_time(read.read_at) if read is not None else None,
            budget=_spend_month(budget) if budget is not None else None,
        )


def _spent(ctx: Context, now: datetime, hours: int) -> SpendWindow:
    since = now - timedelta(hours=hours)
    spent = spending.spent_since(ctx.conn, db.format_time(since), state_dir=ctx.state_dir)
    return SpendWindow(since=since, hours=hours, cost_usd=spent)


def spend_breakdown(backend: Backend, ctx: Context, days: int, *, ticket: str | None = None) -> SpendBreakdown:
    """What the last `days` local days cost, by the backend's clock, as `canopy spend --days` prints it.

    `ticket` narrows its spend by model to that ticket's runs, each beside the workspace's (`spend.models`).

    Returns:
        The breakdown, with the newest idle ticks in the window, and the month against its budget.
    """
    now = backend.clock()
    found = spending.breakdown(ctx.conn, now, days, state_dir=ctx.state_dir, ticket=ticket)
    return _spend_breakdown(ctx, found, now)


def spend_breakdown_hours(
    backend: Backend,
    ctx: Context,
    hours: int,
    *,
    ticket: str | None = None,
) -> SpendBreakdown:
    """What the last `hours` clock hours cost, by the backend's clock, by the hour, as `spend_breakdown` reads them.

    Returns:
        The breakdown, with the newest idle ticks in the window, and the month against its budget.
    """
    now = backend.clock()
    found = spending.breakdown_hours(ctx.conn, now, hours, state_dir=ctx.state_dir, ticket=ticket)
    return _spend_breakdown(ctx, found, now)


def _spend_breakdown(ctx: Context, found: spending.Breakdown, now: datetime) -> SpendBreakdown:
    month = spending.budget_month(ctx.conn, now, ctx.config.spend, state_dir=ctx.state_dir)
    # The window before, as many days or hours, ending where this one starts.
    if found.hours is not None:
        start = db.parse_time(found.since)
        earlier = start - timedelta(hours=found.hours)
    else:
        earlier, start = spending.window_before(found.since, found.days or 0)
    before = spending.headline(ctx.conn, db.format_time(earlier), found.since, state_dir=ctx.state_dir)
    return SpendBreakdown(
        since=db.parse_time(found.since),
        days=found.days,
        hours=found.hours,
        per_day=[
            SpendDay(day=d.day, start=db.parse_time(d.start), costs=_spend_costs(d.costs), done=d.done)
            for d in found.per_day
        ],
        totals=_spend_costs(found.totals),
        ticks=[
            SpendTicks(group=g.group, ticks=g.ticks, cost_usd=g.cost_usd, without_overseer=g.without_overseer)
            for g in found.ticks
        ],
        woken=[
            SpendWoken(by=w.by, ticks=w.ticks, cost_usd=w.cost_usd, without_overseer=w.without_overseer)
            for w in found.woken
        ],
        unpriced=[SpendUnpriced(kind=u.kind, runs=u.runs, unpriced=u.unpriced) for u in found.unpriced],
        idle_share=found.idle_share,
        idle_ticks=list(starmap(tick_of, spending.idle_ticks(ctx.conn, found.since, found.until))),
        done=found.done,
        per_done=found.per_done,
        tickets=[
            SpendTicket(
                key=t.key,
                title=t.title,
                runs=t.runs,
                reviews=t.reviews,
                cost_usd=t.cost_usd,
                done=t.done,
                done_at=db.parse_time(t.done_at) if t.done_at is not None else None,
            )
            for t in found.tickets
        ],
        pull_requests=[
            SpendPullRequest(
                url=p.url,
                ticket_key=p.ticket,
                phase=p.phase,
                runs=p.runs,
                reviews=p.reviews,
                cost_usd=p.cost_usd,
            )
            for p in found.pull_requests
        ],
        tools=[
            SpendTool(
                kind=t.kind,
                tool=t.tool,
                runs=t.runs,
                calls=t.calls,
                errors=t.errors,
                result_chars=t.result_chars,
                est_tokens=t.est_tokens,
            )
            for t in found.tools
        ],
        models=[spend_model(m) for m in found.models],
        month=_spend_month(month) if month is not None else None,
        sessions=_spend_sessions(found.sessions) if found.sessions is not None else None,
        first_call_weeks=[
            SpendFirstCallWeek(
                kind=w.kind,
                by=w.by,
                name=w.name,
                week=w.week,
                runs=w.runs,
                first_call=w.first_call,
                hit_rate=w.hit_rate,
                new_runtime_versions=list(w.new_runtime_versions),
                new_digests=list(w.new_digests),
            )
            for w in found.first_call_weeks
        ],
        previous=SpendPrevious(
            since=earlier,
            until=start,
            totals=_spend_costs(before.totals),
            done=before.done,
            per_done=before.per_done,
        ),
    )


def _spend_sessions(found: runtime_sessions.SessionsSpend) -> SpendSessions:
    return SpendSessions(
        canopy=SpendShare(sessions=found.canopy.sessions, cost_usd=found.canopy.cost_usd),
        outside=SpendShare(sessions=found.outside.sessions, cost_usd=found.outside.cost_usd),
        directories=[
            SpendDirectory(directory=d.directory, sessions=d.sessions, cost_usd=d.cost_usd) for d in found.directories
        ],
        read_at=db.parse_time(found.read_at) if found.read_at is not None else None,
        status=found.status.value if found.status is not None else None,
    )


def _spend_month(found: spending.Month) -> SpendMonth:
    return SpendMonth(
        month=found.month,
        since=db.parse_time(found.since),
        until=db.parse_time(found.until),
        budget_usd=found.budget_usd,
        spent_usd=found.spent_usd,
        elapsed=found.elapsed,
        projected_usd=found.projected_usd,
        alerts=list(found.alerts),
        runs_usd=found.runs_usd,
        outside_usd=found.outside_usd,
        sessions_read_at=db.parse_time(found.sessions_read_at) if found.sessions_read_at is not None else None,
    )


def _spend_costs(costs: spending.Costs) -> SpendCosts:
    return SpendCosts(
        overseer=costs.overseer,
        idle=costs.idle,
        dry_run=costs.dry_run,
        workers=costs.workers,
        plans=costs.plans,
        chores=costs.chores,
        reviews=costs.reviews,
        tasks=costs.tasks,
        outside=costs.outside,
        total=costs.total,
    )
