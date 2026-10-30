"""The runs (DESIGN §8), each one's session transcript and its log's end, and the answer to a running run's question.

The transcript and the log are untrusted text. The answer is the operator's to the question a running run's card asks
(§41), as `canopy reply run:ID LETTER` gives it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from canopy.core import conversation
from canopy.infra import logs
from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, RunId, not_found
from canopy.serve.schema import Answered, AnswerRequest, Run, RunsSince
from canopy.serve.schema.transcript import RawOutput, Transcript

TAG = "runs"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


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


@router.post("/runs/{run_id}/answers", operation_id="answerRun", summary="Answer a run's question", responses=REFUSED)
def answer(run_id: RunId, body: AnswerRequest, backend: BackendDep) -> Answered:
    """`canopy reply run:ID LETTER`: the operator's answer to the question the running run's card asks.

    Refused `moved_on` when its card asks another question than the one asked at `asked_at`, which the page showed.
    """
    return answered(backend, conversation.Ref(conversation.RUN, str(run_id)), body)


def answered(backend: BackendDep, ref: conversation.Ref, body: AnswerRequest) -> Answered:
    """Record and pass on the operator's answer to the question run or review `ref`'s card asks, as the CLI does.

    Returns:
        What was answered.

    Raises:
        RefusedError: `conversation.answer` refused it.
    """
    with backend.open() as ctx:
        try:
            got = conversation.answer(ctx.conn, ref, body.letter, state_dir=ctx.state_dir, asked_at=body.asked_at)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info(
        "question answered",
        extra={"subject": str(ref), "answer": got.letter, "already": got.already, "channel": WEB},
    )
    return Answered(letter=got.letter, option=got.option, already=got.already, heard=got.heard)
