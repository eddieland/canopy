"""The worktrees page's read: each pool's slots, from treehouse (serve/worktrees.py).

Not on the event stream: each read runs `treehouse status` once per pool.
"""

from __future__ import annotations

from fastapi import APIRouter

from canopy.serve import worktrees
from canopy.serve.api.deps import BackendDep
from canopy.serve.schema import Pool

router = APIRouter()


@router.get("/worktrees", operation_id="listWorktrees")
def pools(backend: BackendDep) -> list[Pool]:
    with backend.open() as ctx:
        return worktrees.pools(backend, ctx)
