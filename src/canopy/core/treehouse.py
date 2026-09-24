"""The treehouse worktree pool, through its CLI (D002).

canopy uses three commands: `status --json`, `get --lease --json`, and `return --force --if-lease-id --if-lease-holder`.
Lease holders are `canopy:<KEY>`.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictStr, TypeAdapter, ValidationError

from canopy.infra import procs

HOLDER_PREFIX = "canopy:"
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


_SLOTS = TypeAdapter(list[Slot])


class ReturnOutcome(Enum):
    """What `treehouse return` said."""

    RETURNED = "returned"
    # Exit 1: the slot is unknown, not leased, or leased under a different identity. Retrying cannot help.
    FAILED = "failed"
    # Exit 3: dirty and not forced. canopy always forces, so this is an attention item, never a retry.
    DIRTY = "dirty"


def holder_for(key: str) -> str:
    """Return the lease holder canopy uses for ticket `key`."""
    return f"{HOLDER_PREFIX}{key}"


def _run(runner: procs.Runner, args: list[str]) -> procs.Result:
    try:
        result = runner.run(["treehouse", *args], timeout=_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        raise TreehouseError(str(e)) from e
    if result.timed_out:
        raise TreehouseError(f"treehouse {args[0]} timed out")
    return result


def _fail(result: procs.Result) -> TreehouseError:
    detail = result.stderr.strip() or result.stdout.strip()
    return TreehouseError(f"treehouse {result.args[1]} exited {result.returncode}: {detail}")


def status(runner: procs.Runner) -> list[Slot]:
    """Return every slot in the pool."""
    result = _run(runner, ["status", "--json"])
    if not result.ok:
        raise _fail(result)
    try:
        return _SLOTS.validate_json(result.stdout)
    except ValidationError as e:
        raise TreehouseError(f"treehouse status: unexpected output: {e}") from e


def lease(runner: procs.Runner, key: str, *, base: str | None = None) -> Lease:
    """Lease a slot for ticket `key`, optionally based on branch `base`."""
    args = ["get", "--lease", "--lease-holder", holder_for(key), "--json"]
    if base is not None:
        args += ["--base", base]
    result = _run(runner, args)
    if not result.ok:
        raise _fail(result)
    try:
        return Lease.model_validate_json(result.stdout)
    except ValidationError as e:
        raise TreehouseError(f"treehouse get: unexpected output: {e}") from e


def return_slot(runner: procs.Runner, path: Path, *, lease_id: str, lease_holder: str) -> ReturnOutcome:
    """Return a slot only if it is still held under this exact lease.

    Always forced: the pushed branch is the checkpoint, and anything uncommitted in the slot is discarded.
    """
    args = ["return", "--force", "--if-lease-id", lease_id, "--if-lease-holder", lease_holder, str(path)]
    result = _run(runner, args)
    if result.ok:
        return ReturnOutcome.RETURNED
    if result.returncode == 1:
        return ReturnOutcome.FAILED
    if result.returncode == 3:  # noqa: PLR2004
        return ReturnOutcome.DIRTY
    raise _fail(result)
