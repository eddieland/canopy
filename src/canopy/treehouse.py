"""The treehouse worktree pool, through its CLI (D002).

canopy uses three commands: `status --json`, `get --lease --json`, and `return --force --if-lease-id --if-lease-holder`.
Lease holders are `canopy:<KEY>`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from canopy import procs

HOLDER_PREFIX = "canopy:"
_TIMEOUT_SECONDS = 120


class TreehouseError(Exception):
    """treehouse failed or said something canopy cannot parse."""


@dataclass(frozen=True)
class Slot:
    """One worktree in the pool, from `treehouse status --json`."""

    name: str
    path: Path
    status: str
    lease_id: str
    lease_holder: str
    leased_at: str | None

    @property
    def canopy_key(self) -> str | None:
        """The ticket key if canopy holds this slot's lease, else None."""
        if self.lease_holder.startswith(HOLDER_PREFIX):
            return self.lease_holder.removeprefix(HOLDER_PREFIX)
        return None


@dataclass(frozen=True)
class Lease:
    """A slot leased with `treehouse get --lease --json`."""

    path: Path
    lease_id: str
    lease_holder: str
    leased_at: str
    base_branch: str


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


def _obj(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TreehouseError(f"treehouse {what}: expected a JSON object")
    return {str(k): v for k, v in value.items()}


def _str(d: dict[str, object], key: str, what: str, *, nullable: bool = False) -> str:
    value = d.get(key)
    if value is None and nullable:
        return ""
    if not isinstance(value, str):
        raise TreehouseError(f"treehouse {what}: field {key!r} is missing or not a string")
    return value


def status(runner: procs.Runner) -> list[Slot]:
    """Return every slot in the pool."""
    result = _run(runner, ["status", "--json"])
    if not result.ok:
        raise _fail(result)
    try:
        doc: object = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise TreehouseError(f"treehouse status: invalid JSON: {e}") from e
    if not isinstance(doc, list):
        raise TreehouseError("treehouse status: expected a JSON array")
    slots: list[Slot] = []
    for raw in doc:
        d = _obj(raw, "status")
        leased_at = _str(d, "leased_at", "status", nullable=True)
        slots.append(
            Slot(
                name=_str(d, "name", "status"),
                path=Path(_str(d, "path", "status")),
                status=_str(d, "status", "status"),
                lease_id=_str(d, "lease_id", "status", nullable=True),
                lease_holder=_str(d, "lease_holder", "status", nullable=True),
                leased_at=leased_at or None,
            )
        )
    return slots


def lease(runner: procs.Runner, key: str, *, base: str | None = None) -> Lease:
    """Lease a slot for ticket `key`, optionally based on branch `base`."""
    args = ["get", "--lease", "--lease-holder", holder_for(key), "--json"]
    if base is not None:
        args += ["--base", base]
    result = _run(runner, args)
    if not result.ok:
        raise _fail(result)
    try:
        d = _obj(json.loads(result.stdout), "get")
    except json.JSONDecodeError as e:
        raise TreehouseError(f"treehouse get: invalid JSON: {e}") from e
    return Lease(
        path=Path(_str(d, "path", "get")),
        lease_id=_str(d, "lease_id", "get"),
        lease_holder=_str(d, "lease_holder", "get"),
        leased_at=_str(d, "leased_at", "get"),
        base_branch=_str(d, "base_branch", "get"),
    )


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
