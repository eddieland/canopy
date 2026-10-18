"""Hand a sandboxed run the operator's OpenCode logins, and take back only the tokens it refreshed (DESIGN §24).

A sandboxed run's OpenCode keeps its data in a directory of its role's own, never the operator's: the operator's
OpenCode, and the overseer's, outside any sandbox, run code that their data directory names. The logins are the only
part of it a run needs, and OpenCode keeps them in two files there (checked against OpenCode 1.19.3):

    auth.json       each provider's login: {"type": "api", "key"}, {"type": "oauth", "refresh", "access",
                    "expires", ...} with `expires` in milliseconds, or {"type": "wellknown", ...}, which names a URL
                    whose config OpenCode merges, with its plugins and local MCP servers
    mcp-auth.json   each remote MCP server's OAuth state: {"tokens": {"accessToken", "refreshToken", "expiresAt",
                    "scope"}, "clientInfo", "serverUrl", ...}, with `expiresAt` in seconds

`share` copies the operator's two files into the role's data directory, whole, before each run, so the run starts
with the operator's logins and nothing a run before it left there. `collect` copies back, after each run and before
the next, only what an OAuth refresh changes: the tokens and their expiry, of a login the operator already has, of the
same kind, and only when the run's expire later. It never adds a login, never takes a field that says where a token is
sent or which account it is, and never takes an entry of any other kind: a provider that rotates refresh tokens
would otherwise log the operator out once a run refreshed one, and anything more is a way out of the sandbox.

What a run leaves in its data directory is read on the host, so it is read without following a link and without
blocking on a fifo, at most `MAX_FILE` bytes of it, and anything that is not the shape OpenCode writes is left there.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import secrets
import shutil
import stat
from pathlib import Path
from typing import TYPE_CHECKING, TypeGuard

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# OpenCode's data directory under XDG_DATA_HOME, and the files in it that hold its logins.
RUNTIME = "opencode"
AUTH = "auth.json"
MCP_AUTH = "mcp-auth.json"
FILES = (AUTH, MCP_AUTH)
# More than any login file holds, and less than a run could make the host read.
MAX_FILE = 1 << 20
MAX_TOKEN = 1 << 16
# What `share` and `collect` hold while they read and write, in the directory that holds every role's data directory,
# which no run can write.
LOCK = "credentials.lock"
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@contextlib.contextmanager
def locked(root: Path) -> Iterator[None]:
    """Hold the lock every run's `share` and `collect` take, in `root`, the directory of every role's data directory.

    Yields:
        Nothing, while the lock is held.
    """
    fd = os.open(root / LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def share(operator: Path, data: Path) -> None:
    """Copy the operator's login files, in the OpenCode data directory `operator`, into the role's `data`.

    A file the operator has none of is removed from the role's, so a login the operator dropped goes with it.
    `data` is the role's XDG_DATA_HOME, which the wrapper made; its `opencode/` is the run's to write, and is made
    again when a run left something else there.
    """
    role = os.open(data, DIR_FLAGS)
    try:
        runtime = _made_runtime_dir(role)
        try:
            for name in FILES:
                try:
                    content = (operator / name).read_bytes()
                except FileNotFoundError:
                    content = None
                _place(runtime, name, content)
        finally:
            os.close(runtime)
    finally:
        os.close(role)


def collect(data: Path, operator: Path) -> list[str]:
    """Copy into the operator's login files, in the OpenCode data directory `operator`, each token a run refreshed.

    Returns:
        The logins whose tokens were taken, as `auth.json: anthropic`, for the wrapper to say.
    """
    role = os.open(data, DIR_FLAGS)
    try:
        runtime = _runtime_dir(role)
        if runtime is None:
            return []
        try:
            taken: list[str] = []
            for name, refreshed in ((AUTH, refreshed_login), (MCP_AUTH, refreshed_mcp_login)):
                theirs = _read(runtime, name)
                if theirs is not None:
                    taken.extend(f"{name}: {key}" for key in _merge(operator / name, theirs, refreshed))
            return taken
        finally:
            os.close(runtime)
    finally:
        os.close(role)


def refreshed_login(ours: object, theirs: object) -> dict[str, object] | None:
    """Return the operator's `auth.json` entry with a run's refreshed tokens, when the run's is a refresh of it.

    Both are OAuth logins, the run's tokens are strings and its expiry a later whole number: OpenCode drops an entry it
    cannot decode, which would log the operator out. Every other field stays the operator's: `enterpriseUrl` says where
    the token is sent, and `accountId` whose account it is.

    Returns:
        The entry to keep, or None to keep the operator's as it is.
    """
    if not isinstance(ours, dict) or not isinstance(theirs, dict):
        return None
    mine: dict[str, object] = ours
    run: dict[str, object] = theirs
    if mine.get("type") != "oauth" or run.get("type") != "oauth":
        return None
    refresh, access, expires, before = run.get("refresh"), run.get("access"), run.get("expires"), mine.get("expires")
    if not (_token(refresh) and _token(access) and _whole(expires) and _whole(before)):
        return None
    if expires <= before:
        return None
    return {**mine, "refresh": refresh, "access": access, "expires": expires}


def refreshed_mcp_login(ours: object, theirs: object) -> dict[str, object] | None:
    """Return the operator's `mcp-auth.json` entry with a run's refreshed tokens, when the run's is a refresh of it.

    Both are for the same server URL, and both have tokens that expire, the run's later. Only `tokens` is taken, and
    only its four fields: `clientInfo` and `serverUrl` stay the operator's. OpenCode drops the whole file when one
    entry does not decode, so every field taken is checked for its type.

    Returns:
        The entry to keep, or None to keep the operator's as it is.
    """
    if not isinstance(ours, dict) or not isinstance(theirs, dict):
        return None
    mine: dict[str, object] = ours
    run: dict[str, object] = theirs
    old, new = mine.get("tokens"), run.get("tokens")
    if mine.get("serverUrl") != run.get("serverUrl") or not isinstance(old, dict) or not isinstance(new, dict):
        return None
    was: dict[str, object] = old
    now: dict[str, object] = new
    access, expires, before = now.get("accessToken"), now.get("expiresAt"), was.get("expiresAt")
    if not (_token(access) and _number(expires) and _number(before)):
        return None
    if expires <= before:
        return None
    tokens: dict[str, object] = {"accessToken": access, "expiresAt": expires}
    for field in ("refreshToken", "scope"):  # a refresh may leave either out, which keeps the one before
        value = now.get(field)
        if value is None:
            value = was.get(field)
        if value is None:
            continue
        if not _token(value):
            return None
        tokens[field] = value
    return {**mine, "tokens": tokens}


def _merge(
    path: Path, theirs: dict[str, object], refreshed: Callable[[object, object], dict[str, object] | None]
) -> list[str]:
    """Write into the operator's file at `path` each of its entries that `theirs` holds a refresh of.

    Returns:
        The keys of the entries written.
    """
    try:
        ours: object = json.loads(path.read_bytes())
    except (OSError, ValueError, RecursionError):
        return []
    if not isinstance(ours, dict):
        return []
    mine: dict[str, object] = ours
    changed = {key: entry for key in mine if key in theirs and (entry := refreshed(mine[key], theirs[key])) is not None}
    if not changed:
        return []
    try:
        content = json.dumps({**mine, **changed}, indent=2, allow_nan=False).encode()
    except ValueError:
        return []
    target = path.resolve()  # a link the operator keeps, as a dotfile manager makes, stays a link
    fd, temp = _temp_in(target.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        Path(temp).replace(target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return list(changed)


def _runtime_dir(role: int) -> int | None:
    """Open OpenCode's data directory in the role's, by the descriptor `role`, without following a link.

    Returns:
        Its descriptor, or None when it is missing or not a directory.
    """
    try:
        return os.open(RUNTIME, DIR_FLAGS, dir_fd=role)
    except OSError:
        return None


def _made_runtime_dir(role: int) -> int:
    """Open OpenCode's data directory in the role's, after making it again in place of anything else a run left.

    Returns:
        Its descriptor.
    """
    runtime = _runtime_dir(role)
    if runtime is not None:
        return runtime
    with contextlib.suppress(FileNotFoundError):
        _remove(role, RUNTIME)  # a link, or a file
    os.mkdir(RUNTIME, 0o700, dir_fd=role)
    return os.open(RUNTIME, DIR_FLAGS, dir_fd=role)


def _place(runtime: int, name: str, content: bytes | None) -> None:
    """Replace the entry `name` in the directory `runtime` with a private file holding `content`, or remove it."""
    with contextlib.suppress(FileNotFoundError):
        if stat.S_ISDIR(os.stat(name, dir_fd=runtime, follow_symlinks=False).st_mode):
            shutil.rmtree(name, dir_fd=runtime)
    if content is None:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name, dir_fd=runtime)
        return
    temp = f".{name}.{secrets.token_hex(8)}"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=runtime)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(temp, name, src_dir_fd=runtime, dst_dir_fd=runtime)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp, dir_fd=runtime)
        raise


def _read(runtime: int, name: str) -> dict[str, object] | None:
    """Read the JSON object a run left as `name` in the directory `runtime`.

    Returns:
        The object, or None for anything else: a link, a fifo, a file too big, or not a JSON object.
    """
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=runtime)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        raw = f.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        return None
    try:
        data: object = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _remove(parent: int, name: str) -> None:
    if stat.S_ISDIR(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
        shutil.rmtree(name, dir_fd=parent)
    else:
        os.unlink(name, dir_fd=parent)


def _temp_in(directory: Path) -> tuple[int, str]:
    """Make a private file beside the operator's, to write in full and rename over it.

    Returns:
        Its descriptor and path.
    """
    path = directory / f".canopy-sandbox.{secrets.token_hex(8)}"
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), str(path)


def _token(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and 0 < len(value) <= MAX_TOKEN


def _whole(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _number(value: object) -> TypeGuard[float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
