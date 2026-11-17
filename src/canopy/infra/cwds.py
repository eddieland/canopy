"""The processes whose working directory is inside a directory: what keeps a pool's slot in use (DESIGN §18).

On Linux, each process's `/proc/<pid>/cwd` link; elsewhere (macOS), `lsof -d cwd`, run through `procs`, so there is no
dependency for it. A process this one cannot inspect, another user's, is not found. The caller and its ancestors are
never counted: a command run from inside a slot does not make the slot busy by looking at it.
"""

from __future__ import annotations

import contextlib
import os
import signal
import time
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from canopy.infra import procs

PROC: Final = Path("/proc")
# How long `end` waits for the processes it signalled, after SIGTERM and again after SIGKILL, as treehouse does.
GRACE_SECONDS: Final = 2.0
_POLL_SECONDS: Final = 0.05
_LSOF_TIMEOUT_SECONDS: Final = 30


class CwdError(Exception):
    """The process table could not be read."""


@dataclass(frozen=True)
class Found:
    """A process working in the directory: its pid and its command's name."""

    pid: int
    name: str


@dataclass(frozen=True)
class Table:
    """Every process this one can inspect, each with its working directory: one read of the process table."""

    entries: tuple[tuple[Found, Path], ...]

    def inside(self, directory: Path) -> list[Found]:
        """Return the processes whose working directory is `directory` or below it, by pid.

        Returns:
            Them, this process and its ancestors left out.
        """
        root = Path(os.path.realpath(directory))
        mine = _ancestors()
        found = (f for f, cwd in self.entries if f.pid not in mine and _within(cwd, root))
        return sorted(found, key=lambda f: f.pid)


def table(runner: procs.Runner) -> Table:
    """Read the process table once, for a caller that asks about several directories.

    Returns:
        Every process found, with its working directory.

    Raises:
        CwdError: the process table could not be read.
    """
    entries = _from_proc() if (PROC / "self" / "cwd").exists() else _from_lsof(runner)
    return Table(tuple(entries))


def inside(runner: procs.Runner, directory: Path) -> list[Found]:
    """Return the processes whose working directory is `directory` or below it, by pid.

    Returns:
        Them, this process and its ancestors left out.

    Raises:
        CwdError: the process table could not be read.
    """
    return table(runner).inside(directory)


def end(runner: procs.Runner, directory: Path) -> list[Found]:
    """Stop the processes working in `directory`: SIGTERM, then SIGKILL for any still alive after the grace period.

    Returns:
        The processes still working there afterwards; empty when every one has ended.

    Raises:
        CwdError: the process table could not be read.
    """
    found = inside(runner, directory)
    if not found:
        return []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for f in found:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(f.pid, sig)
        if _wait_gone([f.pid for f in found]):
            break
    return inside(runner, directory)


def _from_proc() -> list[tuple[Found, Path]]:
    found: list[tuple[Found, Path]] = []
    try:
        entries = [e for e in PROC.iterdir() if e.name.isdigit()]
    except OSError as e:
        raise CwdError(f"cannot read {PROC}: {e}") from e
    for entry in entries:
        try:
            cwd = (entry / "cwd").readlink()
            name = (entry / "comm").read_text().strip()
        except OSError:
            continue  # gone, or another user's
        found.append((Found(int(entry.name), name), cwd))
    return found


def _from_lsof(runner: procs.Runner) -> list[tuple[Found, Path]]:
    try:
        result = runner.run(["lsof", "-n", "-w", "-d", "cwd", "-F", "pcn"], timeout=_LSOF_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        raise CwdError(f"lsof: {e}") from e
    if result.timed_out or not result.stdout:
        raise CwdError(f"lsof {'timed out' if result.timed_out else f'exited {result.returncode}'}")
    found: list[tuple[Found, Path]] = []
    pid, name = 0, ""
    for line in result.stdout.splitlines():
        tag, value = line[:1], line[1:]
        if tag == "p":
            pid, name = int(value), ""
        elif tag == "c":
            name = value
        elif tag == "n" and pid:
            found.append((Found(pid, name), Path(value)))
    return found


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _ancestors() -> set[int]:
    """This process and its ancestors, as far as they can be read.

    Returns:
        Their pids.
    """
    pids = {os.getpid(), os.getppid()}
    pid = os.getppid()
    while pid > 1:
        try:
            stat = (PROC / str(pid) / "stat").read_text()
        except OSError:
            break
        # The command name is in parentheses and may hold spaces; the parent's pid is the second field after it.
        pid = int(stat.rpartition(")")[2].split()[1])
        pids.add(pid)
    return pids


def _wait_gone(pids: Collection[int]) -> bool:
    """Wait up to the grace period for every one of `pids` to end.

    Returns:
        Whether they all did.
    """
    deadline = time.monotonic() + GRACE_SECONDS
    while True:
        if not any(procs.alive(p) for p in pids):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_SECONDS)
