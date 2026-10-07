"""Desks: the directory a joint run's worker works in, one link per worktree it leased (DESIGN §18).

A desk is `<workspace>/desks/<KEY>/`, holding a relative symlink named for each repository, pointing at that
repository's leased worktree. One worker per ticket, so one desk per ticket. `canopy _run` makes it before the worker
starts and removes it on every exit path it can see; reconcile removes the desk of a run that died without doing so.

canopy marks each desk it makes with a `MARKER` file and removes only what it marked: anything else under `desks/`,
a directory named for a ticket included, is the operator's and is left alone.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path

from canopy.core.workspace import DESKS_DIR

MARKER = ".canopy-desk"


class DeskError(Exception):
    """The desk cannot be made."""


def path(root: Path, key: str) -> Path:
    """Return the desk for ticket `key` in the workspace at `root`."""
    return root / DESKS_DIR / key


def is_desk(desk: Path) -> bool:
    """Return whether `desk` is a desk canopy made: a directory, not a link to one, holding canopy's marker."""
    return desk.is_dir() and not desk.is_symlink() and (desk / MARKER).is_file()


def make(root: Path, key: str, links: Sequence[tuple[str, Path]]) -> Path:
    """Make `key`'s desk with a link named for each repository to its worktree, replacing one left by a dead run.

    Raises:
        DeskError: `desks/` is a symlink, so the desk would land wherever it points; something canopy did not make is
            where the desk goes; or the desk cannot be written.
    """
    parent = root / DESKS_DIR
    # The workspace root may be a checkout: a committed `desks` link must not decide where canopy writes.
    if parent.is_symlink():
        raise DeskError(f"{parent} is a symlink; canopy makes desks only in a directory of its own. Remove it.")
    desk = path(root, key)
    if (desk.exists() or desk.is_symlink()) and not is_desk(desk):
        raise DeskError(f"{desk} is in the way of {key}'s desk and canopy did not make it. Move it.")
    try:
        parent.mkdir(mode=0o700, exist_ok=True)
        remove(desk)
        desk.mkdir(mode=0o700)
        (desk / MARKER).write_text(f"canopy's desk for {key}; removed when its run ends\n", encoding="utf-8")
        for name, target in links:
            (desk / name).symlink_to(os.path.relpath(target, desk), target_is_directory=True)
    except OSError as e:
        raise DeskError(f"could not make the desk {desk}: {e}") from e
    return desk


def remove(desk: Path) -> bool:
    """Remove a desk canopy made and anything the worker left in it, never following its links.

    Returns whether one was removed: anything else at `desk` is not canopy's and is left alone.
    """
    if not is_desk(desk):
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
