"""The operator's standing instructions files, one for each of four agents (DESIGN §12), and their kept versions.

An agent's file is the one `paths.<agent>_instructions` names, else its default, `<paths.instructions>/<agent>.md`,
which a run reads only while it is there; every later run of that agent reads its text, bounded by `MAX_BYTES`. The
settings' instructions page shows each one, edits its text, makes a default that is not there, and deletes one
(TRUST_MODEL T8, D134). It never chooses which file, so no `paths.*` key is written, and it never deletes a file a key
names, which would refuse every run of its agent. A change is the operator's, as a plan's edit is: refused inside one of
canopy's own runs, never through a link or in a directory anyone else may write in, never over a file that changed
since the page read it, and never past the bound. It writes a temporary file renamed into place, so a run starting then
reads the old text or the new, never half of either. Before a change, the file as it was is kept among the agent's
versions in the operator-only state directory, the newest `KEEP_VERSIONS`, which the page lists and restores from.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import re
import secrets
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from canopy.core import conversation, prompts
from canopy.core.conversation import Refused
from canopy.infra import lock

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    from canopy.core.config import Config, StandingAgent

#: Every agent, in the order the instructions page shows them.
AGENTS: tuple[StandingAgent, ...] = ("worker", "overseer", "reviewer", "chore")

#: The most bytes of a file a run takes: a longer one refuses every run of its agent.
MAX_BYTES = prompts.MAX_STANDING_BYTES

#: How many versions of each agent's file are kept: the newest, each the file as it was before a change.
KEEP_VERSIONS = 10

#: The state directory's directory of versions, one directory in it for each agent.
VERSIONS_DIR = "instructions"

# Read by name from the request, so each guard's words are the operator's to act on.
CONFIGURED = "configured"
TOO_LARGE = "too_large"
STALE = "stale"
UNSAFE_FILE = "unsafe_file"
NO_VERSION = "no_version"

# How much of a file each read takes.
_CHUNK = 64 * 1024

#: A version's name: when it was kept, to the microsecond, in UTC, so names sort as times do; then what made it.
_STAMP = "%Y%m%dT%H%M%S%fZ"
#: A name of that shape, in ASCII digits alone: anything else in the directory is not a version, and is never listed,
#: counted, or pruned.
_VERSION_NAME = re.compile(r"[0-9]{8}T[0-9]{12}Z-(?:edit|delete)\.md")

# The most of a file the page is shown: past the bound, so the operator can trim one from the page, but not without end.
_MAX_SHOWN = 16 * MAX_BYTES

#: What made a version: a save over the file, or its deletion.
type VersionKind = Literal["edit", "delete"]


@dataclass(frozen=True)
class Instructions:
    """One agent's standing instructions file as it stands."""

    #: The agent whose runs read it.
    agent: StandingAgent
    #: The config key that would name it, `paths.<agent>_instructions`.
    key: str
    #: The file: the key's, or the default.
    path: Path
    #: Whether the key names it (`config`), or it is the default (`default`), which a run reads only while it is there.
    source: Literal["config", "default"]
    #: Its text, or None when it cannot be shown: there is no file, or `problem` says why.
    text: str | None
    #: The SHA-256, hex, of its bytes, which a change names as the version it replaces; None when there is no file.
    sha256: str | None
    #: Why a run of the agent would refuse it, or the page cannot show it; None when it is usable, or a default that
    #: is not there.
    problem: str | None
    #: Whether there is no file at `path`: a run then reads none, or for a file the key names, is refused.
    missing: bool
    #: How many versions of it are kept.
    versions: int


@dataclass(frozen=True)
class Version:
    """The file as it was before one change, kept among its agent's versions."""

    #: Its name among them, which says when it was kept: `20261112T183000123456Z-edit`.
    id: str
    #: When it was kept: when the change it went before was made.
    at: datetime
    #: What made it.
    kind: VersionKind
    #: The SHA-256, hex, of its bytes.
    sha256: str
    #: Its size in bytes.
    size: int
    #: Its text, or None when it is not UTF-8 or too large to show.
    text: str | None


@dataclass(frozen=True)
class _Reading:
    """What a read of a file found, or that there is none: the start of its bytes, its hash and size, and its mode."""

    #: Its first `_MAX_SHOWN` bytes and one more, so a file past them is known as such; None when there is none.
    head: bytes | None
    #: The SHA-256, hex, of all its bytes; None when there is none.
    sha256: str | None
    #: Its size in bytes.
    size: int
    #: Its permission bits; None when there is none.
    mode: int | None

    @property
    def whole(self) -> bytes | None:
        """All its bytes, when the read kept them all: None when there is no file, or it is past `_MAX_SHOWN`."""
        return self.head if self.head is not None and self.size <= _MAX_SHOWN else None


def key_of(agent: StandingAgent) -> str:
    """Return the config key that names `agent`'s file.

    Returns:
        The key, `paths.<agent>_instructions`.
    """
    return f"paths.{agent}_instructions"


def read_all(config: Config, state_dir: Path) -> list[Instructions]:
    """Read every agent's standing instructions file, as a run of each would read it now.

    Returns:
        One for each of `AGENTS`, in order.
    """
    return [read(config, state_dir, agent) for agent in AGENTS]


def read(config: Config, state_dir: Path, agent: StandingAgent) -> Instructions:
    """Read `agent`'s standing instructions file, saying what a run of it would refuse.

    Returns:
        The file as it stands.
    """
    path = config.paths.instructions_file(agent)
    source: Literal["config", "default"] = (
        "default" if config.paths.configured_instructions(agent) is None else "config"
    )
    count = len(_version_names(state_dir, agent))

    def found(text: str | None, sha: str | None, problem: str | None, *, missing: bool = False) -> Instructions:
        return Instructions(agent, key_of(agent), path, source, text, sha, problem, missing, count)

    try:
        reading = _read(path)
    except Refused as r:
        return found(None, None, r.reason)
    except OSError as e:
        return found(None, None, f"cannot be read: {e.strerror}")
    if reading.head is None:
        # The default not there is no instructions at all; a file the key names not there refuses every run.
        why = None if source == "default" else "missing: every run of it is refused until it exists"
        return found(None, None, why, missing=True)
    text = None
    if reading.whole is not None:
        with contextlib.suppress(UnicodeDecodeError):
            text = reading.whole.decode("utf-8")
    return found(text, reading.sha256, _problem(reading))


def save(
    config: Config,
    state_dir: Path,
    agent: StandingAgent,
    text: str,
    *,
    read_path: Path,
    read_sha256: str | None,
) -> Instructions:
    """Write the operator's `text` over `agent`'s standing instructions file, as their own editor would.

    The page saves through this (TRUST_MODEL T8), over the agent's file, which it makes when it is not there, readable
    by the operator alone; a default's directory is made too, as theirs alone. The file as it was is kept among the
    agent's versions first. Text that does not end a line gets a newline. A run already started keeps the prompt it
    read; every run started after reads the new text.

    Returns:
        The file as saved.

    Raises:
        Refused: `inside_run` inside one of canopy's own runs; `too_large` for text over `MAX_BYTES`, or a file there
            past what a version keeps; `stale` when the agent's file is not `read_path`, the one the page read, since
            the config was read again, or it changed since, by `read_sha256`, None for a file that was not there;
            `unsafe_file` for a file that is a link, not a regular file, or not the operator's, or a directory that is
            not theirs or that a group or others may write in.
    """
    conversation.check_operator()
    if text and not text.endswith("\n"):
        text += "\n"
    data = text.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise Refused(TOO_LARGE, f"the text is {len(data)} bytes; a run takes at most {MAX_BYTES}")
    path = _same_file(config, agent, read_path)
    configured = config.paths.configured_instructions(agent) is not None
    # One change at a time in this workspace, so two made on the same read cannot both pass the hash check.
    with lock.hold(state_dir / "instructions.lock", wait=True):
        before = _read(path)
        _check_unchanged(path, before, read_sha256)
        with _directory(path, make=not configured) as dir_fd:
            # Taken now, so a file too large to keep refuses the save before anything is written.
            old = None if before.head is None else _kept(path, before)

            def keep_old() -> None:
                if old is not None:
                    _keep(state_dir, agent, old, "edit")

            _replace(dir_fd, path, before, data, read_sha256, keep=keep_old)
    return read(config, state_dir, agent)


def delete(
    config: Config,
    state_dir: Path,
    agent: StandingAgent,
    *,
    read_path: Path,
    read_sha256: str,
) -> Instructions:
    """Delete `agent`'s default standing instructions file, keeping it among its versions first.

    Only the default, `<paths.instructions>/<agent>.md`: a run reads it only while it is there, so once it is gone the
    agent reads none. A file the key names is never deleted: every run of the agent would then be refused.

    Returns:
        The file as it stands after: not there.

    Raises:
        Refused: `inside_run` inside one of canopy's own runs; `configured` when `paths.<agent>_instructions` names
            the file; `stale` when the agent's file is not `read_path`, or it is not there, or changed since the page
            read it, by `read_sha256`;
            `unsafe_file` as `save` refuses it.
    """
    conversation.check_operator()
    path = _same_file(config, agent, read_path)
    if config.paths.configured_instructions(agent) is not None:
        raise Refused(
            CONFIGURED,
            f"{key_of(agent)} names {path}: deleted, every run of the agent would be refused; empty it instead, or "
            "unset the key",
        )
    with lock.hold(state_dir / "instructions.lock", wait=True):
        before = _read(path)
        _check_unchanged(path, before, read_sha256)
        with _directory(path, make=False) as dir_fd:
            old = None if before.head is None else _kept(path, before)
            # Read again before keeping it, so a delete refused here keeps no version, and once more after, just before
            # removing it, as a save does around its rename: a hand edit is lost only if it lands in that last moment.
            _check_still(path, read_sha256)
            if old is not None:
                _keep(state_dir, agent, old, "delete")
                _check_still(path, read_sha256)
            try:
                os.unlink(path.name, dir_fd=dir_fd)
            except OSError as e:
                raise Refused(UNSAFE_FILE, f"{path} was not deleted: {e.strerror}") from None
    return read(config, state_dir, agent)


def versions(state_dir: Path, agent: StandingAgent) -> list[Version]:
    """Return the kept versions of `agent`'s file, newest first.

    Returns:
        Each version that can be read: one that is a link or not a regular file is left out.
    """
    found: list[Version] = []
    directory = state_dir / VERSIONS_DIR / agent
    for name in reversed(_version_names(state_dir, agent)):
        try:
            data = _read(directory / name).whole
        except (Refused, OSError):
            continue
        if data is None:
            continue
        stem = name.removesuffix(".md")
        stamp, _, kind = stem.partition("-")
        at = datetime.strptime(stamp, _STAMP).replace(tzinfo=UTC)
        text = None
        if len(data) <= _MAX_SHOWN:
            with contextlib.suppress(UnicodeDecodeError):
                text = data.decode("utf-8")
        found.append(
            Version(
                id=stem,
                at=at,
                kind="delete" if kind == "delete" else "edit",
                sha256=hashlib.sha256(data).hexdigest(),
                size=len(data),
                text=text,
            ),
        )
    return found


def _check_still(path: Path, read_sha256: str | None) -> None:
    """Read the file again and refuse a change to it unless it is still the one the page read.

    Raises:
        Refused: `stale` when it changed; `unsafe_file` when it can no longer be read, rather than a server error.
    """
    try:
        now = _read(path)
    except OSError as e:
        raise Refused(UNSAFE_FILE, f"{path} cannot be read: {e.strerror}") from None
    _check_unchanged(path, now, read_sha256)


def _same_file(config: Config, agent: StandingAgent, read_path: Path) -> Path:
    """Return `agent`'s file, refusing a change when it is not the one the page read.

    The config may have been read again since, naming another file: a change made on the page's read of one must not
    land on the other.

    Returns:
        The agent's file.

    Raises:
        Refused: `stale` when it is not `read_path`.
    """
    path = config.paths.instructions_file(agent)
    if path != read_path:
        raise Refused(STALE, f"{key_of(agent)} now resolves to {path}, not {read_path}; read it again")
    return path


def _version_names(state_dir: Path, agent: StandingAgent) -> list[str]:
    """The names of `agent`'s kept versions, oldest first.

    Returns:
        Each name that reads as a version's; none when the directory is not there.
    """
    try:
        names = [p.name for p in (state_dir / VERSIONS_DIR / agent).iterdir()]
    except OSError:
        return []
    return sorted(n for n in names if _is_version(n))


def _is_version(name: str) -> bool:
    """Whether `name` is one `_keep` gives a version: its shape, and a time that is one, not a thirteenth month.

    Returns:
        True for a version's name.
    """
    if not _VERSION_NAME.fullmatch(name):
        return False
    try:
        datetime.strptime(name.partition("-")[0], _STAMP)  # noqa: DTZ007  (read for its validity alone)
    except ValueError:
        return False
    return True


def _keep(state_dir: Path, agent: StandingAgent, data: bytes, kind: VersionKind) -> None:
    """Keep `data`, the file as it was, among `agent`'s versions, then drop all but the newest `KEEP_VERSIONS`.

    Raises:
        Refused: `unsafe_file` when the versions' directory is not the operator's alone, or a version cannot be kept.
    """
    directory = state_dir / VERSIONS_DIR / agent
    try:
        for d in (directory.parent, directory):
            with contextlib.suppress(FileExistsError):
                d.mkdir(mode=0o700)
        st = directory.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise Refused(UNSAFE_FILE, f"{directory} is not a directory of yours alone, so no version is kept there")
        name = f"{datetime.now(UTC).strftime(_STAMP)}-{kind}.md"
        fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except OSError as e:
        raise Refused(UNSAFE_FILE, f"cannot keep a version in {directory}: {e.strerror}") from None
    _prune(directory, _version_names(state_dir, agent))


def _prune(directory: Path, names: Sequence[str]) -> None:
    # All but the newest KEEP_VERSIONS, oldest first; one already gone is no matter.
    for name in names[: max(0, len(names) - KEEP_VERSIONS)]:
        with contextlib.suppress(FileNotFoundError):
            (directory / name).unlink()


def _problem(reading: _Reading) -> str | None:
    """Why a run would refuse the file `reading` read, as the prompts read it, or None when it would read it.

    Returns:
        The reason, or None.
    """
    if reading.size > MAX_BYTES:
        return f"{reading.size} bytes, over the {MAX_BYTES} a run takes: every run of it is refused until it is trimmed"
    try:
        (reading.head or b"").decode("utf-8")
    except UnicodeDecodeError:
        return "not UTF-8: every run of it is refused until it is"
    return None


def _kept(path: Path, before: _Reading) -> bytes:
    """All of the file `before` read, to keep as a version before a change.

    Returns:
        Its bytes.

    Raises:
        Refused: `too_large` for a file past `_MAX_SHOWN`, which no version keeps: trimmed by hand, it can be changed.
    """
    if before.whole is None:
        raise Refused(
            TOO_LARGE,
            f"{path} is {before.size} bytes, more than a version keeps; trim it by hand before changing it here",
        )
    return before.whole


def _read(path: Path) -> _Reading:
    """Read the file at `path` without following a link, refusing one that is not the operator's own regular file.

    It is opened without blocking, and checked as opened, so a link, a pipe, or another account's file put in its
    place after any check is refused rather than read. Only its first `_MAX_SHOWN` bytes and one more are kept; the
    rest is hashed as it is read, so a huge file costs the server no more memory than a small one.

    Returns:
        What it read, or a reading of none when there is no file.

    Raises:
        Refused: `unsafe_file` for a link, anything but a regular file, or a file of another account's.
        OSError: The file is there and cannot be read.
    """
    unsafe = f"{path} is a symlink, not a regular file, or not yours; the web UI writes only a file of your own"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return _Reading(None, None, 0, None)
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise Refused(UNSAFE_FILE, unsafe) from None
        raise
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            raise Refused(UNSAFE_FILE, unsafe)
        digest = hashlib.sha256()
        head = bytearray()
        size = 0
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
            if len(head) <= _MAX_SHOWN:
                head += chunk[: _MAX_SHOWN + 1 - len(head)]
        return _Reading(bytes(head), digest.hexdigest(), size, stat.S_IMODE(st.st_mode))


def _check_unchanged(path: Path, before: _Reading, read_sha256: str | None) -> None:
    """Refuse a change to a file other than the one the page read.

    Raises:
        Refused: `stale` when the file's hash is not `read_sha256`, or it is there when the page read none.
    """
    if before.sha256 != read_sha256:
        raise Refused(STALE, f"{path} changed since the page read it; read it again and redo the change")


@contextlib.contextmanager
def _directory(path: Path, *, make: bool) -> Iterator[int]:
    """Open `path`'s directory, once, for every name to be taken relative to it, and check it is the operator's alone.

    With `make`, a directory not there is made first, as the operator's alone, in a parent that is theirs: a default's.

    Yields:
        The directory's descriptor, closed when the block ends.

    Raises:
        Refused: `unsafe_file` for a directory that cannot be opened or made, is not the operator's, or that a group or
            others may write in.
    """
    if make:
        with contextlib.suppress(FileExistsError):
            try:
                path.parent.mkdir(mode=0o700)
            except FileNotFoundError:
                raise Refused(UNSAFE_FILE, f"{path.parent.parent} is not there to make {path.parent} in") from None
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as e:
        raise Refused(UNSAFE_FILE, f"cannot open {path.parent}: {e.strerror}") from None
    try:
        st = os.fstat(dir_fd)
        # As D053 holds the private config: no one else may write there, a group included, or they could put a file of
        # their own in place of the temporary one between its write and its rename.
        if st.st_uid != os.getuid() or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise Refused(
                UNSAFE_FILE,
                f"{path.parent} is not yours, or a group or others may write in it; write {path} by hand",
            )
        yield dir_fd
    finally:
        os.close(dir_fd)


def _replace(
    dir_fd: int,
    path: Path,
    before: _Reading,
    data: bytes,
    read_sha256: str | None,
    *,
    keep: Callable[[], None],
) -> None:
    """Write `data` at `path` through a temporary file in its directory, `dir_fd`, renamed into place.

    `keep` runs once the file is known unchanged, just before the rename, so a save refused at that last moment has
    kept no version of the file and pruned none.

    Raises:
        Refused: `unsafe_file` for a file that could not be written; `stale` when the file changed while it was saved.
    """
    mode = before.mode if before.mode is not None else 0o600
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
        keep()
        # And once more, as keeping it took a moment of its own.
        _check_unchanged(path, _read(path), read_sha256)
        # A rename replaces the name itself, never what a link there names.
        os.rename(temporary, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except Refused:
        _drop(temporary, dir_fd)
        raise
    except OSError as e:
        _drop(temporary, dir_fd)
        raise Refused(UNSAFE_FILE, f"{path} was not saved: {e.strerror}") from None


def _drop(name: str, dir_fd: int) -> None:
    # A temporary file a failed save leaves, if it made one.
    with contextlib.suppress(FileNotFoundError):
        os.unlink(name, dir_fd=dir_fd)
