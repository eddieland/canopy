"""The runs (DESIGN §8), and each one's session transcript. Reads only; a transcript is untrusted text."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import RunId, not_found
from canopy.serve.schema import Run, Transcript

TAG = "runs"
router = APIRouter(tags=[TAG])


@router.get("/runs", operation_id="listRuns", summary="List the runs")
def runs(backend: BackendDep) -> list[Run]:
    """The running runs, then the 50 that ended last."""
    with backend.open() as ctx:
        return views.runs(ctx)


@router.get("/runs/{run_id}", operation_id="getRun", summary="Get a run", responses=not_found("run"))
def run(run_id: RunId, backend: BackendDep) -> Run:
    """One run, as the runs list shows it."""
    with backend.open() as ctx:
        found = views.run_detail(ctx, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    return found


# Agent output, read back from the run's log on each request; never on the stream (DESIGN §22).
@router.get(
    "/runs/{run_id}/transcript",
    operation_id="getRunTranscript",
    summary="Get a run's transcript",
    responses=not_found("run"),
)
def run_transcript(run_id: RunId, backend: BackendDep) -> Transcript:
    """The run's session, read back from its log: agent output, untrusted and bounded."""
    with backend.open() as ctx:
        found = views.run_transcript(ctx, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    return found
