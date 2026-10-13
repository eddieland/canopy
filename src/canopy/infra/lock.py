"""Exclusive `flock` locks: the tick lock on `<state_dir>/lock`, the dispatch lock, and each detached run's lifelock.

A lock is released when the holding process exits, however it exits, so a crashed tick never leaves it held, and a
detached run is alive exactly while its lifelock is held (`procs.running`).
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

LOCK_FILE_NAME = "lock"


class LockBusyError(Exception):
    """Another process holds the lock."""


@contextmanager
def hold(path: Path, *, wait: bool = False) -> Generator[None]:
    """Hold the lock at `path` for the duration of the block.

    If another process holds it, raise LockBusyError at once, or with `wait` block until it is free.

    Raises:
        LockBusyError: Another process holds the lock and `wait` is not set.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Python opens files non-inheritable, so the agents a tick runs do not hold the lock after the tick exits.
    with path.open("a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise LockBusyError(f"{path} is held by another process") from e
        try:
            # The pid is for a human reading the file; the flock is what counts.
            f.seek(0)
            f.truncate()
            f.write(f"{os.getpid()}\n")
            f.flush()
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def take(path: Path) -> int:
    """Take the lock at `path` without waiting and return the open fd that holds it.

    The lock is released once every copy of the fd is closed, in this process or any child it was passed to, however
    that process exits. `procs.SubprocessRunner.spawn` passes one to the child it starts, so the child holds the lock
    for its whole life.

    Returns:
        The fd, open on `path` and not inheritable.

    Raises:
        LockBusyError: Another process holds it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as e:
        os.close(fd)
        raise LockBusyError(f"{path} is held by another process") from e
    except BaseException:
        os.close(fd)
        raise
    return fd


def held(path: Path) -> bool:
    """Return whether some process holds the lock at `path`. A lock with no file is held by nobody."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    # Closing the fd releases the lock, if this took it.
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False
