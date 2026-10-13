"""The search over the journal (DESIGN §22, Search). Reads only; every snippet is untrusted text."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query

from canopy.core import search
from canopy.serve import views
from canopy.serve.schema import SearchResults

if TYPE_CHECKING:
    from canopy.serve.backend import Backend


def router(backend: Backend) -> APIRouter:
    """Return the search's route, reading through `backend`."""
    api = APIRouter()

    @api.get(
        "/search", operation_id="search", responses={422: {"description": "Too short, too long, or too many words."}}
    )
    def find(q: Annotated[str, Query(min_length=search.MIN_QUERY, max_length=search.MAX_QUERY)]) -> SearchResults:
        with backend.open() as ctx:
            try:
                return views.found(ctx, q)
            except search.BadQueryError as e:
                raise HTTPException(status_code=422, detail=str(e)) from None

    return api
