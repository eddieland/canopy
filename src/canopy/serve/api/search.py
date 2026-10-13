"""The search over the journal (DESIGN §22, Search). Reads only; every snippet is untrusted text."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.exceptions import RequestValidationError

from canopy.core import search
from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.schema import SearchResults

TAG = "search"
router = APIRouter(tags=[TAG])


@router.get("/search", operation_id="search", summary="Search the journal")
def find(
    q: Annotated[
        str,
        Query(
            min_length=search.MIN_QUERY,
            max_length=search.MAX_QUERY,
            description=f"The words to find, every one of them: {search.MIN_QUERY} to {search.MAX_QUERY} characters, "
            f"at most {search.MAX_WORDS} words.",
        ),
    ],
    backend: BackendDep,
) -> SearchResults:
    """The tickets, messages, chore runs, decisions, and ticks that hold every word of `q`, at most 20 a source.

    A query of too many words is a 422 like one too short or too long, so every 422 has the same body.
    """
    with backend.open() as ctx:
        try:
            return views.found(ctx, q)
        except search.BadQueryError as e:
            error = {"type": "value_error", "loc": ("query", "q"), "msg": str(e), "input": q}
            raise RequestValidationError([error]) from None
