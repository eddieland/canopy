"""git as the harness runs it on the host, and the `.git` link of a slot (DESIGN §8, HOST_ISOLATION §5).

Every slot of a pool shares one git directory with the others and with the primary clone, and a worker can write to it.
git the harness runs there afterwards runs on the host, outside any worker: in `_run` after the worker, in the next run
or review on the pool, or in a sync. So every git the harness runs goes through `argv`, which turns off what git would
otherwise run from that directory unasked: hooks and the filesystem monitor. Submodule fetches and the `ext::` transport
are off too, as a URL from that directory's config could name either. A command the config names for a filter driver
or a transport (`remote.<name>.uploadpack`) still runs; only a git directory the worker cannot write closes that
(HOST_ISOLATION §4.2).

A worktree slot's `.git` is a file naming its git directory. A worker that rewrites it points host-side git at a
directory of its own, whose hooks and config the flags above do not cover, so `_run` reads it before the run and puts
it back if it changed. The `commondir` file in the slot's own git directory does the same for the common directory;
only the sandbox's policy keeps a worker from rewriting that one (HOST_ISOLATION §4.2).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
from pathlib import Path

# Flags before the subcommand: these override any repository, global, or system config.
SAFE_FLAGS = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "fetch.recurseSubmodules=false",
    "-c",
    "protocol.ext.allow=never",
)
# Never let git wait for credentials on a terminal nobody is watching.
ENV = {"GIT_TERMINAL_PROMPT": "0"}
LINK = ".git"


def argv(*args: str) -> list[str]:
    """Return the command line for `git <args>` with hooks, the filesystem monitor, and submodule fetches off."""
    return ["git", *SAFE_FLAGS, *args]


def read_link(worktree: Path) -> bytes | None:
    """Return what the `.git` file of `worktree` holds, or None if it is not a regular file.

    None for a clone, whose `.git` is a directory, for a symlink, which is never followed, and for one that cannot be
    read. Never raises.
    """
    try:
        fd = os.open(worktree / LINK, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        chunks: list[bytes] = []
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


def restore_link(worktree: Path, content: bytes) -> None:
    """Make the `.git` of `worktree` a file holding `content` again, removing whatever is there without following it.

    Raises:
        OSError: it could not be removed or written.
    """
    link = worktree / LINK
    if link.is_dir() and not link.is_symlink():
        shutil.rmtree(link)
    else:
        with contextlib.suppress(FileNotFoundError):
            link.unlink()
    fd = os.open(link, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
