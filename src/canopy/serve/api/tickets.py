"""The tickets canopy has a record of, and the operator's verbs on one: start, stop, reply, forget."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.core import conversation
from canopy.infra import logs
from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, ticket_ref
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

router = APIRouter()
_log = logs.for_tick(None)


@router.get("/tickets", operation_id="listTickets")
def tickets(backend: BackendDep) -> list[TicketSummary]:
    with backend.open() as ctx:
        return views.tickets(ctx)


@router.get("/tickets/{key}", operation_id="getTicket", responses={404: {"description": "No such ticket."}})
def ticket(key: str, backend: BackendDep) -> TicketDetail:
    ref = ticket_ref(key, "show")
    with backend.open() as ctx:
        found = views.ticket(ctx, ref.id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no record of {ref}")
    return found


@router.post("/tickets/{key}/start", operation_id="startTicket", responses=REFUSED)
def start(key: str, backend: BackendDep) -> Started:
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


@router.post("/tickets/{key}/stop", operation_id="stopTicket", responses=REFUSED)
def stop(key: str, body: StopRequest, backend: BackendDep) -> Stopped:
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


@router.post("/tickets/{key}/replies", operation_id="replyTicket", responses=REFUSED)
def reply(key: str, body: ReplyRequest, backend: BackendDep) -> Replied:
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
@router.post("/tickets/{key}/forget", operation_id="forgetTicket", responses=REFUSED)
def forget(key: str, body: ForgetRequest, backend: BackendDep) -> Forgot:
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
