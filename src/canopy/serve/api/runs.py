"""The runs (DESIGN §8), and each one's session transcript. Reads only; a transcript is untrusted text."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Path

from canopy.serve import views
from canopy.serve.schema import Run, Transcript

if TYPE_CHECKING:
    from canopy.serve.backend import Backend


def router(backend: Backend) -> APIRouter:
    """Return the runs' routes, reading through `backend`."""
    api = APIRouter()

    @api.get("/runs", operation_id="listRuns")
    def runs() -> list[Run]:
        with backend.open() as ctx:
            return views.runs(ctx)

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

    return api
