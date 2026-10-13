"""The chores (DESIGN §19): what `canopy status` and `canopy show chore:NAME` print, and the operator's notes.

Each run is readable on its own, with its session's transcript: untrusted text, read back from its log. Nothing here
runs a chore: the overseer decides when one runs, and `canopy chore try` is the CLI's alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Path

from canopy.core import chore_view, conversation
from canopy.infra import logs
from canopy.serve import views
from canopy.serve.api.refs import REFUSED, WEB, chore_ref, refusal
from canopy.serve.schema import ChoreDetail, ChoreRunDetail, ChoreSummary, Replied, ReplyRequest, Transcript

if TYPE_CHECKING:
    from canopy.serve.backend import Backend


def router(backend: Backend) -> APIRouter:
    """Return the chores' routes, reading and writing through `backend`."""
    api = APIRouter()
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

    @api.post("/chores/{name}/replies", operation_id="replyChore", responses=REFUSED)
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

    return api
