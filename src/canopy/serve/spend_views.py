"""What agent runs cost, as the API sends it (DESIGN §11): the last day's and 30 days' spend, and the breakdown.

The figures are `canopy spend`'s, by the backend's clock, with the idle ticks in the window as the ticks list has them.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import starmap
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.core import spend as spending
from canopy.serve.spend_schema import (
    Spend,
    SpendBreakdown,
    SpendCosts,
    SpendDay,
    SpendModel,
    SpendPullRequest,
    SpendTicket,
    SpendTicks,
    SpendTool,
    SpendUnpriced,
    SpendWindow,
    SpendWoken,
)
from canopy.serve.tick_views import tick_of
from canopy.serve.views import SPEND_DAY_HOURS, SPEND_MONTH_HOURS

if TYPE_CHECKING:
    from datetime import datetime

    from canopy.core.context import Context
    from canopy.serve.backend import Backend


def spend(backend: Backend, ctx: Context) -> Spend:
    """What the last day and the last 30 days cost, by the backend's clock, and what everything ever cost.

    Returns:
        The cost the journal recorded in each window, with the window's start, and its total.
    """
    now = backend.clock()
    return Spend(
        day=_spent(ctx, now, SPEND_DAY_HOURS),
        month=_spent(ctx, now, SPEND_MONTH_HOURS),
        total_usd=db.spent_ever(ctx.conn),
    )


def _spent(ctx: Context, now: datetime, hours: int) -> SpendWindow:
    since = now - timedelta(hours=hours)
    return SpendWindow(since=since, hours=hours, cost_usd=db.spent_since(ctx.conn, db.format_time(since)))


def spend_breakdown(backend: Backend, ctx: Context, days: int) -> SpendBreakdown:
    """What the last `days` local days cost, by the backend's clock, as `canopy spend --days` prints it.

    Returns:
        The breakdown, with the newest idle ticks in the window.
    """
    return _spend_breakdown(ctx, spending.breakdown(ctx.conn, backend.clock(), days))


def spend_breakdown_hours(backend: Backend, ctx: Context, hours: int) -> SpendBreakdown:
    """What the last `hours` clock hours cost, by the backend's clock, by the hour.

    Returns:
        The breakdown, with the newest idle ticks in the window.
    """
    return _spend_breakdown(ctx, spending.breakdown_hours(ctx.conn, backend.clock(), hours))


def _spend_breakdown(ctx: Context, found: spending.Breakdown) -> SpendBreakdown:
    return SpendBreakdown(
        since=db.parse_time(found.since),
        days=found.days,
        hours=found.hours,
        per_day=[
            SpendDay(day=d.day, start=db.parse_time(d.start), costs=_spend_costs(d.costs), done=d.done)
            for d in found.per_day
        ],
        totals=_spend_costs(found.totals),
        ticks=[SpendTicks(group=g.group, ticks=g.ticks, cost_usd=g.cost_usd) for g in found.ticks],
        woken=[SpendWoken(by=w.by, ticks=w.ticks, cost_usd=w.cost_usd) for w in found.woken],
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
        models=[
            SpendModel(kind=m.kind, model=m.model, runs=m.runs, replies=m.replies, cost_usd=m.cost_usd)
            for m in found.models
        ],
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
        total=costs.total,
    )
