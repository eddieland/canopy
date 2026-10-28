"""The PRs the journal knows (DESIGN §22), granting one more review, and the operator's review requests (§21).

canopy writes nothing to a PR: a grant and a request are the journal's. A PR is named by its URL, an opaque string with
slashes in it, so it is a query parameter, never a path.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, HTTPException, Query

from canopy.core import contract, conversation, review_requests
from canopy.infra import logs
from canopy.serve import pull_requests
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, not_found
from canopy.serve.schema import ErrorResponse, Granted
from canopy.serve.schema.review import (
    PullRequest,
    PullRequestDetail,
    ReviewRequestBody,
    ReviewRequested,
    ReviewRequestStopped,
)

TAG: Final = "pull requests"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)
# The kind a PR's grant is of, as `canopy grant URL review` names it.
_REVIEW: Final = "review"

PrUrl = Annotated[
    str,
    Query(
        min_length=1,
        max_length=conversation.MAX_PR_URL,
        description=f"The PR's plain https:// URL, at most {conversation.MAX_PR_URL} characters.",
    ),
]

# The 422 a route answers for a URL that is not a plain https:// URL of at most 300 characters.
_BAD_URL: Final = {422: {"model": ErrorResponse, "description": "Not a plain https:// URL of at most 300 characters."}}


@router.get("/pull-requests", operation_id="listPullRequests", summary="List the PRs")
def pull_request_list(backend: BackendDep) -> list[PullRequest]:
    """The PRs the journal knows, at most 100, most recent activity first: a unit's, or one canopy reviewed."""
    with backend.open() as ctx:
        return pull_requests.pull_requests(ctx)


@router.get(
    "/pull-request",
    operation_id="getPullRequest",
    summary="Get a PR",
    responses={
        **not_found("PR"),
        422: {"model": ErrorResponse, "description": "Not a plain https:// URL of at most 300 characters."},
    },
)
def pull_request(url: PrUrl, backend: BackendDep) -> PullRequestDetail:
    """One PR: the runs that pushed to it, its review runs, and the latest 20 decisions naming it.

    A PR only decisions name, such as a `review.query` match no review has run on yet, has a page too.

    Raises:
        HTTPException: 422 when `url` is not a plain https:// URL, 404 when nothing in the journal names it.
    """
    if not contract.plain_url(url, conversation.MAX_PR_URL):
        raise HTTPException(status_code=422, detail="url must be a PR's plain https:// URL")
    with backend.open() as ctx:
        found = pull_requests.pull_request(backend, ctx, url)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no record of {url}")
    return found


@router.post(
    "/pull-request/grants",
    operation_id="grantPullRequest",
    summary="Grant a PR a review",
    responses={
        **REFUSED,
        422: {"model": ErrorResponse, "description": "Not a plain https:// URL of at most 300 characters."},
    },
)
def grant(url: PrUrl, backend: BackendDep) -> Granted:
    """`canopy grant URL review`, for one more: the PR may have one more review run than now (DESIGN §21).

    Every review run still counts (D030), and it reviews nothing: the next tick decides. A URL canopy has never reviewed
    is refused `unknown`; one that is not a PR's, `bad_ref`.
    """
    try:
        ref = conversation.parse_ref(url)
        conversation.check_verb(ref, "grant")
    except conversation.Refused as r:
        raise RefusedError(r) from None
    if ref.kind != conversation.PR:
        raise RefusedError(conversation.Refused("bad_ref", f"{url} is not a PR's URL"))
    with backend.open() as ctx:
        try:
            granted = backend.grant(ctx, ref, _REVIEW, None)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("reviews granted", extra={"pr": ref.id, "runs": 1, "channel": WEB})
    return Granted(kind=_REVIEW, runs=granted.runs, limit=granted.limit)


@router.post(
    "/pull-request/start",
    operation_id="startPullRequestReview",
    summary="Ask for a PR to be reviewed",
    responses={**REFUSED, **_BAD_URL},
)
def start(url: PrUrl, backend: BackendDep, body: ReviewRequestBody | None = None) -> ReviewRequested:
    """`canopy start URL --review --notes TEXT --persona NAME`: review a PR the loop does not own, once, at its head.

    It reviews nothing now: the next tick does, in whichever of the workspace's repositories the PR is in, its reviewer
    given the notes, once in each persona chosen (DESIGN §21, §31). Notes or personas on a PR already requested replace
    its request's. Refused as the CLI refuses it: `reviews_off`, `bad_notes`, `unknown_persona`, `bad_persona`,
    `bad_pr`, and `loop_pr`.
    """
    ref = _pr_ref(url, "start")
    notes = body.notes if body is not None else None
    chosen = body.personas if body is not None else []
    with backend.open() as ctx:
        try:
            requested = review_requests.request(ctx.conn, ctx.config, ref, channel=WEB, notes=notes, chosen=chosen)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        shown = pull_requests.review_request(ctx.conn, requested.request)
    noted = requested.request.notes is not None
    _log.info(
        "review requested",
        extra={"pr": ref.id, "already": requested.already, "notes": noted, "personas": chosen, "channel": WEB},
    )
    return ReviewRequested(request=shown, already=requested.already)


@router.post(
    "/pull-request/stop",
    operation_id="stopPullRequestReview",
    summary="Stop reviewing a PR",
    responses={**REFUSED, **_BAD_URL},
)
def stop(url: PrUrl, backend: BackendDep) -> ReviewRequestStopped:
    """`canopy stop URL`: end the PR's open review request. A review of it already running finishes.

    Refused `not_requested` for a PR with no open request, and `bad_pr` for a URL that is not a PR's.
    """
    ref = _pr_ref(url, "stop")
    with backend.open() as ctx:
        try:
            stopped = review_requests.stop(ctx.conn, ref)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        shown = pull_requests.review_request(ctx.conn, stopped.request)
    _log.info("review request stopped", extra={"pr": ref.id, "channel": WEB})
    running = stopped.running.id if stopped.running is not None else None
    return ReviewRequestStopped(request=shown, running_review=running)


def _pr_ref(url: str, verb: str) -> conversation.Ref:
    """The PR `url` names, refused as the CLI refuses it.

    Returns:
        The PR's reference.

    Raises:
        RefusedError: `url` is not a reference (`bad_ref`), or not a PR's (`bad_pr`).
    """
    try:
        ref = conversation.parse_ref(url)
        conversation.check_verb(ref, verb)
    except conversation.Refused as r:
        raise RefusedError(r) from None
    if ref.kind != conversation.PR:
        raise RefusedError(conversation.Refused("bad_pr", f"{url} is not a PR's URL"))
    return ref
