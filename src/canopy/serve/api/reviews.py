"""The reviews canopy keeps instead of posting them (DESIGN §21, D114). Reads only; all of it is untrusted."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from canopy.serve import reviews
from canopy.serve.api.deps import BackendDep
from canopy.serve.schema import ReviewDetail, ReviewSummary

router = APIRouter()


@router.get("/reviews", operation_id="listReviews")
def review_list(backend: BackendDep) -> list[ReviewSummary]:
    with backend.open() as ctx:
        return reviews.reviews(ctx)


# The diff is read back from the file beside the run's log on each request; never on the stream.
@router.get("/reviews/{run_id}", operation_id="getReview", responses={404: {"description": "No such review run."}})
def review(run_id: Annotated[int, Path(ge=1, le=2**63 - 1)], backend: BackendDep) -> ReviewDetail:
    with backend.open() as ctx:
        found = reviews.review(ctx, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no review run {run_id}")
    return found
