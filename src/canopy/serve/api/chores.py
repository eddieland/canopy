"""The chores (DESIGN §19): what `canopy status` and `canopy show chore:NAME` print, notes, and dismissed findings.

Each run is readable on its own, with its session's transcript: untrusted text, read back from its log. The operator
can try a chore as `canopy chore try` does, recorded, its run going on in the background; the overseer still decides
when one runs on its own.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.core import chore_view, conversation
from canopy.infra import logs
from canopy.serve import chore_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, ChoreName, ChoreRunId, RefusedError, chore_ref, not_found
from canopy.serve.schema import (
    ChoreDetail,
    ChoreRunDetail,
    ChoreSummary,
    ChoreTried,
    Dismissed,
    DismissRequest,
    Replied,
    ReplyRequest,
    Transcript,
)

TAG = "chores"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get("/chores", operation_id="listChores", summary="List the chores")
def chores(backend: BackendDep) -> list[ChoreSummary]:
    """Each chore configured for this workspace, as `canopy status` lists it; none while `capacity.max_chores` is 0."""
    with backend.open() as ctx:
        return chore_views.chores(backend, ctx)


@router.get(
    "/chores/{name}",
    operation_id="getChore",
    summary="Get a chore",
    responses={**REFUSED, **not_found("chore defined for this workspace")},
)
def chore(name: ChoreName, backend: BackendDep) -> ChoreDetail:
    """One chore defined for this workspace, configured or not: what `canopy show chore:NAME` prints.

    A name no chore could have is refused `bad_ref`; one not defined here is a 404.
    """
    ref = chore_ref(name, "show")
    with backend.open() as ctx:
        found = chore_views.chore(backend, ctx, ref.id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no chore {ref.id!r} is defined for this workspace")
    return found


@router.get(
    "/chores/{name}/runs/{run_id}",
    operation_id="getChoreRun",
    summary="Get a chore run",
    responses={**REFUSED, **not_found("run of this chore")},
)
def chore_run(name: ChoreName, run_id: ChoreRunId, backend: BackendDep) -> ChoreRunDetail:
    """One run of the chore: its row, the whole of its summary, the harness's note, and its findings.

    A run is found only under its own chore, and a chore since deleted from the config keeps its runs.
    """
    ref = chore_ref(name, "show")
    with backend.open() as ctx:
        found = chore_views.chore_run_detail(ctx, ref.id, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"chore {ref.id!r} has no run {run_id}")
    return found


# Agent output, read back from the run's log on each request; never on the stream (DESIGN §22).
@router.get(
    "/chores/{name}/runs/{run_id}/transcript",
    operation_id="getChoreRunTranscript",
    summary="Get a chore run's transcript",
    responses={**REFUSED, **not_found("run of this chore")},
)
def chore_run_transcript(name: ChoreName, run_id: ChoreRunId, backend: BackendDep) -> Transcript:
    """The chore run's session, read back from its log: agent output, untrusted and bounded."""
    ref = chore_ref(name, "show")
    with backend.open() as ctx:
        found = chore_views.chore_run_transcript(ctx, ref.id, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"chore {ref.id!r} has no run {run_id}")
    return found


@router.post("/chores/{name}/replies", operation_id="replyChore", summary="Add a note to a chore", responses=REFUSED)
def note(name: ChoreName, body: ReplyRequest, backend: BackendDep) -> Replied:
    """`canopy reply chore:NAME`: a note the chore's next runs read.

    Idempotent on the submission id: a retried submission records nothing new.
    """
    ref = chore_ref(name, "reply")
    with backend.open() as ctx:
        try:
            defined = chore_view.defined(ctx.config, ctx.workspace)
            replied = conversation.reply(
                ctx.conn,
                ref,
                body.body,
                channel=WEB,
                submission=body.submission,
                chores=defined,
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("operator replied", extra={"subject": str(ref), "message_id": replied.message_id, "channel": WEB})
    return Replied(message_id=replied.message_id, answers=replied.answers, new=replied.new)


@router.post(
    "/chores/{name}/tries",
    operation_id="tryChore",
    summary="Try a chore now",
    responses={**REFUSED, **not_found("chore defined for this workspace")},
)
def try_now(name: ChoreName, backend: BackendDep) -> ChoreTried:
    """`canopy chore try NAME`: run the chore now, recorded as the CLI records it, in a process of its own.

    No guard on time or capacity applies, as none does to the CLI's try (DESIGN §19); a chore with a run running is
    refused `running`. The run's findings reach the attention list when it ends, and the chore's page shows it until
    then.
    """
    ref = chore_ref(name, "show")
    with backend.open() as ctx:
        if ref.id not in chore_view.defined(ctx.config, ctx.workspace):
            raise HTTPException(status_code=404, detail=f"no chore {ref.id!r} is defined for this workspace")
        try:
            run_id = backend.try_chore(ctx, ref.id)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("chore tried", extra={"chore": ref.id, "chore_run_id": run_id, "channel": WEB})
    return ChoreTried(chore=ref.id, run_id=run_id)


@router.post(
    "/chores/{name}/dismissals",
    operation_id="dismissFinding",
    summary="Dismiss a chore's finding",
    responses=REFUSED,
)
def dismiss(name: ChoreName, body: DismissRequest, backend: BackendDep) -> Dismissed:
    """`canopy dismiss chore:NAME ID`: the finding is off the attention list until the chore stops reporting it.

    With `undo`, `--undo`: the dismissal is taken back and the finding listed again (DESIGN §19).
    """
    ref = chore_ref(name, "dismiss")
    with backend.open() as ctx:
        try:
            defined = chore_view.defined(ctx.config, ctx.workspace)
            conversation.dismiss(ctx.conn, ref, [body.finding], channel=WEB, chores=defined, undo=body.undo)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        backend.write_attention(ctx)
    _log.info(
        "finding dismissal taken back" if body.undo else "finding dismissed",
        extra={"chore": ref.id, "finding": body.finding, "channel": WEB},
    )
    return Dismissed(chore=ref.id, finding=body.finding, dismissed=not body.undo)
