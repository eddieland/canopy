"""Desks: the directory a joint run's worker works in, one link per worktree it leased (DESIGN §18).

A desk is `<workspace>/desks/<KEY>/`, holding a relative symlink named for each repository, pointing at that
repository's leased worktree. One worker per ticket, so one desk per ticket. `canopy _run` makes it before the worker
starts and removes it on every exit path it can see; reconcile removes the desk of a run that died without doing so.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path

from canopy.core.workspace import DESKS_DIR


class DeskError(Exception):
    """The desk cannot be made."""


def path(root: Path, key: str) -> Path:
    """Return the desk for ticket `key` in the workspace at `root`."""
    return root / DESKS_DIR / key


def make(root: Path, key: str, links: Sequence[tuple[str, Path]]) -> Path:
    """Make `key`'s desk with a link named for each repository to its worktree, replacing one left by a dead run.

    Raises:
        DeskError: `desks/` is a symlink, so the desk would land wherever it points, or the desk cannot be written.
    """
    parent = root / DESKS_DIR
    # The workspace root may be a checkout: a committed `desks` link must not decide where canopy writes.
    if parent.is_symlink():
        raise DeskError(f"{parent} is a symlink; canopy makes desks only in a directory of its own. Remove it.")
    desk = path(root, key)
    try:
        parent.mkdir(mode=0o700, exist_ok=True)
        remove(desk)
        desk.mkdir(mode=0o700)
        for name, target in links:
            (desk / name).symlink_to(os.path.relpath(target, desk), target_is_directory=True)
    except OSError as e:
        raise DeskError(f"could not make the desk {desk}: {e}") from e
    return desk


def remove(desk: Path) -> bool:
    """Remove a desk and anything the worker left in it, never following its links. Returns whether one was there."""
    if desk.is_symlink():
        desk.unlink()
        return True
    if not desk.exists():
        return False
    # rmtree unlinks the worktree links rather than descending into them.
    shutil.rmtree(desk)
    return True


def prune(root: Path, keep: Iterable[str]) -> list[Path]:
    """Remove every desk except those of the tickets in `keep`, which have a running run. Returns the desks removed."""
    parent = root / DESKS_DIR
    if parent.is_symlink() or not parent.is_dir():
        return []
    kept = set(keep)
    return [desk for desk in sorted(parent.iterdir()) if desk.name not in kept and remove(desk)]
