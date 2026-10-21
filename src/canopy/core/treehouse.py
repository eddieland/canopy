"""The treehouse worktree pool, through its CLI (D002).

canopy uses `status --json`, `get --lease --json`, and `return --force --if-lease-id --if-lease-holder`, and
`canopy workspace sync` also uses `destroy --yes` to remove idle slots a pool has beyond its declared size.
`canopy workspace release` returns a quarantined slot with `return --force --if-lease-holder` alone. Lease
holders are `canopy:<KEY>`; sync's own short leases are `canopy-sync`, which reconcile never returns.

treehouse finds a repository's pool from its working directory. Every command runs in the repository's primary clone
with `TREEHOUSE_ROOT` set to the workspace root, and `get` pins where a new slot goes, so the pools live under
`<workspace>/.treehouse/` whatever treehouse's own config says (DESIGN §18). A `Pool` says which, and which personal
`.worktreeinclude` every `get` passes as `--include-file` (DESIGN §9).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, StrictStr, TypeAdapter, ValidationError

from canopy.core import pools
from canopy.core.pools import Lease, ReturnOutcome, Slot
from canopy.infra import procs

ROOT_ENV = "TREEHOUSE_ROOT"
# treehouse's own default layout, pinned: a repository's `treehouse.toml` cannot move a workspace's slots, and `return`
# finds a slot's pool two levels above it even when the repository's clone is gone.
WORKTREE_PATH = "{pool}/{slot}/{repo}"
_TIMEOUT_SECONDS = 120


class TreehouseError(pools.PoolError):
    """treehouse failed or said something canopy cannot parse."""


class _Held(BaseModel):
    """The fields of a `get` allocation needed to return it, for output that is not a full `Lease`."""

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    path: Path
    lease_id: StrictStr
    lease_holder: StrictStr


_SLOTS = TypeAdapter(list[Slot], config=ConfigDict(defer_build=True))


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


@dataclass(frozen=True)
class TreehousePool:
    """One repository's treehouse pool as a `pools.Pool`: the module's operations, run where `where` says."""

    runner: procs.Runner
    where: Pool = DEFAULT_POOL

    def status(self) -> list[Slot]:
        """Every slot in the pool, as `status` reads them.

        Returns:
            The slots, in treehouse's order.
        """
        return status(self.runner, pool=self.where)

    def lease(self, key: str, *, base: str | None = None) -> Lease:
        """Lease a slot for ticket `key` within the pool's declared size, as `lease` does.

        Returns:
            The leased slot.
        """
        return lease(self.runner, key, base=base, pool=self.where)

    def lease_as(self, holder: str, *, base: str | None = None, fetch: bool = True) -> Lease:
        """Lease any slot for `holder`, whatever the pool's declared size, as `lease_as` does.

        Returns:
            The leased slot.
        """
        return lease_as(self.runner, holder, base=base, pool=self.where, fetch=fetch)

    def return_slot(self, path: Path, *, lease_id: str, lease_holder: str) -> ReturnOutcome:
        """Return slot `path` only if it is still held under this exact lease, as `return_slot` does.

        Returns:
            What treehouse said.
        """
        return return_slot(self.runner, path, lease_id=lease_id, lease_holder=lease_holder, pool=self.where)

    def release(self, path: Path) -> ReturnOutcome:
        """Return slot `path` only if it is still quarantined, as `release` does.

        Returns:
            What treehouse said.
        """
        return release(self.runner, path, pool=self.where)

    def destroy(self, path: Path) -> str | None:
        """Remove slot `path` if treehouse finds it disposable, as `destroy` does.

        Returns:
            None when the slot is gone, else why treehouse kept it.
        """
        return destroy(self.runner, path, pool=self.where)


def status(runner: procs.Runner, *, pool: Pool = DEFAULT_POOL) -> list[Slot]:
    """Return every slot in the pool.

    Raises:
        TreehouseError: treehouse could not be run, timed out, failed, or printed something that is not a slot list.
    """
    result = _run(runner, ["status", "--json"], pool)
    if not result.ok:
        raise TreehouseError(_failure(result))
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

    Returns:
        The leased slot: its path, lease id and holder, when it was leased, and the branch it is based on.

    Raises:
        TreehouseError: The pool's declared slots are all busy, treehouse could not be run, timed out, failed, or
            printed something that is not a lease, or it made a slot past the pool's declared size.
    """
    if pool.slots is None:
        return lease_as(runner, pools.holder_for(key), base=base, pool=pool)
    before = status(runner, pool=pool)
    busy = sum(s.status != pools.AVAILABLE for s in before)
    if busy >= pool.slots:
        raise TreehouseError(f"{busy} of its slots are busy, and capacity declares {pool.slots} for this pool")
    leased = lease_as(runner, pools.holder_for(key), base=base, pool=pool)
    if len(before) < pool.slots or any(s.path == leased.path for s in before):
        return leased
    raise TreehouseError(
        f"no slot of the {len(before)} could be reused, and capacity declares {pool.slots} for this pool; "
        f"{_undo(runner, leased, pool)}",
    )


def lease_as(
    runner: procs.Runner,
    holder: str,
    *,
    base: str | None = None,
    pool: Pool = DEFAULT_POOL,
    fetch: bool = True,
) -> Lease:
    """Lease any slot of `pool` for `holder`, making one if none is available, whatever the pool's declared size.

    Without `fetch`, the slot is cut from the clone's existing refs; a later `get` that reuses it fetches. treehouse
    seeds the slot from the pool's `include_file` on every `get`, a reused slot too, and fails one whose file is missing
    before it touches any slot.

    Returns:
        The leased slot: its path, lease id and holder, when it was leased, and the branch it is based on.

    Raises:
        TreehouseError: treehouse could not be run, timed out, failed, or printed something that is not a lease.
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
        raise TreehouseError(_failure(result))
    try:
        return Lease.model_validate_json(result.stdout)
    except ValidationError as e:
        returned = _return_unparsed(runner, result.stdout, pool)
        raise TreehouseError(f"treehouse get: unexpected output: {e}; {returned}") from e


def return_slot(
    runner: procs.Runner,
    path: Path,
    *,
    lease_id: str,
    lease_holder: str,
    pool: Pool = DEFAULT_POOL,
) -> ReturnOutcome:
    """Return a slot of `pool` only if it is still held under this exact lease.

    Always forced: the pushed branch is the checkpoint, and anything uncommitted in the slot is discarded.

    Returns:
        `RETURNED`, or `FAILED` (exit 1) or `DIRTY` (exit 3) when treehouse kept the slot.

    Raises:
        TreehouseError: treehouse could not be run, timed out, or exited with any other code.
    """
    args = ["return", "--force", "--if-lease-id", lease_id, "--if-lease-holder", lease_holder, str(path)]
    return _returned(_run(runner, args, pool))


def release(runner: procs.Runner, path: Path, *, pool: Pool = DEFAULT_POOL) -> ReturnOutcome:
    """Return a slot of `pool` only if a failed seeding still holds it, under `pools.QUARANTINED`, forced.

    A quarantined slot has a holder but no lease id, so only the holder is a condition.

    Returns:
        `RETURNED`, or `FAILED` (exit 1) or `DIRTY` (exit 3) when treehouse kept the slot.

    Raises:
        TreehouseError: treehouse could not be run, timed out, or exited with any other code.
    """
    return _returned(_run(runner, ["return", "--force", "--if-lease-holder", pools.QUARANTINED, str(path)], pool))


def destroy(runner: procs.Runner, path: Path, *, pool: Pool = DEFAULT_POOL) -> str | None:
    """Remove slot `path` from its pool if treehouse finds it disposable: clean, merged, idle, and unleased.

    Never forced: none of `destroy`'s `--include-*` flags is passed, so treehouse keeps a slot with anything to lose.

    Returns:
        None when the slot is gone, else what treehouse said about keeping it, at most 500 characters.
    """
    result = _run(runner, ["destroy", "--yes", str(path)], pool)
    if result.ok:
        return None
    return (result.stderr.strip() or result.stdout.strip() or f"exited {result.returncode}")[:500]


def _run(runner: procs.Runner, args: Sequence[str], pool: Pool) -> procs.Result:
    env = {ROOT_ENV: str(pool.root)} if pool.root is not None else None
    try:
        result = runner.run(["treehouse", *args], cwd=pool.cwd, env=env, timeout=_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        raise TreehouseError(str(e)) from e
    if result.timed_out:
        raise TreehouseError(f"treehouse {args[0]} timed out")
    return result


def _returned(result: procs.Result) -> ReturnOutcome:
    """What a `return` came to, by its exit code.

    Returns:
        `RETURNED` on exit 0, `FAILED` on 1, `DIRTY` on 3.

    Raises:
        TreehouseError: treehouse exited with any other code.
    """
    if result.ok:
        return ReturnOutcome.RETURNED
    if result.returncode == 1:
        return ReturnOutcome.FAILED
    if result.returncode == 3:  # noqa: PLR2004
        return ReturnOutcome.DIRTY
    raise TreehouseError(_failure(result))


def _failure(result: procs.Result) -> str:
    detail = result.stderr.strip() or result.stdout.strip()
    return f"treehouse {result.args[1]} exited {result.returncode}: {detail}"


def _undo(runner: procs.Runner, leased: Lease, pool: Pool) -> str:
    """Return and destroy a slot `lease` made past the pool's size, and say how far that got, for the error."""
    outcome = return_slot(runner, leased.path, lease_id=leased.lease_id, lease_holder=leased.lease_holder, pool=pool)
    if outcome is not ReturnOutcome.RETURNED:
        return f"returning the new slot {leased.path} said {outcome.value}; the next tick's reconcile returns it"
    kept = destroy(runner, leased.path, pool=pool)
    if kept is not None:
        return f"treehouse kept the new slot {leased.path} ({kept}); `canopy workspace sync` removes it once it can"
    return f"the new slot {leased.path} was removed"


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
