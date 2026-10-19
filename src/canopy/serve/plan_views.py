"""A ticket's plans as the API sends them (DESIGN §25): the newest, the earlier ones, the comments, and the triage.

A plan's text is read from its file every time, bounded and never through a link, as `canopy show` reads it; the
journal holds only its status and hashes. The text is model-written, and the UI draws it in the plan editor, which keeps
HTML and images as characters (D113).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import conversation, db, plan_threads, plans
from canopy.core.vocab import PlanStatus, RunKind
from canopy.serve.schema import PlanFile, PlanReplyView, PlanSummary, PlanThreadView, PlanTriage, TicketPlans

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context


def ticket_plans(ctx: Context, key: str) -> TicketPlans | None:
    """The ticket's plans, or None if the journal has no record of the ticket.

    Returns:
        Whether it needs a plan and why, the plan run writing one now, when the operator asked for changes no planner
        has read, the newest plan as its file stands, every plan, and the operator's comments.
    """
    ticket = db.get_ticket(ctx.conn, key)
    if ticket is None:
        return None
    found = plans.history(ctx.conn, key)
    running = db.running_run_of(ctx.conn, key)
    planning = int(running["id"]) if running is not None and running["kind"] == RunKind.PLAN else None
    asked = plans.changes_asked(ctx.conn, ticket)
    return TicketPlans(
        needed=plans.needed(ctx.config.policy.plan, ticket.plan_setting),
        setting=ticket.plan_setting.value if ticket.plan_setting is not None else None,
        policy=ctx.config.policy.plan,
        planning=planning,
        triage=triage_view(ctx, ticket),
        changes_asked=db.parse_time(asked) if asked is not None else None,
        newest=plan_file(ctx, found[-1]) if found else None,
        plans=[plan_summary(p) for p in found],
        threads=[thread_view(t) for t in plan_threads.threads(ctx.conn, key)],
    )


def triage_view(ctx: Context, ticket: records.Ticket) -> PlanTriage | None:
    """The ticket's triage before its plan, as `canopy show` names its waiver (DESIGN §25).

    Returns:
        Its run, how it ended, its verdict and reason on one line, and whether its waiver is in force; None when the
        ticket has had no triage.
    """
    found = plans.triage(ctx.conn, ticket.key)
    if found is None:
        return None
    waiver = plans.waiver(ctx.conn, ticket)
    waived = waiver is not None and waiver.run_id == found.run_id
    said = waiver.reason if waiver is not None and waived else found.reason
    # One line, as the card shows it, and cut as a triage's reason is: a harness's note may run longer.
    reason = " ".join(conversation.printable(said).split())[: plans.MAX_TRIAGE_REASON]
    return PlanTriage(
        run_id=found.run_id,
        status=found.status.value,
        verdict=found.verdict,
        reason=reason or None,
        waived=waived,
        undoable=waived and ticket.branch is None,
        at=db.parse_time(found.at),
    )


def plan_file(ctx: Context, plan: records.Plan) -> PlanFile:
    """A plan as its file stands now.

    Returns:
        The plan, its path, its text or why it is not a plan any more, its hash, and whether it was edited.
    """
    path = plans.path_for(ctx.state_dir, plan.ticket_key, plan.run_id)
    reading = plans.read(path)
    return PlanFile(
        plan=plan_summary(plan),
        path=str(path),
        text=reading.text,
        problem=reading.problem,
        sha256=reading.sha256,
        edited=reading.sha256 != plan.sha256,
        changed_since_approval=plan.status is PlanStatus.APPROVED and reading.sha256 != plan.approved_sha256,
    )


def plan_summary(plan: records.Plan) -> PlanSummary:
    """A plan's status and approval, never its text.

    Returns:
        The plan, as the API sends it.
    """
    return PlanSummary(
        id=plan.id,
        run_id=plan.run_id,
        status=plan.status.value,
        created_at=db.parse_time(plan.created_at),
        approved_at=db.parse_time(plan.approved_at) if plan.approved_at is not None else None,
        approved_channel=plan.approved_channel,
    )


def thread_view(found: plan_threads.Thread) -> PlanThreadView:
    """A comment thread on the ticket's plan, with its replies.

    Returns:
        The thread, as the API sends it.
    """
    t = found.thread
    return PlanThreadView(
        id=t.id,
        quote=t.quote,
        prefix=t.prefix,
        suffix=t.suffix,
        body=t.body,
        at=db.parse_time(t.created_at),
        resolved=t.resolved_at is not None,
        replies=[PlanReplyView(id=r.id, body=r.body, at=db.parse_time(r.created_at)) for r in found.replies],
    )
