"""The reviews canopy keeps instead of posting them (DESIGN §21, D114), all untrusted; dismissing, sending findings."""

from __future__ import annotations

import gzip
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, Response

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

if TYPE_CHECKING:
    from pydantic import BaseModel

TAG = "reviews"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)
# A body this long or longer goes gzipped to a browser that takes it; a shorter one saves too little to be worth it.
_GZIP_FROM = 1024


@router.get("/reviews", operation_id="listReviews", summary="List the reviews")
def review_list(backend: BackendDep) -> list[ReviewSummary]:
    """The latest 100 review runs canopy kept, newest first."""
    with backend.open() as ctx:
        return reviews.reviews(ctx)


# The diff is read back from the file beside the run's log on each request; never on the stream. A diff at the reading
# bounds is megabytes of JSON, read again on every tick while its page is open, so it goes gzipped (`_json`).
@router.get(
    "/reviews/{run_id}",
    operation_id="getReview",
    summary="Get a review",
    response_model=ReviewDetail,
    responses=not_found("review run"),
)
def review(run_id: ReviewId, request: Request, backend: BackendDep) -> Response:
    """One review run: its summary, its findings anchored on its diff, the diff, and the PR's other runs."""
    with backend.open() as ctx:
        found = reviews.review(ctx, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no review run {run_id}")
    return _json(found, request)


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


def _json(model: BaseModel, request: Request) -> Response:
    """`model` as JSON, gzipped when it is long and the browser takes gzip.

    Only this route compresses, not the whole app: the event stream must never be (gzip buffers it), and this body
    holds the PR's text and the reviewer's, never a secret beside them that its compressed size could give away.

    Returns:
        The response, with `Vary: Accept-Encoding` either way, since its body depends on that header.
    """
    body = model.model_dump_json().encode()
    headers = {"Vary": "Accept-Encoding"}
    if len(body) >= _GZIP_FROM and "gzip" in request.headers.get("accept-encoding", ""):
        body = gzip.compress(body)
        headers["Content-Encoding"] = "gzip"
    return Response(body, media_type="application/json", headers=headers)
