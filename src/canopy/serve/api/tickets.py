"""The tickets canopy has a record of, and the operator's verbs on one: start, stop, reply, forget."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.core import conversation
from canopy.infra import logs
from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, TicketKey, not_found, ticket_ref
from canopy.serve.schema import (
    ForgetRequest,
    Forgot,
    Replied,
    ReplyRequest,
    Started,
    Stopped,
    StopRequest,
    TicketDetail,
    TicketSummary,
)

TAG = "tickets"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get("/tickets", operation_id="listTickets", summary="List the tickets")
def tickets(backend: BackendDep) -> list[TicketSummary]:
    """The journal's tickets, most recent activity first, at most 200."""
    with backend.open() as ctx:
        return views.tickets(ctx)


@router.get(
    "/tickets/{key}",
    operation_id="getTicket",
    summary="Get a ticket",
    responses={**REFUSED, **not_found("ticket")},
)
def ticket(key: TicketKey, backend: BackendDep) -> TicketDetail:
    """One ticket: what `canopy show` prints, its latest 100 messages, and its latest 20 decisions.

    A key that is not a ticket's is refused `bad_ref` or `unsupported`; one canopy has no record of is a 404.
    """
    ref = ticket_ref(key, "show")
    with backend.open() as ctx:
        found = views.ticket(ctx, ref.id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no record of {ref}")
    return found


@router.post("/tickets/{key}/start", operation_id="startTicket", summary="Start a ticket", responses=REFUSED)
def start(key: TicketKey, backend: BackendDep) -> Started:
    """`canopy start`: work the ticket privately, in place of a queue label; its conversation stays in the journal."""
    ref = ticket_ref(key, "start")
    with backend.open() as ctx:
        try:
            started = conversation.start(ctx.conn, ctx.config, ref, repo=ctx.repo, channel=WEB)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("ticket started", extra={"ticket": ref.id, "already": started.already, "channel": WEB})
    run = started.running
    return Started(
        already=started.already,
        running_run=int(run["id"]) if run is not None else None,
        running_private=bool(run["private"]) if run is not None else None,
    )


@router.post("/tickets/{key}/stop", operation_id="stopTicket", summary="Stop a ticket", responses=REFUSED)
def stop(key: TicketKey, body: StopRequest, backend: BackendDep) -> Stopped:
    """`canopy stop`: no new dispatches; a running run finishes unless `now` ends it, as `--now` does."""
    ref = ticket_ref(key, "stop")
    with backend.open() as ctx:
        try:
            stopped = conversation.stop(ctx.conn, ref, channel=WEB)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        _log.info("ticket stopped", extra={"ticket": ref.id, "now": body.now, "channel": WEB})
        run = stopped.running
        ended = run is not None and body.now and backend.end_run(ctx, run)
    return Stopped(already=stopped.already, running_run=int(run["id"]) if run is not None else None, ended=ended)


@router.post("/tickets/{key}/replies", operation_id="replyTicket", summary="Reply on a ticket", responses=REFUSED)
def reply(key: TicketKey, body: ReplyRequest, backend: BackendDep) -> Replied:
    """`canopy reply`: add the operator's message to the ticket's conversation, answering its latest question.

    Idempotent on the submission id: a retried submission records nothing new.
    """
    ref = ticket_ref(key, "reply")
    with backend.open() as ctx:
        try:
            replied = conversation.reply(ctx.conn, ref, body.body, channel=WEB, submission=body.submission)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("operator replied", extra={"ticket": ref.id, "message_id": replied.message_id, "channel": WEB})
    return Replied(message_id=replied.message_id, answers=replied.answers, new=replied.new)


# Forgetting cannot be undone from here, so the request carries the ticket's key as the operator typed it, and a
# mismatch is refused before anything is read (DESIGN §22).
@router.post("/tickets/{key}/forget", operation_id="forgetTicket", summary="Forget a ticket's work", responses=REFUSED)
def forget(key: TicketKey, body: ForgetRequest, backend: BackendDep) -> Forgot:
    """`canopy forget`: drop the ticket's branch and PRs, so its next `implement` starts over.

    Cannot be undone: `confirm` must be the ticket's key, or it is refused `not_confirmed` before anything is read.
    The branch and PRs it returns are the operator's to close and delete.
    """
    ref = ticket_ref(key, "forget")
    if body.confirm != ref.id:
        raise RefusedError(conversation.Refused("not_confirmed", f"type {ref} to confirm forgetting its work"))
    with backend.open() as ctx:
        try:
            forgot = conversation.forget(ctx.conn, ref, dispatch_lock=ctx.dispatch_lock_path)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("ticket forgotten", extra={"ticket": ref.id, "branch": forgot.branch, "prs": forgot.prs, "channel": WEB})
    return Forgot(branch=forgot.branch, prs=forgot.prs)
