"""The worktrees page's read: each pool's slots, from treehouse (serve/worktrees.py).

Not on the event stream: each read runs `treehouse status` once per pool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from canopy.serve import worktrees
from canopy.serve.schema import Pool

if TYPE_CHECKING:
    from canopy.serve.backend import Backend


def router(backend: Backend) -> APIRouter:
    """Return the worktrees' route, reading through `backend`."""
    api = APIRouter()

    @api.get("/worktrees", operation_id="listWorktrees")
    def pools() -> list[Pool]:
        with backend.open() as ctx:
            return worktrees.pools(backend, ctx)

    return api
