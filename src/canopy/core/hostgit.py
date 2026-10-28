"""git as the harness runs it on the host, and the `.git` link of a slot (DESIGN §8, §24).

Every slot of a pool shares one git directory with the others and with the primary clone, and a worker can write to it.
git the harness runs there afterwards runs on the host, outside any worker: in `_run` after the worker, in the next run
or review on the pool, or in a sync. So every git the harness runs goes through `argv`, which turns off what git would
otherwise run from that directory unasked: hooks and the filesystem monitor. Submodule fetches and the `ext::` transport
are off too, as a URL from that directory's config could name either. A command the config names for a filter driver
or a transport (`remote.<name>.uploadpack`) still runs; only a git directory the worker cannot write closes that
(DESIGN §24).

`argv` also turns off git's automatic maintenance, which a fetch or a commit otherwise starts in the background on that
shared directory while other slots' runs use it. The flags cover only the harness's own git; `canopy workspace sync`
sets the same in each primary clone's config, for the worker's git and treehouse's (`AUTO_MAINTENANCE_OFF`), and
`maintenance_left_on` says where a clone's config does not.

A worktree slot's `.git` is a file naming its git directory. A worker that rewrites it points host-side git at a
directory of its own, whose hooks and config the flags above do not cover, so `_run` reads it before the run and puts
it back if it changed. The `commondir` file in the slot's own git directory names the common directory, so a worker
that rewrites it does the same to every git in the slot; it is checked against where git put it, and put back.

`tracked` asks git which of a workspace's own paths it tracks, so that config can refuse a state directory that came
out of a checkout (DESIGN §12, TRUST_MODEL T7).
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Final

from canopy.infra import procs

# Flags before the subcommand: these override any repository, global, or system config.
SAFE_FLAGS: Final = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "fetch.recurseSubmodules=false",
    "-c",
    "protocol.ext.allow=never",
)
# git's automatic maintenance, as config keys and values: `maintenance.auto` for what a fetch or a commit starts, and
# `gc.auto` for `gc --auto`, which older git runs instead. Run in the background on a pool's shared git directory, it
# packs refs and prunes while other slots' runs use them; on CI it pruned a worktree `git worktree add` had not yet
# locked. Maintenance an operator runs on purpose is unaffected.
AUTO_MAINTENANCE_OFF: Final = (("maintenance.auto", "false"), ("gc.auto", "0"))
_MAINTENANCE_FLAGS: Final = tuple(arg for key, value in AUTO_MAINTENANCE_OFF for arg in ("-c", f"{key}={value}"))
# Never let git wait for credentials on a terminal nobody is watching.
ENV: Final = {"GIT_TERMINAL_PROMPT": "0"}
LINK: Final = ".git"
COMMONDIR: Final = "commondir"
# What `git worktree add` writes in `commondir`: the common directory is the one that holds `worktrees/<slot>/`.
COMMONDIR_CONTENT: Final = b"../..\n"
_LINK_PREFIX: Final = b"gitdir:"
_LS_FILES_TIMEOUT_SECONDS: Final = 30
_CONFIG_TIMEOUT_SECONDS: Final = 30


def argv(*args: str) -> list[str]:
    """Return the command line for `git <args>` with hooks, fsmonitor, submodule fetches, and maintenance off."""
    return ["git", *SAFE_FLAGS, *_MAINTENANCE_FLAGS, *args]


def tracked(runner: procs.Runner, root: Path, path: str) -> list[str] | None:
    """Return the files under `path`, relative to `root`, that the repository `root` is in tracks.

    `root` is in a repository when it or a directory above it holds `.git`; when none does, nothing is tracked and git
    does not run.

    Returns:
        The tracked files, relative to `root`, empty when there are none or `root` is in no repository; None when git
        could not say, such as a `.git` it does not read as a repository.
    """
    if git_root(root) is None:
        return []
    try:
        result = runner.run(argv("ls-files", "-z", "--", path), cwd=root, env=ENV, timeout=_LS_FILES_TIMEOUT_SECONDS)
    except procs.ProcError:
        return None
    if not result.ok:
        return None
    return [name for name in result.stdout.split("\0") if name]


def maintenance_left_on(runner: procs.Runner, clone: Path) -> list[str] | None:
    """Return the keys of `AUTO_MAINTENANCE_OFF` that `clone`'s own config does not set as sync sets them.

    Only the clone's own config counts, since the worker's git and treehouse's read it whatever HOME they run with.

    Returns:
        The keys, empty when every one is set; None when git could not read the config.
    """
    pattern = "^(" + "|".join(re.escape(key) for key, _ in AUTO_MAINTENANCE_OFF) + ")$"
    try:
        # Read as booleans, both keys say `false` when off: `maintenance.auto` false, and `gc.auto` 0.
        result = runner.run(
            argv("config", "--local", "--type=bool", "--get-regexp", pattern),
            cwd=clone,
            env=ENV,
            timeout=_CONFIG_TIMEOUT_SECONDS,
        )
    except procs.ProcError:
        return None
    # 1 is git's answer when neither key is set.
    if result.timed_out or result.returncode not in {0, 1}:
        return None
    found = dict(line.split(" ", 1) for line in result.stdout.splitlines() if " " in line)
    return [key for key, _ in AUTO_MAINTENANCE_OFF if found.get(key) != "false"]


def git_root(start: Path) -> Path | None:
    """The nearest directory at or above `start` holding `.git`, a directory or a worktree's file, or None.

    Returns:
        The checkout's root, resolved, or None if `start` is in no checkout.
    """
    start = start.resolve()
    return next((d for d in (start, *start.parents) if (d / LINK).exists()), None)


def read_link(worktree: Path) -> bytes | None:
    """Return what the `.git` file of `worktree` holds, or None if it is not a regular file.

    None for a clone, whose `.git` is a directory, for a symlink, which is never followed, and for one that cannot be
    read. Never raises.
    """
    return _read_file(worktree / LINK)


def restore_link(worktree: Path, content: bytes) -> None:
    """Make the `.git` of `worktree` a file holding `content` again, removing whatever is there without following it.

    Raises:
        OSError: it could not be removed or written.
    """
    _replace(worktree / LINK, content)


def commondir_moved(worktree: Path, link: bytes) -> bool:
    """Whether the `commondir` of `worktree` names a directory other than the one git put it in.

    `link` is what the worktree's `.git` file held when the run started, which says where its own git directory is. The
    common directory is the one that holds that directory, so `commondir` must resolve there, as git's `../..` does.

    Returns:
        True if it names anywhere else, or is missing or not a regular file; always False when `link` names no git
        directory, as for a clone.
    """
    own = own_git_dir(worktree, link)
    if own is None:
        return False
    content = _read_file(own / COMMONDIR)
    if content is None:
        return True
    named = own / os.fsdecode(content.rstrip(b"\n"))
    return named.resolve() != own.parent.parent.resolve()


def restore_commondir(worktree: Path, link: bytes) -> None:
    """Make the `commondir` of `worktree`, found from `link`, hold what git writes there again.

    Raises:
        FileNotFoundError: `link` names no git directory.
        OSError: the file could not be removed or written.
    """
    own = own_git_dir(worktree, link)
    if own is None:
        raise FileNotFoundError(f"{worktree / LINK} names no git directory")
    _replace(own / COMMONDIR, COMMONDIR_CONTENT)


def own_git_dir(worktree: Path, link: bytes) -> Path | None:
    """Return the git directory a worktree's `.git` file holding `link` names, relative to `worktree` if it is.

    Returns:
        The directory, or None when `link` does not name one.
    """
    if not link.startswith(_LINK_PREFIX):
        return None
    named = link.removeprefix(_LINK_PREFIX).strip()
    return worktree / os.fsdecode(named) if named else None


def _read_file(path: Path) -> bytes | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
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


def _replace(path: Path, content: bytes) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
