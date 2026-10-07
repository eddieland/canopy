"""The treehouse worktree pool, through its CLI (D002).

canopy uses three commands: `status --json`, `get --lease --json`, and `return --force --if-lease-id --if-lease-holder`.
Lease holders are `canopy:<KEY>`.

treehouse finds a repository's pool from its working directory. In a workspace, every command runs in the repository's
primary clone with `TREEHOUSE_ROOT` set to the workspace root, and `get` pins where a new slot goes, so the pools live
under `<workspace>/.treehouse/` whatever treehouse's own config says (DESIGN §18). A `Pool` says which.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictStr, TypeAdapter, ValidationError

from canopy.infra import procs

HOLDER_PREFIX = "canopy:"
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


# treehouse writes "" for an unleased slot's lease fields and null for its `leased_at`; accept either for both.
MaybeStr = Annotated[StrictStr, BeforeValidator(_null_is_empty)]


class _Output(BaseModel):
    # treehouse may add fields; canopy reads only the ones it needs.
    model_config = ConfigDict(extra="ignore", frozen=True)


class Slot(_Output):
    """One worktree in the pool, from `treehouse status --json`."""

    name: StrictStr
    path: Path
    status: StrictStr
    lease_id: MaybeStr = ""
    lease_holder: MaybeStr = ""
    leased_at: Annotated[StrictStr | None, BeforeValidator(_empty_is_null)] = None

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
    directory. `root` is the workspace root, passed as `TREEHOUSE_ROOT`; None leaves treehouse's own config in charge,
    as in a workspace of one.
    """

    cwd: Path | None = None
    root: Path | None = None


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
    """Lease a slot for ticket `key` from `pool`, optionally based on branch `base`.

    If treehouse leased a slot but its output is not a `Lease`, the slot is returned before the error is raised when
    the output still names it. When it does not, or the return fails, the next tick's reconcile returns it. The error
    says which happened.
    """
    args = ["get", "--lease", "--lease-holder", holder_for(key), "--json"]
    if base is not None:
        args += ["--base", base]
    if pool.root is not None:
        args += ["--worktree-path", WORKTREE_PATH]
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
