"""The operator's standing instructions files, one for each of four agents (DESIGN §12): read, and saved from the page.

`paths.worker_instructions`, `overseer_instructions`, `reviewer_instructions`, and `chore_instructions` each name a file
of the operator's whose text every later run of that agent reads, bounded by `prompts.MAX_STANDING_BYTES`. The settings
page shows each one and edits its text (TRUST_MODEL T8, D134): only a file the config already names, never which file,
so no `paths.*` key is written. A save is the operator's, as a plan's edit is: refused inside one of canopy's own runs,
never through a link, never over a file that changed since the page read it, and never past the bound the prompts would
refuse. It keeps the file as it was beside it as `<name>.bak`, and writes a temporary file renamed into place, so a run
starting then reads the old text or the new, never half of either.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import secrets
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from canopy.core import conversation, prompts
from canopy.core.conversation import Refused
from canopy.infra import lock

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.config import Config

#: One of the agents a standing instructions file reaches: `worker` reaches implement, resume, plan, and task runs too.
type Agent = Literal["worker", "overseer", "reviewer", "chore"]

#: Every agent, in the order the settings page shows them.
AGENTS: tuple[Agent, ...] = ("worker", "overseer", "reviewer", "chore")

#: The suffix of the file as it was before the last save, kept beside it.
BACKUP_SUFFIX = ".bak"

# Read by name from the request, so each guard's words are the operator's to act on.
NOT_SET = "not_set"
TOO_LARGE = "too_large"
STALE = "stale"
UNSAFE_FILE = "unsafe_file"

# The most of a file the page is shown: past the bound, so the operator can trim one from the page, but not without end.
_MAX_SHOWN = 16 * prompts.MAX_STANDING_BYTES


@dataclass(frozen=True)
class Instructions:
    """One agent's standing instructions file as it stands."""

    #: The agent whose runs read it.
    agent: Agent
    #: The config key that names it, `paths.<agent>_instructions`.
    key: str
    #: The file, or None when the key names none.
    path: Path | None
    #: Its text, or None when it cannot be shown: there is none, or `problem` says why.
    text: str | None
    #: The SHA-256, hex, of its bytes, which a save names as the version it replaces; None when there is no file.
    sha256: str | None
    #: Why a run of the agent would refuse it, or the page cannot show it; None when it is usable.
    problem: str | None
    #: Whether the config names a file that is not there, which a save makes.
    missing: bool = False


@dataclass(frozen=True)
class _Reading:
    """What a read of a file found: its bytes and mode, or that there is none."""

    data: bytes | None
    mode: int | None


def key_of(agent: Agent) -> str:
    """Return the config key that names `agent`'s file.

    Returns:
        The key, `paths.<agent>_instructions`.
    """
    return f"paths.{agent}_instructions"


def path_of(config: Config, agent: Agent) -> Path | None:
    """Return the file the config names for `agent`'s standing instructions.

    Returns:
        The path, or None when none is set.
    """
    match agent:
        case "worker":
            return config.paths.worker_instructions
        case "overseer":
            return config.paths.overseer_instructions
        case "reviewer":
            return config.paths.reviewer_instructions
        case "chore":
            return config.paths.chore_instructions


def read_all(config: Config) -> list[Instructions]:
    """Read every agent's standing instructions file, as a run of each would read it now.

    Returns:
        One for each of `AGENTS`, in order.
    """
    return [read(config, agent) for agent in AGENTS]


def read(config: Config, agent: Agent) -> Instructions:
    """Read `agent`'s standing instructions file, saying what a run of it would refuse.

    Returns:
        The file as it stands.
    """
    path = path_of(config, agent)
    if path is None:
        return Instructions(agent, key_of(agent), None, None, None, None)
    try:
        found = _read(path)
    except Refused as r:
        return Instructions(agent, key_of(agent), path, None, None, r.reason)
    except OSError as e:
        return Instructions(agent, key_of(agent), path, None, None, f"cannot be read: {e.strerror}")
    if found.data is None:
        why = "missing: every run of it is refused until it exists"
        return Instructions(agent, key_of(agent), path, None, None, why, missing=True)
    sha = hashlib.sha256(found.data).hexdigest()
    problem = _problem(found.data)
    text = None
    if len(found.data) <= _MAX_SHOWN:
        with contextlib.suppress(UnicodeDecodeError):
            text = found.data.decode("utf-8")
    return Instructions(agent, key_of(agent), path, text, sha, problem)


def save(config: Config, state_dir: Path, agent: Agent, text: str, *, read_sha256: str | None) -> Instructions:
    """Write the operator's `text` over `agent`'s standing instructions file, as their own editor would.

    The page saves through this (TRUST_MODEL T8): only over the file the config names, which it makes when it is
    missing, readable by the operator alone, in a directory of theirs. Text that does not end a line gets a newline.
    A run already started keeps the prompt it read; every run started after reads the new text.

    Returns:
        The file as saved.

    Raises:
        Refused: `inside_run` inside one of canopy's own runs; `not_set` when the config names no file for `agent`;
            `too_large` for text over `prompts.MAX_STANDING_BYTES`; `stale` when the file changed since the page read
            it, by `read_sha256`, None for a file that was missing; `unsafe_file` for a file that is a link, not a
            regular file, or not the operator's, or a directory that is not theirs or that a group or others may write
            in.
    """
    conversation.check_operator()
    path = path_of(config, agent)
    if path is None:
        raise Refused(NOT_SET, f"{key_of(agent)} names no file; set it in your config to write the instructions here")
    if text and not text.endswith("\n"):
        text += "\n"
    data = text.encode("utf-8")
    if len(data) > prompts.MAX_STANDING_BYTES:
        raise Refused(TOO_LARGE, f"the text is {len(data)} bytes; a run takes at most {prompts.MAX_STANDING_BYTES}")
    # One save at a time in this workspace, so two made on the same read cannot both pass the hash check.
    with lock.hold(state_dir / "instructions.lock", wait=True):
        before = _read(path)
        _check_unchanged(path, before, read_sha256)
        _write(path, before, data, read_sha256)
    return read(config, agent)


def _problem(data: bytes) -> str | None:
    """Why a run would refuse a file of `data`, as `prompts` reads it, or None when it would read it.

    Returns:
        The reason, or None.
    """
    if len(data) > prompts.MAX_STANDING_BYTES:
        return (
            f"{len(data)} bytes, over the {prompts.MAX_STANDING_BYTES} a run takes: every run of it is refused until "
            "it is trimmed"
        )
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "not UTF-8: every run of it is refused until it is"
    return None


def _read(path: Path) -> _Reading:
    """Read the file at `path` without following a link, refusing one that is not the operator's own regular file.

    Returns:
        Its bytes and mode, or none of either when there is no file.

    Raises:
        Refused: `unsafe_file` for a link, anything but a regular file, or a file of another account's.
        OSError: The file is there and cannot be read.
    """
    try:
        st = path.lstat()
    except FileNotFoundError:
        return _Reading(None, None)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        raise Refused(
            UNSAFE_FILE,
            f"{path} is a symlink, not a regular file, or not yours; the web UI writes only a file of your own",
        )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        return _Reading(f.read(), stat.S_IMODE(st.st_mode))


def _check_unchanged(path: Path, before: _Reading, read_sha256: str | None) -> None:
    """Refuse a save over a file other than the one the page read.

    Raises:
        Refused: `stale` when the file's hash is not `read_sha256`, or it is there when the page read none.
    """
    found = None if before.data is None else hashlib.sha256(before.data).hexdigest()
    if found != read_sha256:
        raise Refused(STALE, f"{path} changed since the page read it; read it again and redo the change")


def _write(path: Path, before: _Reading, data: bytes, read_sha256: str | None) -> None:
    """Write `data` at `path` through a temporary file in its directory renamed into place, keeping the old as `.bak`.

    The directory is opened once and every name is taken relative to it, so a directory swapped for a link between
    the check and the write is not followed.

    Raises:
        Refused: `unsafe_file` for a directory that is missing, not the operator's, or others may write in, a backup
            that cannot be kept, or a file that could not be written; `stale` when the file changed while it was saved.
    """
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as e:
        raise Refused(UNSAFE_FILE, f"cannot open {path.parent}: {e.strerror}") from None
    try:
        st = os.fstat(dir_fd)
        # As D053 holds the private config: no one else may write there, a group included, or they could put a file of
        # their own in place of the temporary one between its write and its rename.
        if st.st_uid != os.getuid() or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise Refused(UNSAFE_FILE, f"{path.parent} is not yours, or others may write in it; write {path} by hand")
        mode = before.mode if before.mode is not None else 0o600
        if before.data is not None:
            _back_up(dir_fd, path, before.data, mode)
        temporary = f".{path.name}.{secrets.token_hex(8)}.tmp"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=dir_fd)
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), mode)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            # Read again just before the rename, so a hand edit is lost only if it lands in that last moment.
            _check_unchanged(path, _read(path), read_sha256)
            # A rename replaces the name itself, never what a link there names.
            os.rename(temporary, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except Refused:
            _drop(temporary, dir_fd)
            raise
        except OSError as e:
            _drop(temporary, dir_fd)
            raise Refused(UNSAFE_FILE, f"{path} was not saved: {e.strerror}") from None
    finally:
        os.close(dir_fd)


def _drop(name: str, dir_fd: int) -> None:
    # A temporary file a failed save leaves, if it made one.
    with contextlib.suppress(FileNotFoundError):
        os.unlink(name, dir_fd=dir_fd)


def _back_up(dir_fd: int, path: Path, data: bytes, mode: int) -> None:
    """Keep the file as it was beside it, as `<name>.bak` with its mode, replacing the last save's.

    Raises:
        Refused: `unsafe_file` when the backup's name is a link or it cannot be written.
    """
    name = path.name + BACKUP_SUFFIX
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode, dir_fd=dir_fd)
    except OSError as e:
        raise Refused(UNSAFE_FILE, f"cannot keep a backup at {path.with_name(name)}: {e.strerror}") from None
    with os.fdopen(fd, "wb") as f:
        os.fchmod(f.fileno(), mode)
        f.write(data)
