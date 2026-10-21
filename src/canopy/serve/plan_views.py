"""A ticket's plans as the API sends them (DESIGN §25): the newest, the earlier ones, and the comments.

A plan's text is read from its file every time, bounded and never through a link, as `canopy show` reads it; the
journal holds only its status and hashes. The text is model-written, and the UI draws it in the plan editor, which keeps
HTML and images as characters (D113).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, personas, plan_threads, plans, records, sql
from canopy.core.vocab import PlanStatus, RunKind
from canopy.serve.persona_schema import RunPersona
from canopy.serve.plan_schema import PlanFile, PlanReplyView, PlanSummary, PlanThreadView, TicketPlans

if TYPE_CHECKING:
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
    planning = running.id if running is not None and running.kind == RunKind.PLAN else None
    asked = plans.changes_asked(ctx.conn, ticket)
    return TicketPlans(
        needed=plans.needed(ctx.config.policy.plan, ticket.plan_setting),
        setting=ticket.plan_setting.value if ticket.plan_setting is not None else None,
        policy=ctx.config.policy.plan,
        planning=planning,
        changes_asked=db.parse_time(asked) if asked is not None else None,
        newest=plan_file(ctx, found[-1]) if found else None,
        plans=[plan_summary(p) for p in found],
        threads=[thread_view(t) for t in plan_threads.threads(ctx.conn, key)],
    )


def plan_file(ctx: Context, plan: records.Plan) -> PlanFile:
    """A plan as its file stands now.

    Returns:
        The plan, the persona its planner wrote in, its path, its text or why it is not a plan any more, its hash,
        and whether it was edited.
    """
    path = plans.path_for(ctx.state_dir, plan.ticket_key, plan.run_id)
    reading = plans.read(path)
    return PlanFile(
        plan=plan_summary(plan),
        persona=run_persona(ctx, plan.run_id),
        path=str(path),
        text=reading.text,
        problem=reading.problem,
        sha256=reading.sha256,
        edited=reading.sha256 != plan.sha256,
        changed_since_approval=plan.status is PlanStatus.APPROVED and reading.sha256 != plan.approved_sha256,
    )


def run_persona(ctx: Context, run_id: int) -> RunPersona | None:
    """The persona run `run_id` wrote in, with the instructions it read (DESIGN §31).

    The journal keeps a persona's text once per digest, from the run that first carried it. A run from before canopy
    kept texts has its persona's file read instead, but only while the file's digest is still the run's: a text the run
    never read is not shown as its.

    Returns:
        The persona, or None for a run from before canopy recorded one.
    """
    run = records.fetch_one(ctx.conn, records.Run, sql.select("*").from_("runs").where("id = ?", run_id))
    if run is None or run.persona is None or run.persona_digest is None:
        return None
    kept = db.persona_text(ctx.conn, run.persona_digest)
    if kept is not None:
        return RunPersona(name=run.persona, digest=run.persona_digest, text=kept)
    try:
        now = personas.load(ctx.config, run.persona)
    except personas.PersonaError as e:
        return RunPersona(name=run.persona, digest=run.persona_digest, problem=f"canopy kept no text, and {e.reason}")
    if now.digest != run.persona_digest:
        return RunPersona(
            name=run.persona,
            digest=run.persona_digest,
            problem="canopy kept no text, and its file has been edited since the run read it",
        )
    return RunPersona(name=run.persona, digest=run.persona_digest, text=now.text)


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
        approved_reason=plan.approved_reason,
        effort=plan.effort.value if plan.effort is not None else None,
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
