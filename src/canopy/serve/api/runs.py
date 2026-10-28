"""The runs (DESIGN §8), each one's session transcript, and its log's end. Reads only; both are untrusted text."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import RunId, not_found
from canopy.serve.schema import Run, RunsSince
from canopy.serve.schema.transcript import RawOutput, Transcript

TAG = "runs"
router = APIRouter(tags=[TAG])


@router.get("/runs", operation_id="listRuns", summary="List the runs")
def runs(backend: BackendDep) -> list[Run]:
    """The running runs, then the 50 that ended last."""
    with backend.open() as ctx:
        return views.runs(ctx)


# Before `/runs/{run_id}`, which would otherwise take `since` for a run's id and refuse it.
@router.get("/runs/since", operation_id="getRunsSince", summary="Count what the runs did since a moment")
def runs_since(
    since: Annotated[datetime, Query(description="The moment to count from, as an ISO 8601 time with its offset.")],
    backend: BackendDep,
) -> RunsSince:
    """How many runs ended since `since`, and how many PRs they opened, over the whole journal."""
    with backend.open() as ctx:
        return views.runs_since(ctx, since)


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


# The end of the same log as written, setup output and stderr included, read again on each request (DESIGN §22).
@router.get(
    "/runs/{run_id}/output",
    operation_id="getRunOutput",
    summary="Get a run's output",
    responses=not_found("run"),
)
def run_output(run_id: RunId, backend: BackendDep) -> RawOutput:
    """The end of the run's log as written, its setup commands' and its stderr included: untrusted and bounded."""
    with backend.open() as ctx:
        found = views.run_raw_output(ctx, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    return found
