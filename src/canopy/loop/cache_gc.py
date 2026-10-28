"""`canopy gc --caches`: each role's sandbox cache emptied while no run of that role is live (DESIGN §24, §26).

The wrapper gives every sandboxed run its role's cache directory, `$XDG_CACHE_HOME/canopy/sandbox/<cache>/`, setup
sharing the worker's, and nothing else ever empties one. This removes what is in each, leaving the directory, which
the wrapper keeps as it made it. A cache goes only while no run that could be using it is live, under the dispatch
lock, which every run's start takes, so none starts while its cache is emptied; a dispatch waits for it. The overseer's
goes only while no tick runs, under the tick lock, which a tick holds for its whole life; a tick that starts meanwhile
is skipped as busy. A cache canopy cannot match to its runs, or whose runs it cannot read, is left as it is. Nothing is
followed through a link, so nothing outside a cache directory is removed, the operator's own caches included. The loop
never runs it on its own.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import canopy_sandbox

from canopy.core import db
from canopy.infra import lock, logs, procs
from canopy.loop import gc

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping

    from canopy.core.context import Context
    from canopy.core.db import RunTable

#: What emptying came to in one cache directory.
Outcome = Literal["emptied", "skipped", "failed"]

#: The run tables whose runs start in the wrapper as each role (DESIGN §24): a worker or plan run's agent as `worker`
#: and its `setup_cmd` as `setup`, a task's agent as `worker`, a chore's as `chore`, and a review's as `review`. The
#: overseer's runs are ticks, in no run table: `TICK_ROLES` says how its cache is held.
ROLE_TABLES: Mapping[str, tuple[RunTable, ...]] = {
    "worker": ("runs", "task_runs"),
    "setup": ("runs",),
    "chore": ("chore_runs",),
    "review": ("review_runs",),
    "overseer": (),
}
#: The roles that run only inside a tick, whose cache goes only while canopy holds the tick lock.
TICK_ROLES = frozenset({"overseer"})


@dataclass(frozen=True)
class Emptied:
    """What `--caches` did in one directory of the sandbox's cache root."""

    #: The directory's name: the cache of the roles the wrapper points at it.
    cache: str
    outcome: Outcome
    #: Why it was skipped, or why it failed; empty when it was emptied.
    detail: str = ""
    #: The bytes of the regular files it removed.
    freed: int = 0


def empty(ctx: Context) -> list[Emptied]:
    """Empty each role's cache directory while no run of its roles is live, skipping one canopy cannot tell about.

    Returns:
        What it came to in each entry of the cache root, by name; none when there is no cache root.
    """
    log = logs.for_tick(None)
    root = canopy_sandbox.cache_root()
    done: list[Emptied] = []
    for entry in _entries(root):
        with lock.hold(ctx.dispatch_lock_path, wait=True):
            result = _between_ticks(ctx, entry) if _in_ticks(entry.name) else _empty_one(ctx.conn, entry)
        log.info(
            "sandbox cache",
            extra={"cache": result.cache, "outcome": result.outcome, "detail": result.detail, "freed": result.freed},
        )
        done.append(result)
    return done


def tables_of(cache: str) -> tuple[RunTable, ...] | None:
    """The run tables whose runs may use the cache directory named `cache`, by the roles the wrapper points at it.

    Returns:
        The tables, or None when no role the wrapper knows uses it, or one does whose runs canopy does not know.
    """
    roles = [role for role, name in canopy_sandbox.CACHES.items() if name == cache]
    if not roles or any(role not in ROLE_TABLES for role in roles):
        return None
    return tuple(dict.fromkeys(table for role in roles for table in ROLE_TABLES[role]))


def _in_ticks(cache: str) -> bool:
    """Whether a role that runs inside a tick caches in the directory named `cache`.

    Returns:
        True for the overseer's.
    """
    return any(role in TICK_ROLES for role, name in canopy_sandbox.CACHES.items() if name == cache)


def _between_ticks(ctx: Context, directory: Path) -> Emptied:
    """Empty `directory`, the overseer's cache, under the tick lock, or skip it while a tick holds that.

    Returns:
        What `_empty_one` did, or `skipped` while a tick runs.
    """
    try:
        with lock.hold(ctx.lock_path):
            return _empty_one(ctx.conn, directory)
    except lock.LockBusyError:
        busy = "a tick is running, whose overseer may be using it; run it again later"
        return Emptied(directory.name, "skipped", busy)


def _entries(root: Path) -> list[Path]:
    """The entries of the cache root, by name.

    Returns:
        Each, or none when the root is missing or cannot be read.
    """
    try:
        return sorted(root.iterdir())
    except OSError:
        return []


def _empty_one(conn: sqlite3.Connection, directory: Path) -> Emptied:
    """Empty `directory`, an entry of the cache root, if it is a role's cache no live run uses, under the caller's lock.

    Returns:
        `emptied` with the bytes it freed, `skipped` with why, or `failed` with what could not be removed.
    """
    name = directory.name
    skip = _skip(conn, directory)
    if skip is not None:
        return Emptied(name, "skipped", skip)
    freed = 0
    try:
        with os.scandir(directory) as found:
            for entry in sorted(found, key=lambda e: e.name):
                freed += _remove(Path(entry.path))
    except OSError as e:
        return Emptied(name, "failed", str(e), freed)
    return Emptied(name, "emptied", freed=freed)


def _skip(conn: sqlite3.Connection, directory: Path) -> str | None:
    """Why `directory`, an entry of the cache root, is not to be emptied now.

    Returns:
        The reason, or None when it is a directory of the operator's, a role's cache, and no run of its roles is live.
    """
    try:
        info = directory.lstat()
    except OSError as e:
        return f"it could not be read: {e}"
    if stat.S_ISLNK(info.st_mode):
        return "it is a link, which canopy does not follow"
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        return "it is not a directory of yours"
    tables = tables_of(directory.name)
    if tables is None:
        return "no role canopy knows caches here, so it cannot tell whether a run uses it"
    return _in_use(conn, tables)


def _in_use(conn: sqlite3.Connection, tables: Collection[RunTable]) -> str | None:
    """Why a cache the runs in `tables` may use is not to be emptied now: one of them is live, or none can be read.

    Returns:
        The reason, or None when no run in `tables` is live.
    """
    try:
        live = _live(conn, tables)
    except (sqlite3.Error, OSError) as e:
        return f"canopy could not tell whether a run using it is live: {e}"
    if not live:
        return None
    runs = f"{live[0]} is" if len(live) == 1 else f"{', '.join(live)} are"
    return f"{runs} live and may be using it; run it again once none is"


def _live(conn: sqlite3.Connection, tables: Collection[RunTable]) -> list[str]:
    """Each running run in `tables` that may be at work: its own process or its agent alive, or either unknown.

    A run whose own process is gone may have left its agent at work until reconcile kills it (DESIGN §6), and one that
    names no process yet cannot be told about, so both count.

    Returns:
        Each as a message names it, `run 3` or `review run 4`, by table, then by when it started.
    """
    live: list[str] = []
    for table in tables:
        for row in db.running_runs(conn, table):
            pid, agent = row["pid"], row[db.AGENT_PID[table]]
            if pid is None or procs.running(Path(row["log_path"]), pid) or (agent is not None and procs.alive(agent)):
                live.append(f"{db.RUN_NOUNS[table]} {row['id']}")
    return live


def _remove(path: Path) -> int:
    """Remove `path`, an entry of a cache directory, following no link: a link goes, never what it points at.

    Returns:
        The bytes of the regular files it removed.
    """
    info = path.lstat()
    if stat.S_ISDIR(info.st_mode):
        size = gc.tree_size(path)
        shutil.rmtree(path, onexc=_unlocked)
        return size
    path.unlink()
    return info.st_size if stat.S_ISREG(info.st_mode) else 0


def _unlocked(function: Callable[..., object], path: str, error: BaseException) -> None:
    """Make the directory that holds `path` writable and remove `path` again, when a tool made it read-only.

    Go's module cache makes its directories read-only, so `rmtree` alone cannot empty them.

    Raises:
        BaseException: `error`, for any other failure, or when what holds `path` is not a directory.
    """
    if not isinstance(error, PermissionError) or function not in {os.unlink, os.rmdir}:
        raise error
    parent = Path(path).parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise error
    parent.chmod(stat.S_IMODE(info.st_mode) | stat.S_IRWXU)
    function(path)
