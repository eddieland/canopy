"""The JSON and SSE API under `{base_path}/api` (DESIGN §6, §19, §22).

Every route but `/session` needs a signed-in session, and a write its token too (auth.py). Writes go through the
functions the CLI's verbs call (`canopy.core.conversation`, and `canopy.core.pause` for the loop's pause), with channel
`web`, so the guards are the same ones; a guard's refusal is a 409 naming it. A forget also carries the ticket's key as
the operator typed it. A reload asks the loop to read its config again, as SIGHUP does; it writes nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from importlib.metadata import version
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.sse import EventSourceResponse

from canopy.core import chore_view, config, conversation, pause, search
from canopy.infra import logs
from canopy.serve import live, reviews, views, worktrees
from canopy.serve.auth import FAILED_SIGN_IN_SECONDS, OPEN_TOKEN, SESSION_SECONDS
from canopy.serve.schema import (
    AttentionItem,
    ChoreDetail,
    ChoreRunDetail,
    ChoreSummary,
    ConfigReload,
    ForgetRequest,
    Forgot,
    LastTick,
    LoopState,
    Meta,
    PauseChanged,
    Pool,
    RefusalResponse,
    Replied,
    ReplyRequest,
    ReviewDetail,
    ReviewSummary,
    Run,
    SearchResults,
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
    Transcript,
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
    _loop_routes(signed_in, backend)
    _run_routes(signed_in, backend)
    _search_routes(signed_in, backend)
    _review_routes(signed_in, backend)
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
        return Meta(version=version("canopy"), mock=backend.mock, ticket_url=backend.config.tracker.ticket_url or None)

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

    # Forgetting cannot be undone from here, so the request carries the ticket's key as the operator typed it, and a
    # mismatch is refused before anything is read (DESIGN §22).
    @api.post("/tickets/{key}/forget", operation_id="forgetTicket", responses=_REFUSED)
    def forget(key: str, body: ForgetRequest) -> Forgot:
        ref = ticket_ref(key, "forget")
        if body.confirm != ref.id:
            raise refusal(conversation.Refused("not_confirmed", f"type {ref} to confirm forgetting its work"))
        with backend.open() as ctx:
            try:
                forgot = conversation.forget(ctx.conn, ref, dispatch_lock=ctx.dispatch_lock_path)
            except conversation.Refused as r:
                raise refusal(r) from None
        log.info(
            "ticket forgotten", extra={"ticket": ref.id, "branch": forgot.branch, "prs": forgot.prs, "channel": WEB}
        )
        return Forgot(branch=forgot.branch, prs=forgot.prs)


def _chore_routes(api: APIRouter, backend: Backend) -> None:
    """The chores (DESIGN §19): what `canopy status` and `canopy show chore:NAME` print, and the operator's notes.

    Each run is readable on its own, with its session's transcript: untrusted text, read back from its log. Nothing
    here runs a chore: the overseer decides when one runs, and `canopy chore try` is the CLI's alone.
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

    @api.get(
        "/chores/{name}/runs/{run_id}",
        operation_id="getChoreRun",
        responses={404: {"description": "No such run of this chore."}},
    )
    def chore_run(name: str, run_id: Annotated[int, Path(ge=1, le=2**63 - 1)]) -> ChoreRunDetail:
        ref = chore_ref(name, "show")
        with backend.open() as ctx:
            found = views.chore_run_detail(ctx, ref.id, run_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"chore {ref.id!r} has no run {run_id}")
        return found

    # Agent output, read back from the run's log on each request; never on the stream (DESIGN §22).
    @api.get(
        "/chores/{name}/runs/{run_id}/transcript",
        operation_id="getChoreRunTranscript",
        responses={404: {"description": "No such run of this chore."}},
    )
    def chore_run_transcript(name: str, run_id: Annotated[int, Path(ge=1, le=2**63 - 1)]) -> Transcript:
        ref = chore_ref(name, "show")
        with backend.open() as ctx:
            found = views.chore_run_transcript(ctx, ref.id, run_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"chore {ref.id!r} has no run {run_id}")
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
    """The ticks (DESIGN §6): what `canopy decisions` prints, and the overseer's transcript.

    Reads only; a rationale and a transcript are untrusted text.
    """

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

    # The overseer's output, read back from the tick's output file on each request (DESIGN §22).
    @api.get(
        "/ticks/{tick_id}/transcript",
        operation_id="getTickTranscript",
        responses={404: {"description": "No such tick."}},
    )
    def tick_transcript(tick_id: Annotated[int, Path(ge=1, le=2**63 - 1)]) -> Transcript:
        with backend.open() as ctx:
            found = views.tick_transcript(ctx, tick_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"no tick {tick_id}")
        return found


def _loop_routes(api: APIRouter, backend: Backend) -> None:
    """The loop's pause (DESIGN §6), `canopy pause` and `canopy resume`, and asking it to read its config again.

    The loop reads both at every step of its wait.
    """
    log = logs.for_tick(None)

    @api.get("/loop", operation_id="getLoop")
    def loop() -> LoopState:
        with backend.open() as ctx:
            return views.loop_state(ctx)

    @api.post("/loop/pause", operation_id="pauseLoop")
    def pause_loop() -> PauseChanged:
        with backend.open() as ctx:
            already = pause.pause(ctx.conn, channel=WEB)
            state = views.loop_state(ctx)
        if not already:
            log.info("loop paused", extra={"channel": WEB})
        return PauseChanged(already=already, loop=state)

    @api.post("/loop/resume", operation_id="resumeLoop")
    def resume_loop() -> PauseChanged:
        with backend.open() as ctx:
            already = pause.resume(ctx.conn)
            state = views.loop_state(ctx)
        if not already:
            log.info("loop resumed", extra={"channel": WEB})
        return PauseChanged(already=already, loop=state)

    @api.post("/loop/reload", operation_id="reloadConfig", responses=_REFUSED)
    def reload_config() -> ConfigReload:
        with backend.open() as ctx:
            try:
                found = backend.reload(ctx)
            except config.ConfigError as e:
                raise refusal(conversation.Refused("config_invalid", str(e))) from None
        log.info("config reload asked for", extra={"channel": WEB, "changed": list(found.changed)})
        return ConfigReload(changed=list(found.changed), restart=list(found.restart), after_tick=found.after_tick)


def _run_routes(api: APIRouter, backend: Backend) -> None:
    """One run (DESIGN §8), and its session's transcript. Reads only; a transcript is untrusted text."""

    @api.get("/runs/{run_id}", operation_id="getRun", responses={404: {"description": "No such run."}})
    def run(run_id: Annotated[int, Path(ge=1, le=2**63 - 1)]) -> Run:
        with backend.open() as ctx:
            found = views.run_detail(ctx, run_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"no run {run_id}")
        return found

    # Agent output, read back from the run's log on each request; never on the stream (DESIGN §22).
    @api.get(
        "/runs/{run_id}/transcript", operation_id="getRunTranscript", responses={404: {"description": "No such run."}}
    )
    def run_transcript(run_id: Annotated[int, Path(ge=1, le=2**63 - 1)]) -> Transcript:
        with backend.open() as ctx:
            found = views.run_transcript(ctx, run_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"no run {run_id}")
        return found


def _search_routes(api: APIRouter, backend: Backend) -> None:
    """The search over the journal (DESIGN §22, Search). Reads only; every snippet is untrusted text."""

    @api.get(
        "/search", operation_id="search", responses={422: {"description": "Too short, too long, or too many words."}}
    )
    def find(q: Annotated[str, Query(min_length=search.MIN_QUERY, max_length=search.MAX_QUERY)]) -> SearchResults:
        with backend.open() as ctx:
            try:
                return views.found(ctx, q)
            except search.BadQueryError as e:
                raise HTTPException(status_code=422, detail=str(e)) from None


def _review_routes(api: APIRouter, backend: Backend) -> None:
    """The reviews canopy keeps instead of posting them (DESIGN §21, D114). Reads only; all of it is untrusted."""

    @api.get("/reviews", operation_id="listReviews")
    def review_list() -> list[ReviewSummary]:
        with backend.open() as ctx:
            return reviews.reviews(ctx)

    # The diff is read back from the file beside the run's log on each request; never on the stream.
    @api.get("/reviews/{run_id}", operation_id="getReview", responses={404: {"description": "No such review run."}})
    def review(run_id: Annotated[int, Path(ge=1, le=2**63 - 1)]) -> ReviewDetail:
        with backend.open() as ctx:
            found = reviews.review(ctx, run_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"no review run {run_id}")
        return found
