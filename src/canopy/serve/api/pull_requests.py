"""The PRs the journal knows, each with what the journal holds about it (DESIGN §22). Reads only; canopy writes no PR.

A PR is named by its URL, an opaque string with slashes in it, so it is a query parameter, never a path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from canopy.core import contract, conversation
from canopy.serve import pull_requests
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import not_found
from canopy.serve.schema import ErrorResponse, PullRequest, PullRequestDetail

TAG = "pull requests"
router = APIRouter(tags=[TAG])

PrUrl = Annotated[
    str,
    Query(
        min_length=1,
        max_length=conversation.MAX_PR_URL,
        description=f"The PR's plain https:// URL, at most {conversation.MAX_PR_URL} characters.",
    ),
]


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
        found = pull_requests.pull_request(ctx, url)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no record of {url}")
    return found
