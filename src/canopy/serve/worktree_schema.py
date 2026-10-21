"""The API's types for the worktrees page (DESIGN §22): each repository's pool, its slots, and what holds them.

Built on `schema.Model`, as every API type is (schema.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model, Run

type WorktreeState = Annotated[
    Literal["working", "held", "dirty", "idle", "broken"],
    Field(
        description="A worktree's state, in five groups the UI colors (DESIGN §22). `working` is held by a run or "
        "review the journal shows running; `held` is leased or in use by anything else; `dirty` is unleased with "
        "uncommitted changes; `broken` is damaged, unverified, or a status canopy does not know.",
    ),
]


class Process(Model):
    """A process the pool found running in a worktree."""

    pid: int
    """Its process id."""
    name: str
    """Its name, control characters dropped."""


class ReviewHold(Model):
    """A running review that holds a worktree (DESIGN §21)."""

    id: int
    """The review run's id."""
    pr_url: str
    """The URL of the PR it reviews."""
    started_at: datetime
    """When it started."""


class Worktree(Model):
    """One slot of a pool, as the pool's `status` reports it, with what in the journal holds it."""

    name: str
    """The slot's name in its pool."""
    path: str
    """From the workspace root when under it, as a workspace's pools are; else whole."""
    status: str
    """The pool's own word: available, leased, in-use, dirty, damaged, or unverified; treehouse's also "you're here"."""
    state: WorktreeState
    """Its status, grouped as the UI colors it."""
    branch: str | None = None
    """The branch checked out, or for a detached run's slot, the run's branch."""
    detached: bool = False
    """Whether its HEAD is detached."""
    branch_error: str | None = None
    """Why the pool could not read the branch."""
    holder: str | None = None
    """Who holds its lease, as the pool names them."""
    leased_at: datetime | None = None
    """When its lease was taken."""
    run: Run | None = None
    """The running run holding this lease, matched by lease id."""
    review: ReviewHold | None = None
    """The running review holding this lease, matched by lease id."""
    note: str | None = None
    """Something the operator should know about this slot, in the CLI's words: a stale canopy lease, say."""
    processes: list[Process] = []
    """The processes running in it, at most 20."""


class Pool(Model):
    """One repository's pool of worktrees, read when asked for."""

    repo: str
    """The repository, as the workspace names it."""
    size: int | None = None
    """The size `capacity` declares for it; None leaves it at the pool's bound: treehouse's `max_trees`, or 16 for
    canopy's (DESIGN §18)."""
    error: str | None = None
    """Why its worktrees could not be read: no clone, or the pool's read failed."""
    worktrees: list[Worktree] = []
    """Its slots."""
