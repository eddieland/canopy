"""The reviews canopy keeps instead of posting them (DESIGN §21, D114). Reads only; all of it is untrusted."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.serve import reviews
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import ReviewId, not_found
from canopy.serve.schema import ReviewDetail, ReviewSummary

TAG = "reviews"
router = APIRouter(tags=[TAG])


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
