"""The chores (DESIGN §19): what `canopy status` and `canopy show chore:NAME` print, notes, and dismissed findings.

Each run is readable on its own, with its session's transcript: untrusted text, read back from its log. Nothing here
runs a chore: the overseer decides when one runs, and `canopy chore try` is the CLI's alone.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from canopy.core import chore_view, conversation
from canopy.infra import logs
from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, chore_ref
from canopy.serve.schema import (
    ChoreDetail,
    ChoreRunDetail,
    ChoreSummary,
    Dismissed,
    DismissRequest,
    Replied,
    ReplyRequest,
    Transcript,
)

router = APIRouter()
_log = logs.for_tick(None)


@router.get("/chores", operation_id="listChores")
def chores(backend: BackendDep) -> list[ChoreSummary]:
    with backend.open() as ctx:
        return views.chores(backend, ctx)


@router.get("/chores/{name}", operation_id="getChore", responses={404: {"description": "No such chore."}})
def chore(name: str, backend: BackendDep) -> ChoreDetail:
    ref = chore_ref(name, "show")
    with backend.open() as ctx:
        found = views.chore(backend, ctx, ref.id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no chore {ref.id!r} is defined for this workspace")
    return found


@router.get(
    "/chores/{name}/runs/{run_id}",
    operation_id="getChoreRun",
    responses={404: {"description": "No such run of this chore."}},
)
def chore_run(name: str, run_id: Annotated[int, Path(ge=1, le=2**63 - 1)], backend: BackendDep) -> ChoreRunDetail:
    ref = chore_ref(name, "show")
    with backend.open() as ctx:
        found = views.chore_run_detail(ctx, ref.id, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"chore {ref.id!r} has no run {run_id}")
    return found


# Agent output, read back from the run's log on each request; never on the stream (DESIGN §22).
@router.get(
    "/chores/{name}/runs/{run_id}/transcript",
    operation_id="getChoreRunTranscript",
    responses={404: {"description": "No such run of this chore."}},
)
def chore_run_transcript(
    name: str, run_id: Annotated[int, Path(ge=1, le=2**63 - 1)], backend: BackendDep
) -> Transcript:
    ref = chore_ref(name, "show")
    with backend.open() as ctx:
        found = views.chore_run_transcript(ctx, ref.id, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"chore {ref.id!r} has no run {run_id}")
    return found


@router.post("/chores/{name}/replies", operation_id="replyChore", responses=REFUSED)
def note(name: str, body: ReplyRequest, backend: BackendDep) -> Replied:
    ref = chore_ref(name, "reply")
    with backend.open() as ctx:
        try:
            defined = chore_view.defined(ctx.config, ctx.workspace)
            replied = conversation.reply(
                ctx.conn, ref, body.body, channel=WEB, submission=body.submission, chores=defined
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("operator replied", extra={"subject": str(ref), "message_id": replied.message_id, "channel": WEB})
    return Replied(message_id=replied.message_id, answers=replied.answers, new=replied.new)


@router.post("/chores/{name}/dismissals", operation_id="dismissFinding", responses=REFUSED)
def dismiss(name: str, body: DismissRequest, backend: BackendDep) -> Dismissed:
    ref = chore_ref(name, "dismiss")
    with backend.open() as ctx:
        try:
            defined = chore_view.defined(ctx.config, ctx.workspace)
            conversation.dismiss(ctx.conn, ref, body.finding, channel=WEB, chores=defined, undo=body.undo)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info(
        "finding dismissal taken back" if body.undo else "finding dismissed",
        extra={"chore": ref.id, "finding": body.finding, "channel": WEB},
    )
    return Dismissed(chore=ref.id, finding=body.finding, dismissed=not body.undo)
