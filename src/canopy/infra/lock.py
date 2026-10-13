"""Exclusive `flock` locks: the tick lock on `<state_dir>/lock`, and the dispatch lock.

The lock is released when the holding process exits, however it exits, so a crashed tick never leaves it held.
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
