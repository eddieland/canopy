"""The ticks (DESIGN §6): what `canopy decisions` prints, and the overseer's transcript and output.

Reads only; a rationale, a transcript, and an output are untrusted text.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from canopy.serve import tick_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import TickId, not_found
from canopy.serve.schema import LastTick, Tick, TickDetail
from canopy.serve.schema.transcript import RawOutput, Transcript

TAG = "ticks"
router = APIRouter(tags=[TAG])


@router.get("/tick", operation_id="getLastTick", summary="Get the latest tick")
def last_tick(backend: BackendDep) -> LastTick:
    """The latest tick, as `canopy status`'s first line shows it, or none; and the newest message acknowledged."""
    with backend.open() as ctx:
        return tick_views.last_tick(ctx)


@router.get("/ticks", operation_id="listTicks", summary="List the ticks")
def ticks(
    backend: BackendDep,
    *,
    idle: Annotated[bool, Query(description="Only the live ticks `canopy loop` found idle.")] = False,
) -> list[Tick]:
    """The latest 50 ticks, newest first, or the latest 50 the loop found idle."""
    with backend.open() as ctx:
        return tick_views.ticks(ctx, idle=idle)


@router.get("/ticks/{tick_id}", operation_id="getTick", summary="Get a tick", responses=not_found("tick"))
def tick(tick_id: TickId, backend: BackendDep) -> TickDetail:
    """One tick: what `canopy decisions ID` prints."""
    with backend.open() as ctx:
        found = tick_views.tick_detail(ctx, tick_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no tick {tick_id}")
    return found


# The overseer's output, read back from the tick's output file on each request (DESIGN §22).
@router.get(
    "/ticks/{tick_id}/transcript",
    operation_id="getTickTranscript",
    summary="Get a tick's transcript",
    responses=not_found("tick"),
)
def tick_transcript(tick_id: TickId, backend: BackendDep) -> Transcript:
    """The overseer's session, read back from the tick's output: agent output, untrusted and bounded."""
    with backend.open() as ctx:
        found = tick_views.tick_transcript(ctx, tick_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no tick {tick_id}")
    return found


# The end of the same file as written, stderr included, read again on each request (DESIGN §22).
@router.get(
    "/ticks/{tick_id}/output",
    operation_id="getTickOutput",
    summary="Get a tick's output",
    responses=not_found("tick"),
)
def tick_output(tick_id: TickId, backend: BackendDep) -> RawOutput:
    """The end of the overseer's output as written, stderr included: agent output, untrusted and bounded."""
    with backend.open() as ctx:
        found = tick_views.tick_raw_output(ctx, tick_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no tick {tick_id}")
    return found
