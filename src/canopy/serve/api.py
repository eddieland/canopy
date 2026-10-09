"""The JSON and SSE API under `{base_path}/api` (DESIGN §6, §19, §22).

Every route but `/session` needs a signed-in session, and a write its token too (auth.py). Writes go through the
functions the CLI's verbs call (`canopy.core.conversation`), with channel `web`, so the guards are the same ones; a
guard's refusal is a 409 naming it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from importlib.metadata import version
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from fastapi.sse import EventSourceResponse

from canopy.core import chore_view, conversation
from canopy.infra import logs
from canopy.serve import live, views, worktrees
from canopy.serve.auth import FAILED_SIGN_IN_SECONDS, OPEN_TOKEN, SESSION_SECONDS
from canopy.serve.schema import (
    AttentionItem,
    ChoreDetail,
    ChoreSummary,
    LastTick,
    Meta,
    Pool,
    RefusalResponse,
    Replied,
    ReplyRequest,
    Run,
    Session,
    SignIn,
    Spend,
    Started,
    Stopped,
    StopRequest,
    StreamEvent,
    Tick,
    TickDetail,
    TicketDetail,
    TicketSummary,
)

if TYPE_CHECKING:
    from canopy.core.conversation import Ref
    from canopy.serve.auth import Sessions
    from canopy.serve.backend import Backend
    from canopy.serve.options import ServeOptions

WEB = "web"
_REFUSED: dict[int | str, dict[str, Any]] = {409: {"model": RefusalResponse, "description": "A guard refused it."}}


def refusal(r: conversation.Refused) -> HTTPException:
    """A guard's refusal as the 409 the UI shows."""
    return HTTPException(status_code=409, detail={"guard": r.guard, "reason": r.reason})


def ticket_ref(key: str, verb: str) -> Ref:
    """The ticket `key` names, refused as the CLI refuses it: `bad_ref`, or `unsupported` for another kind."""
    try:
        ref = conversation.parse_ref(key)
        conversation.check_verb(ref, verb)
    except conversation.Refused as r:
        raise refusal(r) from None
    if ref.kind != conversation.TICKET:
        raise refusal(conversation.Refused("unsupported", f"{ref} is not a ticket"))
    return ref


def chore_ref(name: str, verb: str) -> Ref:
    """The chore `name` names, refused as `canopy reply chore:NAME` refuses it: `bad_ref` for a name no chore has."""
    try:
        ref = conversation.parse_ref(f"{conversation.CHORE}:{name}")
        conversation.check_verb(ref, verb)
    except conversation.Refused as r:
        raise refusal(r) from None
    return ref


def router(options: ServeOptions, backend: Backend, sessions: Sessions) -> APIRouter:
    """Return the API's routes for a server set up with `options`, reading and writing through `backend`."""
    api = APIRouter(prefix=f"{options.base_path}/api")
    signed_in = APIRouter(dependencies=[Depends(sessions.require)])
    _session_routes(api, sessions)
    _read_routes(signed_in, backend)
    _live_routes(signed_in, backend)
    _write_routes(signed_in, backend)
    _chore_routes(signed_in, backend)
    _tick_routes(signed_in, backend)
    api.include_router(signed_in)
    return api


def _session_routes(api: APIRouter, sessions: Sessions) -> None:
    log = logs.for_tick(None)

    @api.get("/session", operation_id="getSession")
    def session(request: Request) -> Session:
        if sessions.open:
            return Session(signed_in=True, token=OPEN_TOKEN)
        signed = sessions.of(request)
        if signed is None:
            return Session(signed_in=False)
        return Session(signed_in=True, token=sessions.token(signed))

    @api.post("/session", operation_id="signIn", responses={401: {"description": "Not the listener secret."}})
    async def sign_in(body: SignIn, response: Response) -> Session:
        if not sessions.secret_matches(body.secret):
            log.warning("web UI sign-in refused: not the listener secret")
            await asyncio.sleep(FAILED_SIGN_IN_SECONDS)
            raise HTTPException(status_code=401, detail="that is not the listener secret")
        if sessions.open:
            return Session(signed_in=True, token=OPEN_TOKEN)
        value = sessions.issue()
        response.set_cookie(
            sessions.cookie_name,
            value,
            max_age=SESSION_SECONDS,
            path=sessions.cookie_path,
            httponly=True,
            samesite="strict",
        )
        signed = sessions.check(value)
        log.info("web UI signed in")
        return Session(signed_in=True, token=sessions.token(signed) if signed is not None else None)

    @api.delete("/session", operation_id="signOut")
    def sign_out(response: Response) -> Session:
        response.delete_cookie(sessions.cookie_name, path=sessions.cookie_path, httponly=True, samesite="strict")
        return Session(signed_in=sessions.open, token=OPEN_TOKEN if sessions.open else None)


def _read_routes(api: APIRouter, backend: Backend) -> None:
    @api.get("/meta", operation_id="getMeta")
    def meta() -> Meta:
        return Meta(version=version("canopy"), mock=backend.mock)

    @api.get("/attention", operation_id="listAttention")
    def attention() -> list[AttentionItem]:
        with backend.open() as ctx:
            return views.attention(backend, ctx)

    @api.get("/runs", operation_id="listRuns")
    def runs() -> list[Run]:
        with backend.open() as ctx:
            return views.runs(ctx)

    @api.get("/tick", operation_id="getTick")
    def last_tick() -> LastTick:
        with backend.open() as ctx:
            return views.last_tick(ctx)

    @api.get("/spend", operation_id="getSpend")
    def spend() -> Spend:
        with backend.open() as ctx:
            return views.spend(backend, ctx)

    @api.get("/tickets", operation_id="listTickets")
    def tickets() -> list[TicketSummary]:
        with backend.open() as ctx:
            return views.tickets(ctx)

    @api.get("/tickets/{key}", operation_id="getTicket", responses={404: {"description": "No such ticket."}})
    def ticket(key: str) -> TicketDetail:
        ref = ticket_ref(key, "show")
        with backend.open() as ctx:
            found = views.ticket(ctx, ref.id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"canopy has no record of {ref}")
        return found


def _live_routes(api: APIRouter, backend: Backend) -> None:
    """What is read from beyond a single journal query: treehouse's pools, and the event stream."""

    # Not on the event stream: each read runs `treehouse status` once per pool (worktrees.py).
    @api.get("/worktrees", operation_id="listWorktrees")
    def pools() -> list[Pool]:
        with backend.open() as ctx:
            return worktrees.pools(backend, ctx)

    # FastAPI's SSE support sends `Cache-Control: no-cache` and `X-Accel-Buffering: no`, so a proxy or an SSH forward
    # streams it, and a keepalive comment after 15 idle seconds. Nothing may compress this route: gzip buffers.
    @api.get("/events", operation_id="streamEvents", response_class=EventSourceResponse)
    async def events() -> AsyncIterator[StreamEvent]:
        async for event in live.events(backend):
            yield event


def _write_routes(api: APIRouter, backend: Backend) -> None:
    log = logs.for_tick(None)

    @api.post("/tickets/{key}/start", operation_id="startTicket", responses=_REFUSED)
    def start(key: str) -> Started:
        ref = ticket_ref(key, "start")
        with backend.open() as ctx:
            try:
                started = conversation.start(ctx.conn, ctx.config, ref, repo=ctx.repo, channel=WEB)
            except conversation.Refused as r:
                raise refusal(r) from None
        log.info("ticket started", extra={"ticket": ref.id, "already": started.already, "channel": WEB})
        run = started.running
        return Started(
            already=started.already,
            running_run=int(run["id"]) if run is not None else None,
            running_private=bool(run["private"]) if run is not None else None,
        )

    @api.post("/tickets/{key}/stop", operation_id="stopTicket", responses=_REFUSED)
    def stop(key: str, body: StopRequest) -> Stopped:
        ref = ticket_ref(key, "stop")
        with backend.open() as ctx:
            try:
                stopped = conversation.stop(ctx.conn, ref, channel=WEB)
            except conversation.Refused as r:
                raise refusal(r) from None
            log.info("ticket stopped", extra={"ticket": ref.id, "now": body.now, "channel": WEB})
            run = stopped.running
            ended = run is not None and body.now and backend.end_run(ctx, run)
        return Stopped(already=stopped.already, running_run=int(run["id"]) if run is not None else None, ended=ended)

    @api.post("/tickets/{key}/replies", operation_id="replyTicket", responses=_REFUSED)
    def reply(key: str, body: ReplyRequest) -> Replied:
        ref = ticket_ref(key, "reply")
        with backend.open() as ctx:
            try:
                replied = conversation.reply(ctx.conn, ref, body.body, channel=WEB, submission=body.submission)
            except conversation.Refused as r:
                raise refusal(r) from None
        log.info("operator replied", extra={"ticket": ref.id, "message_id": replied.message_id, "channel": WEB})
        return Replied(message_id=replied.message_id, answers=replied.answers, new=replied.new)


def _chore_routes(api: APIRouter, backend: Backend) -> None:
    """The chores (DESIGN §19): what `canopy status` and `canopy show chore:NAME` print, and the operator's notes.

    Nothing here runs a chore: the overseer decides when one runs, and `canopy chore try` is the CLI's alone.
    """
    log = logs.for_tick(None)

    @api.get("/chores", operation_id="listChores")
    def chores() -> list[ChoreSummary]:
        with backend.open() as ctx:
            return views.chores(backend, ctx)

    @api.get("/chores/{name}", operation_id="getChore", responses={404: {"description": "No such chore."}})
    def chore(name: str) -> ChoreDetail:
        ref = chore_ref(name, "show")
        with backend.open() as ctx:
            found = views.chore(backend, ctx, ref.id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"no chore {ref.id!r} is defined for this workspace")
        return found

    @api.post("/chores/{name}/replies", operation_id="replyChore", responses=_REFUSED)
    def note(name: str, body: ReplyRequest) -> Replied:
        ref = chore_ref(name, "reply")
        with backend.open() as ctx:
            try:
                defined = chore_view.defined(ctx.config, ctx.workspace)
                replied = conversation.reply(
                    ctx.conn, ref, body.body, channel=WEB, submission=body.submission, chores=defined
                )
            except conversation.Refused as r:
                raise refusal(r) from None
        log.info("operator replied", extra={"subject": str(ref), "message_id": replied.message_id, "channel": WEB})
        return Replied(message_id=replied.message_id, answers=replied.answers, new=replied.new)


def _tick_routes(api: APIRouter, backend: Backend) -> None:
    """The ticks (DESIGN §6): what `canopy decisions` prints. Reads only; a rationale is untrusted text."""

    @api.get("/ticks", operation_id="listTicks")
    def ticks() -> list[Tick]:
        with backend.open() as ctx:
            return views.ticks(ctx)

    @api.get("/ticks/{tick_id}", operation_id="showTick", responses={404: {"description": "No such tick."}})
    def tick(tick_id: Annotated[int, Path(ge=1, le=2**63 - 1)]) -> TickDetail:
        with backend.open() as ctx:
            found = views.tick_detail(ctx, tick_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"no tick {tick_id}")
        return found
