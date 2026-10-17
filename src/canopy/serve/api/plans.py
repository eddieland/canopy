"""A ticket's plans (DESIGN §25): read them, approve, ask for, or skip one, save an edit, and comment on passages.

The plan verbs are `canopy plan`'s, through `canopy.core.plans`, so with its refusals; asking for changes is a reply,
through the tickets' reply route. Saving an edit writes the plan's file as the operator's own editor would, and refuses
one the file changed under. Comments are the web channel's alone: there is no CLI verb to comment, since a passage is
chosen by selecting it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.core import conversation, plan_threads, plans
from canopy.infra import logs
from canopy.serve import plan_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, PlanId, RefusedError, ThreadId, TicketKey, not_found, ticket_ref
from canopy.serve.schema import (
    PlanAction,
    PlanChanged,
    PlanCommentRequest,
    PlanFile,
    PlanReplyRequest,
    PlanSave,
    PlanSaved,
    PlanThreadChange,
    PlanThreadDeleted,
    PlanThreadView,
    TicketPlans,
)

TAG = "plans"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get(
    "/tickets/{key}/plans",
    operation_id="getTicketPlans",
    summary="Get a ticket's plans",
    responses={**REFUSED, **not_found("ticket")},
)
def ticket_plans(key: TicketKey, backend: BackendDep) -> TicketPlans:
    """Whether the ticket needs a plan, its newest as the file stands, every plan, and the operator's comments.

    A key that is not a ticket's is refused `bad_ref` or `unsupported`; one canopy has no record of is a 404.
    """
    ref = ticket_ref(key, "show")
    with backend.open() as ctx:
        found = plan_views.ticket_plans(ctx, ref.id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no record of {ref}")
    return found


@router.get(
    "/tickets/{key}/plans/{plan_id}",
    operation_id="getTicketPlan",
    summary="Get one of a ticket's plans",
    responses={**REFUSED, **not_found("plan of this ticket")},
)
def ticket_plan(key: TicketKey, plan_id: PlanId, backend: BackendDep) -> PlanFile:
    """One of the ticket's plans, earlier ones included, as its file stands: what `canopy show --plans` prints."""
    ref = ticket_ref(key, "show")
    with backend.open() as ctx:
        found = [p for p in plans.history(ctx.conn, ref.id) if p.id == plan_id]
        if not found:
            raise HTTPException(status_code=404, detail=f"{ref} has no plan {plan_id}")
        return plan_views.plan_file(ctx, found[0])


@router.post(
    "/tickets/{key}/plan", operation_id="changeTicketPlan", summary="Decide a ticket's plan", responses=REFUSED
)
def change(key: TicketKey, body: PlanAction, backend: BackendDep) -> PlanChanged:
    """`canopy plan KEY --approve`, `canopy plan KEY`, or `--skip`: approve the newest plan, ask for a new one, or skip.

    Approving takes the file as it stands, edits included. Asking for changes is a reply, not this.
    """
    ref = ticket_ref(key, "plan")
    with backend.open() as ctx:
        try:
            if body.action == "approve":
                plan = plans.approve(ctx.conn, ctx.state_dir, ref.id, channel=WEB, dispatch_lock=ctx.dispatch_lock_path)
                _log.info("plan approved", extra={"ticket": ref.id, "plan": plan.id, "channel": WEB})
                return PlanChanged(action=body.action, plan=plan.id, already=False)
            verb = plans.skip if body.action == "skip" else plans.ask
            asked = verb(ctx.conn, ref.id, dispatch_lock=ctx.dispatch_lock_path)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    what = "plan skipped" if body.action == "skip" else "plan asked for"
    _log.info(what, extra={"ticket": ref.id, "superseded": asked.superseded, "channel": WEB})
    return PlanChanged(action=body.action, superseded=asked.superseded, already=asked.already)


@router.put(
    "/tickets/{key}/plans/{plan_id}/file",
    operation_id="saveTicketPlan",
    summary="Save an edit of a ticket's plan",
    responses=REFUSED,
)
def save(key: TicketKey, plan_id: PlanId, body: PlanSave, backend: BackendDep) -> PlanSaved:
    """Write the plan editor's Markdown over the plan's file, as the operator's own editor would.

    Only the current plan, waiting or approved; an approved one then needs approving again. Refused `bad_plan` while a
    plan run for the ticket is running, and when the file changed since the editor read it, by `read_sha256`.
    """
    ref = ticket_ref(key, "plan")
    with backend.open() as ctx:
        try:
            written = plans.save(
                ctx.conn,
                ctx.state_dir,
                ref.id,
                plan_id,
                body.markdown,
                read_sha256=body.read_sha256,
                dispatch_lock=ctx.dispatch_lock_path,
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("plan saved", extra={"ticket": ref.id, "plan": plan_id, "size": written.size, "channel": WEB})
    return PlanSaved(sha256=written.sha256, size=written.size)


@router.post(
    "/tickets/{key}/plan-threads",
    operation_id="commentTicketPlan",
    summary="Comment on a passage of a ticket's plan",
    responses=REFUSED,
)
def comment(key: TicketKey, body: PlanCommentRequest, backend: BackendDep) -> PlanThreadView:
    """A new open thread on a passage, anchored by its words and the text either side, never by a position."""
    ref = ticket_ref(key, "plan")
    with backend.open() as ctx:
        try:
            added = plan_threads.add(
                ctx.conn, ref.id, quote=body.quote, prefix=body.prefix, suffix=body.suffix, body=body.body
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("plan comment added", extra={"ticket": ref.id, "plan_thread": added.thread.id, "channel": WEB})
    return plan_views.thread_view(added)


@router.post(
    "/tickets/{key}/plan-threads/{thread_id}/replies",
    operation_id="replyTicketPlanThread",
    summary="Reply in a comment thread on a plan",
    responses=REFUSED,
)
def reply(key: TicketKey, thread_id: ThreadId, body: PlanReplyRequest, backend: BackendDep) -> PlanThreadView:
    """A reply at the end of the thread's replies."""
    ref = ticket_ref(key, "plan")
    with backend.open() as ctx:
        try:
            plan_threads.reply(ctx.conn, ref.id, thread_id, body.body)
            changed = plan_threads.change(ctx.conn, ref.id, thread_id)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("plan comment replied", extra={"ticket": ref.id, "plan_thread": thread_id, "channel": WEB})
    return plan_views.thread_view(changed)


@router.patch(
    "/tickets/{key}/plan-threads/{thread_id}",
    operation_id="changeTicketPlanThread",
    summary="Change a comment thread on a plan",
    responses=REFUSED,
)
def change_thread(key: TicketKey, thread_id: ThreadId, body: PlanThreadChange, backend: BackendDep) -> PlanThreadView:
    """Edit the comment's words or a reply's, resolve or reopen the thread, or move it to its passage's new words."""
    ref = ticket_ref(key, "plan")
    with backend.open() as ctx:
        try:
            anchor = (body.anchor.quote, body.anchor.prefix, body.anchor.suffix) if body.anchor is not None else None
            changed = plan_threads.change(
                ctx.conn, ref.id, thread_id, body=body.body, reply_id=body.reply, resolved=body.resolved, anchor=anchor
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("plan comment changed", extra={"ticket": ref.id, "plan_thread": thread_id, "channel": WEB})
    return plan_views.thread_view(changed)


@router.delete(
    "/tickets/{key}/plan-threads/{thread_id}",
    operation_id="deleteTicketPlanThread",
    summary="Delete a comment thread on a plan",
    responses=REFUSED,
)
def delete_thread(key: TicketKey, thread_id: ThreadId, backend: BackendDep) -> PlanThreadDeleted:
    """Delete the thread and its replies."""
    ref = ticket_ref(key, "plan")
    with backend.open() as ctx:
        try:
            plan_threads.delete(ctx.conn, ref.id, thread_id)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("plan comment deleted", extra={"ticket": ref.id, "plan_thread": thread_id, "channel": WEB})
    return PlanThreadDeleted(id=thread_id)
