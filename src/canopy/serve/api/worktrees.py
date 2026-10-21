"""The worktrees page's read: each pool's slots, from the pool (serve/worktrees.py).

Not on the event stream: each read runs the pool's `status` once per pool.
"""

from __future__ import annotations

from fastapi import APIRouter

from canopy.serve import worktrees
from canopy.serve.api.deps import BackendDep
from canopy.serve.worktree_schema import Pool

TAG = "worktrees"
router = APIRouter(tags=[TAG])


@router.get("/worktrees", operation_id="listWorktrees", summary="List the worktrees")
def pools(backend: BackendDep) -> list[Pool]:
    """Each pool's slots, as the pool's `status` reports them, with the running run or review holding each."""
    with backend.open() as ctx:
        return worktrees.pools(backend, ctx)
