"""Give a sandboxed run's Bazel the operator's downloads, and take back only the ones it adds (DESIGN §24).

Bazel's repository cache holds what it downloads, such as a wheel or a toolchain archive, as
`content_addressable/<algorithm>/<checksum>/file`, and checks each file against its checksum before it uses it (checked
against Bazel 9.3.0). A run may not write the operator's own: Bazel checks a file, then copies it in a separate step,
so a run that could rename a file of its own over one in between would hand the operator's builds what it chose.

So a run's Bazel uses a repository cache of its role's own, in the role's cache directory, made of a link to each entry
in the operator's, which the policy lets the run read and not write, and of the entries its own downloads add. `share`
links in the operator's new entries before each run. `collect`, after each run and before the next, copies each entry
a run added into the operator's cache, but only from a copy the run cannot reach, and only when that copy has the
checksum the entry is named by, then links the role's entry to it. Only SHA-256, SHA-384, and SHA-512 entries are
taken: SHA-1 has known collisions, and Python has no BLAKE3.

Bazel takes no variable for its caches, so the run's `bazel`, first on its PATH, runs the real one with
`--bazelrc` naming a file of the run's, read after the repository's own: the role's repository cache, a disk cache,
and an output root of the role's own. The operator's disk cache and output root are not shared: Bazel takes an action's
outputs from one without checking them, and runs its own binaries from the other.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import re
import secrets
import shlex
import shutil
import stat
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

# Where Bazel keeps its downloads in a repository cache, and the name of each entry's file.
CAS = "content_addressable"
FILE = "file"
# The algorithms an entry may be named by, each with the length of its name in hex. Only the ones that can be
# checked, and are not broken, are taken back.
ALGORITHMS = {"sha1": 40, "sha256": 64, "sha384": 96, "sha512": 128, "blake3": 64}
CHECKED = ("sha256", "sha384", "sha512")
# A marker Bazel leaves beside an entry's file for each canonical id it was fetched under.
MARKER = re.compile(r"id-[0-9a-f]{40,128}")
# Under the role's cache directory: the run's Bazel's repository cache, disk cache, and output root.
ROOT = "bazel"
REPOSITORY_CACHE = "repository-cache"
DISK_CACHE = "disk-cache"
OUTPUT_ROOT = "output"
# Held while `share` and `collect` change a role's repository cache or the operator's, in the directory that holds
# every role's cache directory, which no run can write.
LOCK = "bazel.lock"
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
BAZEL_SHIM = """#!/bin/sh
# canopy-sandbox's bazel, first on PATH (DESIGN §24). Its rc file, read after the repository's own, gives Bazel the
# role's repository cache, disk cache, and output root.
exec @REAL@ --bazelrc=@RC@ "$@"
"""


@contextlib.contextmanager
def locked(root: Path) -> Iterator[None]:
    """Hold the lock every run's `share` and `collect` take, in `root`, the directory of every role's cache directory.

    Yields:
        Nothing, while the lock is held.
    """
    fd = os.open(root / LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def share(cache: Path, operator: Path) -> None:
    """Link each entry of the operator's repository cache, at `operator`, into the role's, under `cache`.

    A link whose entry the operator no longer has is removed. An entry of the run's own is left for `collect`.
    """
    with _cas(cache) as cas:
        for algorithm, length in ALGORITHMS.items():
            theirs = operator / CAS / algorithm
            names = {n for n in _names(theirs) if _is_key(n, length)}
            mine = _made_dir(cas, algorithm)
            try:
                for name in _list(mine):
                    if _is_link(mine, name) and name not in names:
                        os.unlink(name, dir_fd=mine)
                for name in names:
                    with contextlib.suppress(FileExistsError):
                        os.symlink(theirs / name, name, dir_fd=mine)
            finally:
                os.close(mine)


def collect(cache: Path, operator: Path) -> list[str]:
    """Copy into the operator's repository cache, at `operator`, each entry a run added to the role's, under `cache`.

    Each is copied to a file of the operator's first, which no run can reach, and taken only when that copy has the
    checksum its entry is named by. The role's entry is then linked to the operator's, as it is to one the operator
    has fetched as well.

    Returns:
        Each entry copied, as `sha256/<checksum>`.
    """
    taken: list[str] = []
    with _cas(cache) as cas:
        for algorithm in CHECKED:
            mine = _open_dir(cas, algorithm)
            if mine is None:
                continue
            try:
                theirs = operator / CAS / algorithm
                for name in _list(mine):
                    if not _is_key(name, ALGORITHMS[algorithm]) or _is_link(mine, name):
                        continue
                    if (theirs / name / FILE).is_file():  # the operator fetched it too, meanwhile
                        _link(mine, name, theirs / name)
                    elif _take(mine, name, algorithm, theirs):
                        _link(mine, name, theirs / name)
                        taken.append(f"{algorithm}/{name}")
            finally:
                os.close(mine)
    return taken


def rc_file(cache: Path) -> str:
    """Return the rc file the run's Bazel reads last, for the role's cache directory `cache`.

    Returns:
        Its text.
    """
    root = cache / ROOT
    return (
        f"startup --output_user_root={root / OUTPUT_ROOT}\n"
        f"common --repository_cache={root / REPOSITORY_CACHE}\n"
        f"common --disk_cache={root / DISK_CACHE}\n"
    )


def shim(bin_dir: Path, real: Path, rc: Path) -> None:
    """Write the run's `bazel` into `bin_dir`: the real one at `real`, reading `rc` after the repository's rc file."""
    values = {"@REAL@": shlex.quote(str(real)), "@RC@": shlex.quote(str(rc))}
    script = re.sub(r"@[A-Z]+@", lambda m: values[m.group()], BAZEL_SHIM)
    path = bin_dir / "bazel"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o500)


def _take(mine: int, name: str, algorithm: str, theirs: Path) -> bool:
    """Copy the file of the role's entry `name` into the operator's directory `theirs`, if its checksum is its name.

    Returns:
        True when it was taken.
    """
    try:
        entry = os.open(name, DIR_FLAGS, dir_fd=mine)
    except OSError:
        return False
    try:
        try:
            fd = os.open(FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=entry)
        except OSError:
            return False
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return False
            theirs.mkdir(parents=True, exist_ok=True)
            temp = theirs / f"tmp-canopy-{secrets.token_hex(8)}"
            digest = hashlib.new(algorithm)
            try:
                with temp.open("xb") as copy:
                    while chunk := source.read(1 << 20):
                        digest.update(chunk)
                        copy.write(chunk)
                if digest.hexdigest() != name:
                    return False
                (theirs / name).mkdir(exist_ok=True)
                temp.replace(theirs / name / FILE)
            finally:
                temp.unlink(missing_ok=True)
        for marker in _list(entry):
            if MARKER.fullmatch(marker):
                (theirs / name / marker).touch()
        return True
    finally:
        os.close(entry)


def _link(mine: int, name: str, target: Path) -> None:
    """Put a link to the operator's entry `target` in place of the role's entry `name`, which the run downloaded."""
    away = f".{name}.{secrets.token_hex(8)}"
    os.rename(name, away, src_dir_fd=mine, dst_dir_fd=mine)
    os.symlink(target, name, dir_fd=mine)
    shutil.rmtree(away, dir_fd=mine, ignore_errors=True)


@contextlib.contextmanager
def _cas(cache: Path) -> Iterator[int]:
    """Open the role's repository cache's `content_addressable/`, making each directory not there, or not one.

    The run can write every directory below `cache`, so none is reached through a link it left.

    Yields:
        Its descriptor.
    """
    fd = os.open(cache, DIR_FLAGS)
    try:
        for name in (ROOT, REPOSITORY_CACHE, CAS):
            child = _made_dir(fd, name)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _made_dir(parent: int, name: str) -> int:
    """Open the directory `name` in `parent` without following a link, after making it in place of anything else.

    Returns:
        Its descriptor.
    """
    found = _open_dir(parent, name)
    if found is not None:
        return found
    with contextlib.suppress(FileNotFoundError):
        if stat.S_ISDIR(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
            shutil.rmtree(name, dir_fd=parent)
        else:
            os.unlink(name, dir_fd=parent)
    os.mkdir(name, 0o700, dir_fd=parent)
    return os.open(name, DIR_FLAGS, dir_fd=parent)


def _open_dir(parent: int, name: str) -> int | None:
    try:
        return os.open(name, DIR_FLAGS, dir_fd=parent)
    except OSError:
        return None


def _names(directory: Path) -> list[str]:
    try:
        return [p.name for p in directory.iterdir()]
    except OSError:
        return []


def _list(fd: int) -> list[str]:
    return os.listdir(fd)  # by descriptor, so that no link a run left is followed


def _is_key(name: str, length: int) -> bool:
    return len(name) == length and all(c in "0123456789abcdef" for c in name)


def _is_link(parent: int, name: str) -> bool:
    try:
        return stat.S_ISLNK(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode)
    except OSError:
        return False
