"""The ticks (DESIGN §6): what `canopy decisions` prints, and the overseer's transcript and output.

Reads only; a rationale, a transcript, and an output are untrusted text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Path

from canopy.serve import views
from canopy.serve.schema import LastTick, Tick, TickDetail, TickOutput, Transcript

if TYPE_CHECKING:
    from canopy.serve.backend import Backend


def router(backend: Backend) -> APIRouter:
    """Return the ticks' routes, reading through `backend`."""
    api = APIRouter()

    @api.get("/tick", operation_id="getTick")
    def last_tick() -> LastTick:
        with backend.open() as ctx:
            return views.last_tick(ctx)

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

    # The end of the same file as written, stderr included, read again on each request (DESIGN §22).
    @api.get("/ticks/{tick_id}/output", operation_id="getTickOutput", responses={404: {"description": "No such tick."}})
    def tick_output(tick_id: Annotated[int, Path(ge=1, le=2**63 - 1)]) -> TickOutput:
        with backend.open() as ctx:
            found = views.tick_raw_output(ctx, tick_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"no tick {tick_id}")
        return found

    return api
