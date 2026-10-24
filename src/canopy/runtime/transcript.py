"""A session's transcript, read back from what a run's log holds (DESIGN §13, §22).

canopy writes what a template printed, as printed, to the run's log or the tick's output file. This reads one session
back from it, in the order it was printed, as entries a page can show (`canopy.runtime.entries`): the agent's text, its
reasoning, each tool call with its input and output, each model call's cost, and the runtime's errors, each numbered by
the model call it came from. The runtime's implementation reads its own events into entries; what is not an event of
the session, such as stderr, a setup command's output, and the harness's own lines, never shows as the agent's.

`prompt` reads the message canopy gave the runtime, which it keeps beside the log (`prompt_path`): the first model
call's input, but for the agent's definition and the runtime's own system prompt and tools, which nothing prints.

Everything here is agent output: untrusted, and unbounded until it is read. So the file is read only if it is a
regular file and not a symlink, at most `MAX_BYTES` of it; each event is validated (D026); control characters are
dropped; and each text, the transcript's entries, and their characters altogether are cut at a bound, with
`truncated` saying something was. An event of a known type that does not validate is counted in `unreadable`.

`tail` reads the end of such a file as written, for a tick's output shown whole: stderr and every line the transcript
leaves out. The same checks hold, at most `MAX_TAIL` of it is read, and its control characters are dropped.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.infra.text import printable
from canopy.runtime import entries
from canopy.runtime.entries import Text, ToolCall
from canopy.runtime.implementation import one, pick, two

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from canopy.runtime.entries import Entry
    from canopy.runtime.implementation import Version

#: How much of a log is read: far more than a long run prints, and little enough to read on each request.
MAX_BYTES = 32 * 1024 * 1024
#: How many entries a transcript holds, and how many characters all of them hold together.
MAX_ENTRIES = 2000
MAX_CHARS = 2_000_000
#: How much of the end of a file `tail` reads: far more than an overseer prints on stderr, and little enough to send.
MAX_TAIL = 1024 * 1024
#: How much of a prompt `prompt` reads: far more than canopy renders, a tick's state block included.
MAX_PROMPT = 1024 * 1024


@dataclass(frozen=True)
class Transcript:
    """What a log holds of one session. `truncated` when a bound cut anything; `unreadable` events did not validate."""

    entries: Sequence[Entry] = ()
    truncated: bool = False
    unreadable: int = 0


@dataclass(frozen=True)
class Prompt:
    """The message canopy gave the runtime: at most `MAX_PROMPT` bytes of it, `truncated` when it holds more."""

    text: str
    truncated: bool


@dataclass(frozen=True)
class Tail:
    """The end of a file as written: at most `MAX_TAIL` bytes of it, `truncated` when it holds more, of `size` bytes."""

    text: str
    size: int
    truncated: bool


def read(path: Path, session_id: str, *, version: Version) -> Transcript | None:
    """Read `session_id`'s events from the log at `path`. None when it is missing, a symlink, or not a regular file.

    The events are read as the runtime `version` runs prints them.

    Returns:
        The session's entries, within the bounds, and whether a bound cut any; or None for a file it refuses.
    """
    fd = _open(path)
    if fd is None:
        return None
    with os.fdopen(fd, "rb") as f:
        data = f.read(MAX_BYTES + 1)
    truncated = len(data) > MAX_BYTES
    if truncated:
        # The last line read may be cut short; it is not an event then.
        data = data[: data.rfind(b"\n", 0, MAX_BYTES) + 1]
    lines = data.decode("utf-8", errors="replace").splitlines()
    return _bounded(pick(version, one.transcript, two.transcript).read(lines, session_id), truncated=truncated)


def tail(path: Path) -> Tail | None:
    """Read the end of the file at `path`, from its first whole line. None for any file `read` would refuse.

    Returns:
        At most `MAX_TAIL` bytes of the file's end as printable text, with the file's size and whether it holds more;
        or None for a file it refuses.
    """
    fd = _open(path)
    if fd is None:
        return None
    with os.fdopen(fd, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        f.seek(max(0, size - MAX_TAIL))
        data = f.read(MAX_TAIL)
    truncated = size > MAX_TAIL
    if truncated:
        # The first line read may be cut short, a character too: start at the next whole line.
        data = data[data.find(b"\n") + 1 :]
    return Tail(printable(data.decode("utf-8", errors="replace")), size, truncated)


def prompt_path(log: Path) -> Path:
    """Return where canopy keeps the prompt of the session whose events are in `log`: beside it, as `<id>.prompt`."""
    return log.with_suffix(".prompt")


def prompt(path: Path) -> Prompt | None:
    """Read the prompt at `path`, from its start. None for any file `read` would refuse.

    Returns:
        At most `MAX_PROMPT` bytes of it as printable text, line breaks kept, and whether it holds more; or None.
    """
    fd = _open(path)
    if fd is None:
        return None
    with os.fdopen(fd, "rb") as f:
        data = f.read(MAX_PROMPT + 1)
    truncated = len(data) > MAX_PROMPT
    return Prompt(printable(data[:MAX_PROMPT].decode("utf-8", errors="replace")), truncated)


def _open(path: Path) -> int | None:
    """A descriptor for reading the regular file at `path`, or None when it is missing, a symlink, or anything else.

    Returns:
        An open read-only descriptor the caller closes, or None.
    """
    try:
        # Non-blocking, so a FIFO in the file's place cannot hold the request open; it is refused below.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    return fd


# The entries of `read`, a session's as the implementation reads them, within `MAX_ENTRIES` and `MAX_CHARS`.
def _bounded(read: Iterable[Entry | None], *, truncated: bool) -> Transcript:
    found: list[Entry] = []
    chars = 0
    unreadable = 0
    for entry in read:
        if entry is None:
            unreadable += 1
            continue
        size = entries.size(entry)
        if len(found) == MAX_ENTRIES or chars + size > MAX_CHARS:
            truncated = True
            break
        found.append(entry)
        chars += size
        truncated = truncated or (isinstance(entry, Text | ToolCall) and entry.cut)
    return Transcript(found, truncated, unreadable)
