"""The tickets canopy has a record of, and the operator's verbs on one: start, stop, reply, forget, grant, and choose.

Choosing is of the persona or the model one of the ticket's agents runs in or on.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.core import conversation, personas, ticket_models
from canopy.infra import logs
from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, TicketKey, not_found, ticket_ref
from canopy.serve.schema import Granted, Replied, ReplyRequest, TicketSummary
from canopy.serve.schema.model import AgentModel, ModelRequest
from canopy.serve.schema.persona import AgentPersona, PersonaRequest
from canopy.serve.schema.ticket import ForgetRequest, Forgot, GrantRequest, Started, Stopped, StopRequest, TicketDetail

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
        found = views.ticket(backend, ctx, ref.id)
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
        running_run=run.id if run is not None else None,
        running_private=run.private if run is not None else None,
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
    return Stopped(already=stopped.already, running_run=run.id if run is not None else None, ended=ended)


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
            forgot = conversation.forget(ctx.conn, ref, channel=WEB, dispatch_lock=ctx.dispatch_lock_path)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("ticket forgotten", extra={"ticket": ref.id, "branch": forgot.branch, "prs": forgot.prs, "channel": WEB})
    return Forgot(branch=forgot.branch, prs=forgot.prs)


@router.post(
    "/tickets/{key}/grants",
    operation_id="grantTicket",
    summary="Grant a ticket's unit a run",
    responses=REFUSED,
)
def grant(key: TicketKey, body: GrantRequest, backend: BackendDep) -> Granted:
    """`canopy grant KEY KIND --repo NAME`, for one more run: the unit may have one more run of the kind than now.

    Every run still counts (D030), and it dispatches nothing: the next tick decides. `repo` may be left out when the
    ticket has had runs in one repository only; else it is refused `unknown_repo`, as a ticket with no runs is.
    """
    ref = ticket_ref(key, "grant")
    with backend.open() as ctx:
        try:
            granted = backend.grant(ctx, ref, body.kind, body.repo)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info(
        "attempts granted",
        extra={"ticket": ref.id, "repo": granted.repo, "kind": body.kind, "runs": 1, "channel": WEB},
    )
    return Granted(kind=body.kind, repo=granted.repo, runs=granted.runs, limit=granted.limit)


@router.post(
    "/tickets/{key}/personas",
    operation_id="chooseTicketPersona",
    summary="Choose a persona for one of a ticket's agents",
    responses=REFUSED,
)
def persona(key: TicketKey, body: PersonaRequest, backend: BackendDep) -> AgentPersona:
    """`canopy persona KEY NAME --agent AGENT`, or with no `persona` `--clear` (DESIGN §31).

    It covers every run of that agent for the ticket, from its next, until cleared. A name with no file is refused
    `unknown_persona`, and a file canopy would not put in a prompt `bad_persona`.
    """
    ref = ticket_ref(key, "persona")
    with backend.open() as ctx:
        try:
            now = personas.choose(ctx.conn, ctx.config, ref.id, body.agent, body.persona, channel=WEB)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info(
        "persona chosen" if body.persona is not None else "persona cleared",
        extra={"ticket": ref.id, "agent": body.agent, "persona": body.persona, "channel": WEB},
    )
    return views.agent_persona(now)


@router.post(
    "/tickets/{key}/models",
    operation_id="chooseTicketModel",
    summary="Choose a model for one of a ticket's agents",
    responses=REFUSED,
)
def model(key: TicketKey, body: ModelRequest, backend: BackendDep) -> AgentModel:
    """`canopy model KEY MODEL --agent AGENT`, or with no `model` `--clear` (DESIGN §13).

    It covers every run of that agent for the ticket, from its next, until cleared. A model the runtime does not list is
    refused `unknown_model`, and a list that cannot be read `model_list_failed`.
    """
    ref = ticket_ref(key, "model")
    with backend.open() as ctx:
        try:
            now = ticket_models.choose(
                ctx.conn,
                ctx.config,
                ref.id,
                body.agent,
                body.model,
                listing=lambda: backend.models(ctx),
                channel=WEB,
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info(
        "model chosen" if body.model is not None else "model cleared",
        extra={"ticket": ref.id, "agent": body.agent, "model": body.model, "channel": WEB},
    )
    return views.agent_model(now)
