"""The operator's desk (DESIGN §18): a ticket's branch checked out in a leased slot per repository, for their own edits.

`canopy desk KEY` leases a slot of each unit's pool as `operator:KEY`, a holder that is not canopy's, so reconcile's
stale-lease return and `canopy workspace release` both leave it; checks the ticket's branch out in each as a local
branch tracking origin's, so the operator commits and pushes as in any checkout (a run checks out detached, D109, for
reasons that do not hold for the operator: the next run's `_drop_local_branch` is refused while the desk has the branch
checked out); and makes `<workspace>/checkouts/KEY/`, one link per repository to its slot, beside a `.code-workspace`
file naming the slots, which an editor opens as one window. It lives beside `desks/`, not in it: a joint run's desk
for the same ticket is canopy's own, made and removed with the run, and the two must not collide.

`canopy desk KEY --close` returns the slots, when nothing in them would be lost unless told to discard it, and removes
the directory without following its links. The desk's marker file holds what close needs: the branch, and each
repository's slot.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError

from canopy.core import db, pools
from canopy.runs import checkpoint

if TYPE_CHECKING:
    from canopy.core.context import Context

#: Where the operator's desks live under the workspace: one directory per ticket.
DIR = "checkouts"
#: The file in a desk that marks it as one canopy made, holding what close needs.
MARKER = ".canopy-checkout"
#: The lease holder of a desk's slots, followed by the ticket's key. Not `canopy:`, so no tick returns it.
HOLDER_PREFIX = "operator:"
#: The workspace file an editor opens the desk from, named for the ticket.
WORKSPACE_SUFFIX = ".code-workspace"


class CheckoutError(Exception):
    """The desk cannot be opened or closed; what was leased for it has been returned."""


@dataclass(frozen=True)
class Desk:
    """A ticket's desk: its directory, the branch it has checked out, and each repository's slot."""

    key: str
    path: Path
    branch: str
    #: Each repository's slot, by the repository's name, which is also its link's.
    slots: Mapping[str, Path]

    @property
    def workspace_file(self) -> Path:
        """The editor's workspace file, which names every slot."""
        return self.path / f"{self.key}{WORKSPACE_SUFFIX}"


@dataclass(frozen=True)
class Unsafe:
    """What closing a desk would lose in one slot: uncommitted changes, or commits origin lacks."""

    repo: str
    changes: int
    commits: int
    #: Why git could not say, when it could not: the slot then counts as unsafe.
    error: str | None = None

    def __str__(self) -> str:
        """`repo` and what it holds, as the refusal names it.

        Returns:
            One clause, such as `api has 2 uncommitted changes and 1 commit origin lacks`.
        """
        if self.error is not None:
            return f"{self.repo} could not be read: {self.error}"
        parts = []
        if self.changes:
            parts.append(f"{self.changes} uncommitted change{'' if self.changes == 1 else 's'}")
        if self.commits:
            parts.append(f"{self.commits} commit{'' if self.commits == 1 else 's'} origin lacks")
        return f"{self.repo} has {' and '.join(parts)}"


def path(root: Path, key: str) -> Path:
    """Return the desk for ticket `key` in the workspace at `root`."""
    return root / DIR / key


def holder_for(key: str) -> str:
    """Return the lease holder of `key`'s desk's slots."""
    return f"{HOLDER_PREFIX}{key}"


def key_of(lease_holder: str) -> str | None:
    """Return the ticket whose desk holds a lease as `lease_holder`, or None when it is not a desk's."""
    if lease_holder.startswith(HOLDER_PREFIX):
        return lease_holder.removeprefix(HOLDER_PREFIX)
    return None


def find(root: Path, key: str) -> Desk | None:
    """Return `key`'s desk if it is open: a directory canopy marked, whose marker reads.

    Returns:
        The desk, or None when there is none, or what is there is not canopy's.
    """
    desk = path(root, key)
    if not desk.is_dir() or desk.is_symlink():
        return None
    try:
        held = _Marker.model_validate_json((desk / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None
    return Desk(key, desk, held.branch, {name: Path(slot) for name, slot in held.slots.items()})


def open_desk(ctx: Context, key: str, repos: Collection[str] = ()) -> Desk:
    """Open `key`'s desk: lease a slot per unit, or per unit in `repos`, at the ticket's branch, and link them.

    Returns:
        The desk, with every slot on the branch.

    Raises:
        CheckoutError: The ticket has no branch, in any unit or one of `repos`; `checkouts/` is a symlink, or
            something canopy did not make is where the desk goes; a pool refused a lease, or a slot could not be put
            on the branch. Every slot leased so far is returned first.
    """
    branch, units = _units(ctx, key, repos)
    parent = ctx.workspace.root / DIR
    # The workspace root may be a checkout: a committed `checkouts` link must not decide where canopy writes.
    if parent.is_symlink():
        raise CheckoutError(f"{parent} is a symlink; canopy makes desks only in a directory of its own. Remove it.")
    desk = path(ctx.workspace.root, key)
    if desk.exists() or desk.is_symlink():
        raise CheckoutError(f"{desk} is in the way of {key}'s desk and canopy did not make it. Move it.")
    leased: list[tuple[str, pools.Lease]] = []
    try:
        for name in units:
            lease = ctx.pool(name).lease_as(holder_for(key), base=branch)
            leased.append((name, lease))
            _check_out(ctx, name, lease.path, branch)
        slots = {name: lease.path for name, lease in leased}
        _write(desk, parent, key, branch, slots)
    except (pools.PoolError, checkpoint.SetupError, OSError) as e:
        _return_all(ctx, leased)
        _remove(desk)
        raise CheckoutError(f"could not open {key}'s desk: {e}") from e
    return Desk(key, desk, branch, slots)


def close_desk(ctx: Context, desk: Desk, *, discard: bool = False) -> list[Unsafe]:
    """Close `desk`: return its slots and remove its directory, unless a slot has work origin lacks.

    A slot whose lease is no longer the desk's, released by hand or leased since to a run, is dropped from the desk
    without a look at its work, which is not the desk's. Each slot returned is dropped too, as it goes, so a close
    that fails partway is finished by the next one.

    Returns:
        What each slot would lose, when any would and `discard` is not given: nothing is then returned or removed.

    Raises:
        CheckoutError: A pool could not return a slot. What could be returned was, and the desk is kept for the
            rest.
    """
    ours: dict[str, tuple[Path, pools.Slot]] = {}
    for name, slot in desk.slots.items():
        try:
            ours[name] = (slot, _lease_of(ctx, name, slot, desk.key))
        except CheckoutError:
            _forget(desk, name)
    if not discard:
        unsafe = [u for name, (slot, _) in ours.items() if (u := _unsafe(ctx, name, slot, desk.branch)) is not None]
        if unsafe:
            return unsafe
    kept: list[str] = []
    for name, (slot, lease) in ours.items():
        try:
            git = checkpoint.Git(ctx.runner, slot, name)
            # Off the branch, so it can be deleted: a return resets the slot detached, but only after this.
            git.run("checkout", "--quiet", "--detach", "--force")
            git.result("branch", "--quiet", "--delete", "--force", desk.branch)
            outcome = ctx.pool(name).return_slot(slot, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
        except (pools.PoolError, checkpoint.SetupError) as e:
            kept.append(f"{name}: {e}")
            continue
        if outcome is not pools.ReturnOutcome.RETURNED:
            kept.append(f"{name}: its pool {outcome.value} to return slot {slot}")
            continue
        _forget(desk, name)
    if kept:
        raise CheckoutError(f"{desk.key}'s desk is kept: " + "; ".join(kept))
    _remove(desk.path)
    return []


def _units(ctx: Context, key: str, repos: Collection[str]) -> tuple[str, list[str]]:
    """The ticket's branch, and the repositories the desk covers: every unit with the branch, or those in `repos`.

    Returns:
        The branch, and the repositories in the map's order.

    Raises:
        CheckoutError: No unit has a branch yet, or one of `repos` is not a unit with one.
    """
    with_branch = {str(u.repo): str(u.branch) for u in db.units(ctx.conn, key) if u.repo and u.branch}
    if not with_branch:
        raise CheckoutError(f"{key} has no branch in the journal yet: its first implement names one")
    missing = [name for name in repos if name not in with_branch]
    if missing:
        raise CheckoutError(f"{key} has no branch in {', '.join(missing)}; it has one in {', '.join(with_branch)}")
    chosen = [r.name for r in ctx.workspace.repos if r.name in with_branch and (not repos or r.name in repos)]
    # One branch per ticket (D058): every unit carries the same name.
    return with_branch[chosen[0]], chosen


def _check_out(ctx: Context, name: str, slot: Path, branch: str) -> None:
    """Put `slot` on `branch` as a local branch tracking origin's, which the lease fetched.

    Raises:
        checkpoint.SetupError: The branch is not on origin, or git failed.
    """
    git = checkpoint.Git(ctx.runner, slot, name)
    git.run("fetch", "--quiet", "--prune", "origin")
    tracking = f"refs/remotes/origin/{branch}"
    if not git.ok("rev-parse", "--verify", "--quiet", tracking):
        raise checkpoint.SetupError(f"{name}: the branch {branch} is not on origin")
    git.run("checkout", "--quiet", "-B", branch, "--track", tracking)


def _unsafe(ctx: Context, name: str, slot: Path, branch: str) -> Unsafe | None:
    """What closing would lose in `slot`: its uncommitted changes, and HEAD's commits `origin/<branch>` lacks.

    Returns:
        The count of each, or None when there is nothing to lose. A slot git cannot read counts as unsafe.
    """
    git = checkpoint.Git(ctx.runner, slot, name)
    status = git.result("status", "--porcelain", "--untracked-files=all")
    ahead = git.result("rev-list", "--count", f"refs/remotes/origin/{branch}..HEAD")
    for result in (status, ahead):
        if not result.ok:
            return Unsafe(name, 0, 0, error=(result.stderr.strip() or f"git exited {result.returncode}")[:200])
    changes = len(status.stdout.splitlines())
    commits = int(ahead.stdout.strip() or 0)
    return Unsafe(name, changes, commits) if changes or commits else None


def _lease_of(ctx: Context, name: str, slot: Path, key: str) -> pools.Slot:
    """The pool's slot at `slot`, which must still be leased to `key`'s desk.

    Returns:
        The slot, with its lease id and holder.

    Raises:
        CheckoutError: The pool has no such slot, or its lease is not the desk's.
    """
    found = next((s for s in ctx.pool(name).status() if s.path == slot), None)
    if found is None:
        raise CheckoutError(f"{name}'s pool has no slot {slot}")
    if found.lease_holder != holder_for(key):
        raise CheckoutError(f"slot {slot} is held by {found.lease_holder or 'nobody'}, not {key}'s desk")
    return found


def _return_all(ctx: Context, leased: Collection[tuple[str, pools.Lease]]) -> None:
    """Return every lease in `leased`, after a failure; one that cannot be is left to the operator's `--close`."""
    for name, lease in leased:
        _return_quietly(ctx, name, lease)


def _return_quietly(ctx: Context, name: str, lease: pools.Lease) -> None:
    try:
        ctx.pool(name).return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    except pools.PoolError:
        return


def _write(desk: Path, parent: Path, key: str, branch: str, slots: Mapping[str, Path]) -> None:
    """Make the desk: its marker, a link per slot, and the editor's workspace file."""
    parent.mkdir(mode=0o700, exist_ok=True)
    desk.mkdir(mode=0o700)
    marker = _Marker(branch=branch, slots={name: str(slot) for name, slot in slots.items()})
    (desk / MARKER).write_text(marker.model_dump_json() + "\n", encoding="utf-8")
    for name, slot in slots.items():
        (desk / name).symlink_to(os.path.relpath(slot, desk), target_is_directory=True)
    _write_workspace(desk / f"{key}{WORKSPACE_SUFFIX}", slots)


def _write_workspace(file: Path, slots: Mapping[str, Path]) -> None:
    """Write the editor's workspace file: a folder per slot, by the real path, which the editor's git reads best."""
    folders = [{"name": name, "path": str(slot)} for name, slot in slots.items()]
    file.write_text(json.dumps({"folders": folders}, indent=2) + "\n", encoding="utf-8")


def _forget(desk: Desk, name: str) -> None:
    """Drop repository `name`'s slot from the desk on disk: its link, and its line in the marker and workspace file."""
    left = {n: s for n, s in desk.slots.items() if n != name}
    link = desk.path / name
    if link.is_symlink():
        link.unlink()
    marker = _Marker(branch=desk.branch, slots={n: str(s) for n, s in left.items()})
    (desk.path / MARKER).write_text(marker.model_dump_json() + "\n", encoding="utf-8")
    _write_workspace(desk.workspace_file, left)


def _remove(desk: Path) -> None:
    """Remove the desk at `desk`, never following its links, if canopy made it."""
    if desk.is_dir() and not desk.is_symlink() and (desk / MARKER).is_file():
        # rmtree unlinks the slot links rather than descending into them, as `desks.remove` relies on.
        shutil.rmtree(desk)


class _Marker(BaseModel):
    """What the marker file holds: the branch, and each repository's slot."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    branch: StrictStr
    slots: dict[StrictStr, StrictStr]
