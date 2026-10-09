"""The treehouse worktree pool, through its CLI (D002).

canopy uses `status --json`, `get --lease --json`, and `return --force --if-lease-id --if-lease-holder`, and
`canopy workspace sync` also uses `destroy --yes` to remove idle slots a pool has beyond its declared size. Lease
holders are `canopy:<KEY>`; sync's own short leases are `canopy-sync`, which reconcile never returns.

treehouse finds a repository's pool from its working directory. In a workspace, every command runs in the repository's
primary clone with `TREEHOUSE_ROOT` set to the workspace root, and `get` pins where a new slot goes, so the pools live
under `<workspace>/.treehouse/` whatever treehouse's own config says (DESIGN §18). A `Pool` says which, and which
personal `.worktreeinclude` every `get` passes as `--include-file` (DESIGN §9).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
)

from canopy.infra import procs

HOLDER_PREFIX = "canopy:"
# Held only while `canopy workspace sync` makes a pool's slots, which it then returns. Not a `canopy:` holder, so no
# ticket key can name it and reconcile leaves it to the next sync.
SYNC_HOLDER = "canopy-sync"
AVAILABLE = "available"
ROOT_ENV = "TREEHOUSE_ROOT"
# treehouse's own default layout, pinned: a repository's `treehouse.toml` cannot move a workspace's slots, and `return`
# finds a slot's pool two levels above it even when the repository's clone is gone.
WORKTREE_PATH = "{pool}/{slot}/{repo}"
_TIMEOUT_SECONDS = 120


class TreehouseError(Exception):
    """treehouse failed or said something canopy cannot parse."""


def _null_is_empty(value: object) -> object:
    return "" if value is None else value


def _empty_is_null(value: object) -> object:
    return None if value == "" else value


def _null_is_list(value: object) -> object:
    return list[object]() if value is None else value


# treehouse writes "" for an unleased slot's lease fields and null for its `leased_at`; accept either for both.
MaybeStr = Annotated[StrictStr, BeforeValidator(_null_is_empty)]


class _Output(BaseModel):
    # treehouse may add fields; canopy reads only the ones it needs.
    model_config = ConfigDict(extra="ignore", frozen=True)


class Process(_Output):
    """A process treehouse found running in a slot."""

    pid: StrictInt
    name: StrictStr


class Slot(_Output):
    """One worktree in the pool, from `treehouse status --json`.

    `status` is treehouse's word: available, leased, in-use, dirty, damaged, unverified, or "you're here". `branch` is
    empty for a detached or unreadable checkout; `branch_error` says why it could not be read. Only the web UI's
    worktrees page reads `branch`, `detached`, `branch_error`, and `processes` (DESIGN §22).
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
    """A slot leased with `treehouse get --lease --json`."""

    path: Path
    lease_id: StrictStr
    lease_holder: StrictStr
    leased_at: StrictStr
    base_branch: StrictStr


class _Held(_Output):
    """The fields of a `get` allocation needed to return it, for output that is not a full `Lease`."""

    path: Path
    lease_id: StrictStr
    lease_holder: StrictStr


_SLOTS = TypeAdapter(list[Slot])


class ReturnOutcome(Enum):
    """What `treehouse return` said."""

    RETURNED = "returned"
    # Exit 1: the slot is unknown, not leased, or leased under a different identity. Retrying cannot help.
    FAILED = "failed"
    # Exit 3: dirty and not forced. canopy always forces, so this is an attention item, never a retry.
    DIRTY = "dirty"


@dataclass(frozen=True)
class Pool:
    """Where treehouse runs for one repository's pool.

    `cwd` is a directory in the repository, from which treehouse finds its pool; None is this process's working
    directory. `root` is the workspace root, passed as `TREEHOUSE_ROOT`; None leaves treehouse's own config in charge.
    `slots` is the pool's declared size (`capacity.slots_for`), which `lease` never grows the pool past. None leaves the
    size to treehouse's `max_trees`. `include_file` is the operator's own `.worktreeinclude` (`paths.worktree_include`),
    which treehouse reads in place of the committed one; None leaves the committed one.
    """

    cwd: Path | None = None
    root: Path | None = None
    slots: int | None = None
    include_file: Path | None = None


DEFAULT_POOL = Pool()


def holder_for(key: str) -> str:
    """Return the lease holder canopy uses for ticket `key`."""
    return f"{HOLDER_PREFIX}{key}"


def _run(runner: procs.Runner, args: list[str], pool: Pool) -> procs.Result:
    env = {ROOT_ENV: str(pool.root)} if pool.root is not None else None
    try:
        result = runner.run(["treehouse", *args], cwd=pool.cwd, env=env, timeout=_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        raise TreehouseError(str(e)) from e
    if result.timed_out:
        raise TreehouseError(f"treehouse {args[0]} timed out")
    return result


def _fail(result: procs.Result) -> TreehouseError:
    detail = result.stderr.strip() or result.stdout.strip()
    return TreehouseError(f"treehouse {result.args[1]} exited {result.returncode}: {detail}")


def status(runner: procs.Runner, *, pool: Pool = DEFAULT_POOL) -> list[Slot]:
    """Return every slot in the pool."""
    result = _run(runner, ["status", "--json"], pool)
    if not result.ok:
        raise _fail(result)
    try:
        return _SLOTS.validate_json(result.stdout)
    except ValidationError as e:
        raise TreehouseError(f"treehouse status: unexpected output: {e}") from e


def lease(runner: procs.Runner, key: str, *, base: str | None = None, pool: Pool = DEFAULT_POOL) -> Lease:
    """Lease a slot for ticket `key` from `pool`, optionally based on branch `base`, within the pool's declared size.

    If treehouse leased a slot but its output is not a `Lease`, the slot is returned before the error is raised when
    the output still names it. When it does not, or the return fails, the next tick's reconcile returns it. The error
    says which happened.

    With `pool.slots` set, a pool with that many slots busy is full, and treehouse is not asked: it would make another,
    or hand out a slot of a pool bigger than declared. treehouse may still make one when the available slots are not
    reusable (another clone's, say); that slot is returned and destroyed, and the lease refused, so the pool keeps its
    size (DESIGN §18).
    """
    if pool.slots is None:
        return lease_as(runner, holder_for(key), base=base, pool=pool)
    before = status(runner, pool=pool)
    busy = sum(s.status != AVAILABLE for s in before)
    if busy >= pool.slots:
        raise TreehouseError(f"{busy} of its slots are busy, and capacity declares {pool.slots} for this pool")
    leased = lease_as(runner, holder_for(key), base=base, pool=pool)
    if len(before) < pool.slots or any(s.path == leased.path for s in before):
        return leased
    raise TreehouseError(
        f"no slot of the {len(before)} could be reused, and capacity declares {pool.slots} for this pool; "
        f"{_undo(runner, leased, pool)}"
    )


def _undo(runner: procs.Runner, leased: Lease, pool: Pool) -> str:
    """Return and destroy a slot `lease` made past the pool's size, and say how far that got, for the error."""
    outcome = return_slot(runner, leased.path, lease_id=leased.lease_id, lease_holder=leased.lease_holder, pool=pool)
    if outcome is not ReturnOutcome.RETURNED:
        return f"returning the new slot {leased.path} said {outcome.value}; the next tick's reconcile returns it"
    kept = destroy(runner, leased.path, pool=pool)
    if kept is not None:
        return f"treehouse kept the new slot {leased.path} ({kept}); `canopy workspace sync` removes it once it can"
    return f"the new slot {leased.path} was removed"


def lease_as(
    runner: procs.Runner, holder: str, *, base: str | None = None, pool: Pool = DEFAULT_POOL, fetch: bool = True
) -> Lease:
    """Lease any slot of `pool` for `holder`, making one if none is available, whatever the pool's declared size.

    Without `fetch`, the slot is cut from the clone's existing refs; a later `get` that reuses it fetches. treehouse
    seeds the slot from the pool's `include_file` on every `get`, a reused slot too, and fails one whose file is missing
    before it touches any slot.
    """
    args = ["get", "--lease", "--lease-holder", holder, "--json"]
    if not fetch:
        args.append("--no-fetch")
    if base is not None:
        args += ["--base", base]
    if pool.root is not None:
        args += ["--worktree-path", WORKTREE_PATH]
    if pool.include_file is not None:
        # Absolute: treehouse reads a relative one from its working directory, the repository.
        args += ["--include-file", str(pool.include_file)]
    result = _run(runner, args, pool)
    if not result.ok:
        raise _fail(result)
    try:
        return Lease.model_validate_json(result.stdout)
    except ValidationError as e:
        returned = _return_unparsed(runner, result.stdout, pool)
        raise TreehouseError(f"treehouse get: unexpected output: {e}; {returned}") from e


def _return_unparsed(runner: procs.Runner, stdout: str, pool: Pool) -> str:
    """Return the slot a `get` with unparseable output leased, and say what happened for the error."""
    try:
        held = _Held.model_validate_json(stdout)
    except ValidationError:
        return "could not tell which slot was leased; the next tick's reconcile returns it"
    try:
        outcome = return_slot(runner, held.path, lease_id=held.lease_id, lease_holder=held.lease_holder, pool=pool)
    except TreehouseError as e:
        return f"returning {held.path} failed ({e}); the next tick's reconcile returns it"
    if outcome is ReturnOutcome.RETURNED:
        return f"returned {held.path}"
    return f"returning {held.path} said {outcome.value}; the next tick's reconcile returns it"


def return_slot(
    runner: procs.Runner, path: Path, *, lease_id: str, lease_holder: str, pool: Pool = DEFAULT_POOL
) -> ReturnOutcome:
    """Return a slot of `pool` only if it is still held under this exact lease.

    Always forced: the pushed branch is the checkpoint, and anything uncommitted in the slot is discarded.
    """
    args = ["return", "--force", "--if-lease-id", lease_id, "--if-lease-holder", lease_holder, str(path)]
    result = _run(runner, args, pool)
    if result.ok:
        return ReturnOutcome.RETURNED
    if result.returncode == 1:
        return ReturnOutcome.FAILED
    if result.returncode == 3:  # noqa: PLR2004
        return ReturnOutcome.DIRTY
    raise _fail(result)


def destroy(runner: procs.Runner, path: Path, *, pool: Pool = DEFAULT_POOL) -> str | None:
    """Remove slot `path` from its pool if treehouse finds it disposable: clean, merged, idle, and unleased.

    Never forced: none of `destroy`'s `--include-*` flags is passed, so treehouse keeps a slot with anything to lose.
    Returns None when the slot is gone, else what treehouse said about keeping it.
    """
    result = _run(runner, ["destroy", "--yes", str(path)], pool)
    if result.ok:
        return None
    return (result.stderr.strip() or result.stdout.strip() or f"exited {result.returncode}")[:500]
