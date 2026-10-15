"""The reviews canopy keeps instead of posting them (DESIGN §21, D114), all untrusted; dismissing, sending findings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.core import chore_view, conversation
from canopy.infra import logs
from canopy.serve import reviews
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, ReviewId, not_found
from canopy.serve.schema import (
    ReviewDetail,
    ReviewDismissed,
    ReviewDismissRequest,
    ReviewSendRequest,
    ReviewSent,
    ReviewSummary,
)

TAG = "reviews"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get("/reviews", operation_id="listReviews", summary="List the reviews")
def review_list(backend: BackendDep) -> list[ReviewSummary]:
    """The latest 100 review runs canopy kept, newest first."""
    with backend.open() as ctx:
        return reviews.reviews(ctx)


# The diff is read back from the file beside the run's log on each request; never on the stream.
@router.get("/reviews/{run_id}", operation_id="getReview", summary="Get a review", responses=not_found("review run"))
def review(run_id: ReviewId, backend: BackendDep) -> ReviewDetail:
    """One review run: its summary, its findings anchored on its diff, the diff, and the PR's other runs."""
    with backend.open() as ctx:
        found = reviews.review(ctx, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no review run {run_id}")
    return found


@router.post(
    "/reviews/{run_id}/dismissals",
    operation_id="dismissReviewFinding",
    summary="Dismiss a review's finding",
    responses=REFUSED,
)
def dismiss(run_id: ReviewId, body: ReviewDismissRequest, backend: BackendDep) -> ReviewDismissed:
    """`canopy dismiss review:ID N`: no worker or tick acts on the finding. With `undo`, `--undo` (DESIGN §21)."""
    ref = conversation.Ref(conversation.REVIEW, str(run_id))
    with backend.open() as ctx:
        try:
            defined = chore_view.defined(ctx.config, ctx.workspace)
            conversation.dismiss(ctx.conn, ref, str(body.finding), channel=WEB, chores=defined, undo=body.undo)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info(
        "finding dismissal taken back" if body.undo else "finding dismissed",
        extra={"subject": str(ref), "finding": body.finding, "channel": WEB},
    )
    return ReviewDismissed(run=run_id, finding=body.finding, dismissed=not body.undo)


@router.post(
    "/reviews/{run_id}/sends",
    operation_id="sendReviewFindings",
    summary="Send a review's findings to a worker",
    responses=REFUSED,
)
def send(run_id: ReviewId, body: ReviewSendRequest, backend: BackendDep) -> ReviewSent:
    """`canopy send review:ID N...`: a reply on the review's ticket, the operator's go-ahead on those findings.

    Idempotent on the submission id: a retried submission records nothing new (DESIGN §21).
    """
    ref = conversation.Ref(conversation.REVIEW, str(run_id))
    findings = sorted(set(body.findings))
    with backend.open() as ctx:
        try:
            sent = conversation.send(ctx.conn, ref, findings, channel=WEB, submission=body.submission)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info(
        "findings sent",
        extra={
            "subject": str(ref),
            "findings": findings,
            "ticket": sent.ticket,
            "message_id": sent.replied.message_id,
            "channel": WEB,
        },
    )
    return ReviewSent(
        run=run_id, findings=findings, ticket_key=sent.ticket, message_id=sent.replied.message_id, new=sent.replied.new
    )
