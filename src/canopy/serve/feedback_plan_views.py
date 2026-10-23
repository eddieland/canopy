"""A PR's current feedback plan as the API sends it beside its threads (DESIGN §32, On the PR, and the drafts after).

The plan is its ticket's current one, when it covers the PR's repository: waiting, stale, approved, or spent by the
`resume` that went ahead on it. Its text is read from its file every time, bounded and never through a link, as
`canopy show` reads it, and like each item's proposed reply it is model text, sent for the UI to show as plain text.
Whether it is stale is computed here, from what the connectors last read, as the state block computes it. A waiting
plan is also named on its ticket's summary, which is how the attention list tells its `plan_review` from a ticket
plan's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from canopy.core import db, feedback_items, feedback_plans, plans, records, sql
from canopy.core.vocab import PlanStatus, ReviewItem
from canopy.serve.schema import WaitingFeedbackPlan
from canopy.serve.schema.feedback_plan import FeedbackPlan, FeedbackPlanApproved, FeedbackPlanItem, ItemName

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from datetime import datetime

    from canopy.core.context import Context


def for_pr(ctx: Context, url: str, thread_of: Mapping[int, str]) -> FeedbackPlan | None:
    """The current feedback plan of the ticket whose unit `url` is the PR of, if it covers that unit's repository.

    `thread_of` is the thread each review comment on the PR is on, by its id, as the page shows them, so an item
    names its thread.

    Returns:
        The plan, its status and what made it stale, its file, and its items; None when the PR is no unit's, or its
        ticket has no current feedback plan of its repository.
    """
    conn = ctx.conn
    unit = sql.execute(conn, sql.select("ticket_key, repo").from_("ticket_units").where("pr_url = ?", url)).fetchone()
    if unit is None:
        return None
    plan = feedback_plans.current(conn, str(unit["ticket_key"]))
    if plan is None or str(unit["repo"]) not in feedback_plans.repos(conn, plan):
        return None
    # Feedback after an approval waits for the next plan, so only a waiting plan is stale (DESIGN §32).
    changes: list[feedback_items.Change] = (
        feedback_items.changes(conn, ctx.config.trust, plan) if plan.status is PlanStatus.PROPOSED else []
    )
    path = plans.path_for(ctx.state_dir, plan.ticket_key, plan.run_id)
    reading = plans.read(path)
    who = feedback_plans.authors(conn, plan.id)
    trusted = ctx.config.trust.trusted_reviewers
    items: list[FeedbackPlanItem] = []
    for i in feedback_plans.items(conn, plan.id):
        author = who.get((i.pr_url, i.item, i.item_id))
        on_page = i.pr_url == url and i.item is ReviewItem.COMMENT
        items.append(
            FeedbackPlanItem(
                number=i.number,
                pr_url=i.pr_url,
                item=i.item.value,
                item_id=i.item_id,
                proposal=i.proposal.value,
                reply=i.reply,
                left_out=i.left_out,
                author=author,
                trusted=author is not None and author in trusted,
                thread_id=thread_of.get(i.item_id) if on_page else None,
            ),
        )
    return FeedbackPlan(
        id=plan.id,
        ticket_key=plan.ticket_key,
        run=plan.run_id,
        created_at=db.parse_time(plan.created_at),
        status=_status(plan, stale=bool(changes)),
        changes=[c.said() for c in changes],
        stale_shown=bool(changes) and plan.stale_shown == feedback_items.digest(changes),
        approved_at=_time(plan.approved_at),
        approved_channel=plan.approved_channel,
        approved_reason=plan.approved_reason,
        approved_message=plan.approved_message_id,
        spent_run=plan.spent_run_id,
        path=str(path),
        text=reading.text,
        problem=reading.problem,
        items=items,
    )


def approved(conn: sqlite3.Connection, plan: records.FeedbackPlan) -> FeedbackPlanApproved:
    """What an approval of `plan` did, as `canopy plan KEY --approve` reports it.

    Returns:
        The plan, its ticket, the items addressed and left out, and the message the approval wrote.
    """
    covered = feedback_plans.items(conn, plan.id)
    return FeedbackPlanApproved(
        plan=plan.id,
        ticket_key=plan.ticket_key,
        addressed=[ItemName(number=i.number, item_id=i.item_id) for i in covered if not i.left_out],
        left=[ItemName(number=i.number, item_id=i.item_id) for i in covered if i.left_out],
        message=plan.approved_message_id,
    )


def waiting(ctx: Context, key: str) -> WaitingFeedbackPlan | None:
    """The ticket's current feedback plan while it waits on the operator, as the attention list names it.

    The overseer raises a waiting plan as `plan_review`, as it does a ticket's plan, so this is how the UI tells the
    two apart, and when the operator answered it.

    Returns:
        The plan, the PRs it covers, how many items it covers, and whether it is stale; None when the ticket's current
        feedback plan, if it has one, does not wait: approved or spent.
    """
    conn = ctx.conn
    plan = feedback_plans.current(conn, key)
    if plan is None or plan.status is not PlanStatus.PROPOSED:
        return None
    covered = feedback_plans.repos(conn, plan)
    units = db.units(conn, key)
    return WaitingFeedbackPlan(
        id=plan.id,
        pr_urls=[str(u.pr_url) for u in units if u.pr_url and u.repo in covered],
        items=len(feedback_plans.items(conn, plan.id)),
        stale=bool(feedback_items.changes(conn, ctx.config.trust, plan)),
    )


def _status(plan: records.FeedbackPlan, *, stale: bool) -> Literal["waiting", "stale", "approved", "spent"]:
    if plan.spent_run_id is not None:
        return "spent"
    if plan.status is PlanStatus.APPROVED:
        return "approved"
    return "stale" if stale else "waiting"


def _time(stamp: str | None) -> datetime | None:
    return db.parse_time(stamp) if stamp is not None else None
