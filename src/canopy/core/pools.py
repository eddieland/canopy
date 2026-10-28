"""What a worktree pool is to canopy, whichever implements it (DESIGN §18, What a pool guarantees; ROADMAP M45).

A pool leases slots, git worktrees of one repository's primary clone, to holders: `canopy:<KEY>` for a ticket's run,
`canopy:review:<id>` for a review, and `canopy-sync` while `canopy workspace sync` makes slots. `Pool` is the operations
every caller uses; treehouse (`core/treehouse.py`) is one implementation and canopy's own pool (`core/pool.py`) the
other. `tests/canopy/core/test_pool_contract.py` holds both to the same guarantees.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final, Protocol

from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictBool, StrictInt, StrictStr

if TYPE_CHECKING:
    from collections.abc import Sequence

HOLDER_PREFIX: Final = "canopy:"
# Held only while `canopy workspace sync` makes a pool's slots, which it then returns. Not a `canopy:` holder, so no
# ticket key can name it and reconcile leaves it to the next sync.
SYNC_HOLDER: Final = "canopy-sync"
# The holder of a reused slot whose seeding failed, in both pools: no ticket can name it and no lease's return clears
# it, so the slot is not reused until the operator releases it (DESIGN §18).
QUARANTINED: Final = "quarantined: worktree seeding failed"
AVAILABLE: Final = "available"


class PoolError(Exception):
    """A pool could not do what it was asked, or said something canopy cannot parse."""


def _null_is_empty(value: object) -> object:
    return "" if value is None else value


def _empty_is_null(value: object) -> object:
    return None if value == "" else value


def _null_is_list(value: object) -> object:
    return list[object]() if value is None else value


# treehouse writes "" for an unleased slot's lease fields and null for its `leased_at`; accept either for both.
MaybeStr = Annotated[StrictStr, BeforeValidator(_null_is_empty)]


class _Output(BaseModel):
    # A pool may add fields; canopy reads only the ones it needs.
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)


class Process(_Output):
    """A process running in a slot."""

    pid: StrictInt
    name: StrictStr


class Slot(_Output):
    """One worktree in a pool.

    `status` is one of available, leased, in-use, dirty, or damaged, or treehouse's unverified or "you're here".
    `branch` is empty for a detached or unreadable checkout; `branch_error` says why it could not be read. Only the web
    UI's worktrees page reads `branch`, `detached`, `branch_error`, and `processes` (DESIGN §22).
    """

    name: StrictStr
    path: Path
    status: StrictStr
    branch: MaybeStr = ""
    detached: StrictBool = False
    branch_error: MaybeStr = ""
    lease_id: MaybeStr = ""
    lease_holder: MaybeStr = ""
    leased_at: Annotated[StrictStr | None, BeforeValidator(_empty_is_null)] = None
    processes: Annotated[list[Process], BeforeValidator(_null_is_list)] = []

    @property
    def canopy_key(self) -> str | None:
        """The ticket key if canopy holds this slot's lease, else None."""
        if self.lease_holder.startswith(HOLDER_PREFIX):
            return self.lease_holder.removeprefix(HOLDER_PREFIX)
        return None


class Lease(_Output):
    """A leased slot: its path, the lease's id and holder, when it was taken, and the branch it is based on."""

    path: Path
    lease_id: StrictStr
    lease_holder: StrictStr
    leased_at: StrictStr
    base_branch: StrictStr


class ReturnOutcome(Enum):
    """What returning a slot came to."""

    RETURNED = "returned"
    # The slot is unknown, not leased, or leased under a different identity. Retrying cannot help.
    FAILED = "failed"
    # Dirty and not forced. canopy always forces, so this is an attention item, never a retry.
    DIRTY = "dirty"


class Pool(Protocol):
    """One repository's pool. Every operation raises `PoolError` when the pool cannot be read or changed."""

    def status(self) -> Sequence[Slot]:
        """Return every slot in the pool."""
        ...

    def lease(self, key: str, *, base: str | None = None) -> Lease:
        """Lease a slot for ticket `key`, based on branch `base` or the default branch, within the declared size."""
        ...

    def lease_as(self, holder: str, *, base: str | None = None, fetch: bool = True) -> Lease:
        """Lease any slot for `holder`, making one if none is reusable, up to the pool's bound."""
        ...

    def return_slot(self, path: Path, *, lease_id: str, lease_holder: str) -> ReturnOutcome:
        """Return slot `path` only if it is still held under this exact lease, forced."""
        ...

    def release(self, path: Path) -> ReturnOutcome:
        """Return slot `path` only if it is still held as `QUARANTINED`, forced, as the operator asks."""
        ...

    def destroy(self, path: Path) -> str | None:
        """Remove slot `path` if nothing in it could be lost. Returns None when it is gone, else why it was kept."""
        ...


def holder_for(key: str) -> str:
    """Return the lease holder canopy uses for ticket `key`."""
    return f"{HOLDER_PREFIX}{key}"
