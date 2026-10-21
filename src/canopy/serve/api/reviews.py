"""The reviews canopy keeps (DESIGN §21, D114), all untrusted; dismissing, sending findings, and a review's draft.

Each review run is readable on its own too, apart from its results: its session's transcript and its log's end. A
review of a PR the loop does not own is a draft of a review on it (DESIGN §34), edited and published through
`canopy review edit` and `publish`'s functions, so with their refusals: what posts is the version the page showed,
named by its hash, word for word, as the operator's own comment review, pending for them to submit unless they ask
canopy to submit it.
"""

from __future__ import annotations

import gzip
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Path, Request, Response

from canopy.core import chore_view, conversation, review_drafts, review_drafts_manage, review_runs
from canopy.infra import logs
from canopy.serve import review_draft_views, reviews
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, ReviewId, not_found
from canopy.serve.review_schema import (
    RequestedReview,
    ReviewDetail,
    ReviewDismissed,
    ReviewDismissRequest,
    ReviewDraft,
    ReviewDraftAddRequest,
    ReviewDraftBodyRequest,
    ReviewDraftCommentRequest,
    ReviewDraftPublished,
    ReviewDraftPublishRequest,
    ReviewSendRequest,
    ReviewSent,
    ReviewSummary,
)
from canopy.serve.transcript_schema import RawOutput, Transcript

if TYPE_CHECKING:
    import sqlite3

    from pydantic import BaseModel

TAG = "reviews"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)
# A body this long or longer goes gzipped to a browser that takes it; a shorter one saves too little to be worth it.
_GZIP_FROM = 1024

CommentNumber = Annotated[
    int,
    Path(
        ge=1,
        le=review_drafts.MAX_COMMENTS,
        description="The comment's number in the draft's newest version, from 1.",
    ),
]


@router.get("/reviews", operation_id="listReviews", summary="List the reviews")
def review_list(backend: BackendDep) -> list[ReviewSummary]:
    """The latest 100 review runs canopy kept, newest first."""
    with backend.open() as ctx:
        return reviews.reviews(ctx)


@router.get("/review-requests", operation_id="listReviewRequests", summary="List the reviews waiting on a tick")
def review_requests(backend: BackendDep) -> list[RequestedReview]:
    """The PRs the operator asked canopy to review that no review of is running yet, newest first."""
    with backend.open() as ctx:
        return reviews.requested(ctx)


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


# The reviewer's output, read back from the review's log on each request; never on the stream (DESIGN §22).
@router.get(
    "/reviews/{run_id}/transcript",
    operation_id="getReviewTranscript",
    summary="Get a review's transcript",
    responses=not_found("review run"),
)
def review_transcript(run_id: ReviewId, backend: BackendDep) -> Transcript:
    """The review run's session, read back from its log: agent output, untrusted and bounded."""
    with backend.open() as ctx:
        found = reviews.review_transcript(ctx, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no review run {run_id}")
    return found


# The end of the same log as written, the reviewer's stderr and exit included, read again on each request.
@router.get(
    "/reviews/{run_id}/output",
    operation_id="getReviewOutput",
    summary="Get a review's output",
    responses=not_found("review run"),
)
def review_output(run_id: ReviewId, backend: BackendDep) -> RawOutput:
    """The end of the review run's log as written, the reviewer's stderr included: untrusted and bounded."""
    with backend.open() as ctx:
        found = reviews.review_raw_output(ctx, run_id)
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
            conversation.dismiss(ctx.conn, ref, [str(body.finding)], channel=WEB, chores=defined, undo=body.undo)
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
        run=run_id,
        findings=findings,
        ticket_key=sent.ticket,
        message_id=sent.replied.message_id,
        new=sent.replied.new,
    )


@router.post(
    "/reviews/{run_id}/draft/body",
    operation_id="editReviewDraftBody",
    summary="Edit a review's draft's body",
    responses=REFUSED,
)
def draft_body(run_id: ReviewId, body: ReviewDraftBodyRequest, backend: BackendDep) -> ReviewDraft:
    """`canopy review edit ID --body --text TEXT`: the body of the review's draft, as a new version; empty for none.

    Refused as the CLI refuses it: `unknown`, `no_draft` for a review with none, a status past edits (`published`,
    `staged`, ...), and `bad_text`.
    """
    with backend.open() as ctx:
        try:
            version = review_drafts_manage.edit_body(ctx.conn, run_id, body.text, channel=WEB)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        _log.info("review draft edited", extra={"run_id": run_id, "version": version.number, "channel": WEB})
        return _draft(ctx.conn, run_id)


@router.post(
    "/reviews/{run_id}/draft/comments",
    operation_id="addReviewDraftComment",
    summary="Add a comment to a review's draft",
    responses=REFUSED,
)
def draft_add(run_id: ReviewId, body: ReviewDraftAddRequest, backend: BackendDep) -> ReviewDraft:
    """`canopy review edit ID --add PATH:LINE --text TEXT`: a comment on a line of the diff the review kept.

    Refused as the CLI refuses it: as an edit of the body is, `no_diff` once the diff is gone, `off_diff` for a line it
    does not show, and `too_many` past the comments a version may carry.
    """
    with backend.open() as ctx:
        try:
            version = review_drafts_manage.add_comment(
                ctx.conn,
                run_id,
                f"{body.path}:{body.line}",
                body.text,
                channel=WEB,
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
        _log.info("review draft edited", extra={"run_id": run_id, "version": version.number, "channel": WEB})
        return _draft(ctx.conn, run_id)


@router.post(
    "/reviews/{run_id}/draft/comments/{number}/edit",
    operation_id="editReviewDraftComment",
    summary="Edit a comment of a review's draft",
    responses=REFUSED,
)
def draft_comment(
    run_id: ReviewId,
    number: CommentNumber,
    body: ReviewDraftCommentRequest,
    backend: BackendDep,
) -> ReviewDraft:
    """`canopy review edit ID --comment N --text TEXT`: comment N's text, on the line it is on, as a new version.

    Refused as the CLI refuses it: as an edit of the body is, and `unknown` for a comment the version does not hold.
    """
    with backend.open() as ctx:
        try:
            version = review_drafts_manage.edit_comment(ctx.conn, run_id, number, body.text, channel=WEB)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        _log.info("review draft edited", extra={"run_id": run_id, "version": version.number, "channel": WEB})
        return _draft(ctx.conn, run_id)


@router.post(
    "/reviews/{run_id}/draft/comments/{number}/drop",
    operation_id="dropReviewDraftComment",
    summary="Drop a comment of a review's draft",
    responses=REFUSED,
)
def draft_drop(run_id: ReviewId, number: CommentNumber, backend: BackendDep) -> ReviewDraft:
    """`canopy review edit ID --drop N`: the draft without comment N, as a new version. Its finding stays as it is.

    Refused as the CLI refuses it: as an edit of the body is, and `unknown` for a comment the version does not hold.
    """
    with backend.open() as ctx:
        try:
            version = review_drafts_manage.drop_comment(ctx.conn, run_id, number, channel=WEB)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        _log.info("review draft edited", extra={"run_id": run_id, "version": version.number, "channel": WEB})
        return _draft(ctx.conn, run_id)


@router.post(
    "/reviews/{run_id}/draft/publish",
    operation_id="publishReviewDraft",
    summary="Publish a review's draft on its PR",
    responses=REFUSED,
)
def draft_publish(run_id: ReviewId, body: ReviewDraftPublishRequest, backend: BackendDep) -> ReviewDraftPublished:
    """`canopy review publish ID HASH [--submit]`: the version the page showed, as the operator's own review.

    It goes word for word, unmarked, as one comment review on the commit the review read, its comments on their lines;
    it approves nothing and requests no change. Left pending on GitHub for the operator to submit there, unless
    `submit`. Every check runs before anything posts: refused `no_draft`, `not_ours` for a PR a ticket holds now, a
    status that cannot publish (`published`, `staged`, `unconfirmed`, `publishing`), `stale` for a version the page no
    longer shows, `empty`, `no_diff`, `staged` for a PR holding a review the operator staged, and `no_post`.
    """
    with backend.open() as ctx:
        try:
            done = review_drafts_manage.publish(
                ctx.conn,
                ctx.config,
                ctx.runner,
                run_id,
                body.hash,
                submit=body.submit,
                channel=WEB,
                log=_log,
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
        _log.info(
            "review draft published",
            extra={
                "run_id": run_id,
                "version": done.version.number,
                "status": done.draft.status,
                "submit": body.submit,
                "channel": WEB,
            },
        )
        return ReviewDraftPublished(draft=_draft(ctx.conn, run_id), published=done.version.number, failed=done.failed)


def _draft(conn: sqlite3.Connection, run_id: int) -> ReviewDraft:
    """Review run `run_id`'s draft as it now stands, its comments placed on the diff it kept.

    Returns:
        The draft.

    Raises:
        HTTPException: 404 when the run or its draft is gone, which a verb that just changed it never leaves.
    """
    run = review_runs.get_review_run(conn, run_id)
    found = review_draft_views.of_review(conn, run, review_drafts.diff_of(run)) if run is not None else None
    if found is None:
        raise HTTPException(status_code=404, detail=f"review run {run_id} has no draft")
    return found


def _json(model: BaseModel, request: Request) -> Response:
    """`model` as JSON, gzipped when it is long and the browser takes gzip.

    Only this route compresses, not the whole app: the event stream must never be (gzip buffers it), and this body
    holds the PR's text and the reviewer's, never a secret beside them that its compressed size could give away.

    Returns:
        The response, with `Vary: Accept-Encoding` either way, since its body depends on that header.
    """
    # By alias, as FastAPI serializes a `response_model`, so this body stays what the schema declares.
    body = model.model_dump_json(by_alias=True).encode()
    headers = {"Vary": "Accept-Encoding"}
    if len(body) >= _GZIP_FROM and _takes_gzip(request.headers.get("accept-encoding", "")):
        body = gzip.compress(body)
        headers["Content-Encoding"] = "gzip"
    return Response(body, media_type="application/json", headers=headers)


def _takes_gzip(accept_encoding: str) -> bool:
    """Whether an `Accept-Encoding` header takes gzip: it names `gzip` with a weight above 0, or none, which is 1.

    Returns:
        True when the header lists gzip and does not refuse it with `q=0`; a weight that is not a number refuses it.
    """
    for part in accept_encoding.split(","):
        coding, _, params = part.partition(";")
        if coding.strip().lower() != "gzip":
            continue
        weight = 1.0
        for param in params.split(";"):
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        return weight > 0
    return False
