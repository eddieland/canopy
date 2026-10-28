"""Single keypresses at the terminal, read without Enter, for `canopy loop`'s countdown (DESIGN §6).

While `listen` is entered, the terminal is in cbreak mode: keys arrive one at a time and are not echoed, and Ctrl-C and
Ctrl-Z still send their signals. The terminal's settings are put back on the way out. Only a terminal this process
reads from the foreground gets this; anything else reads no keys, and the loop then shows no hint for them.
"""

from __future__ import annotations

import contextlib
import os
import select
import termios
import tty
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import IO, Any, Final

# Enough for anything a person types between two of the countdown's redraws.
_READ_BYTES: Final = 1024


@contextmanager
def listen(stream: IO[str] | None) -> Generator[Callable[[], str] | None]:
    """Yield a function returning the keys pressed since it was last called, or None when `stream` is no terminal.

    The function never blocks. None also when the terminal cannot be set up, or when this process is in the background:
    changing a terminal's settings from there stops the process (SIGTTOU).
    """
    fd = _terminal_fd(stream)
    saved = _cbreak(fd) if fd is not None else None
    if fd is None or saved is None:
        yield None
        return
    try:
        yield lambda: _pending(fd)
    finally:
        # The process may have lost the terminal (a hangup); there is then nothing to put back.
        with contextlib.suppress(termios.error):
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _terminal_fd(stream: IO[str] | None) -> int | None:
    """The descriptor of `stream` if it is a terminal this process reads in the foreground.

    Returns:
        The descriptor, or None when `stream` is None, has none, is not a terminal, or this process is in the
        background on it.
    """
    if stream is None:
        return None
    try:
        fd = stream.fileno()
    except (OSError, ValueError):  # a captured or closed stream; io.UnsupportedOperation is an OSError
        return None
    if not os.isatty(fd):
        return None
    try:
        if os.tcgetpgrp(fd) != os.getpgrp():
            return None
    except OSError:
        pass  # not this process's controlling terminal, so no job control to fall foul of
    return fd


def _cbreak(fd: int) -> list[Any] | None:  # termios' own type for a terminal's settings
    """Put the terminal at `fd` in cbreak mode. Returns its settings before, or None if it could not be changed.

    Returns:
        The terminal's settings before the change, to put back, or None when they could not be changed.
    """
    try:
        return tty.setcbreak(fd)
    except termios.error:
        return None


def _pending(fd: int) -> str:
    """Every key waiting to be read at `fd`, without waiting for one.

    Returns:
        The keys read, decoded with bad bytes replaced; empty when none was waiting.
    """
    keys: list[bytes] = []
    while select.select([fd], [], [], 0)[0]:
        chunk = os.read(fd, _READ_BYTES)
        if not chunk:
            break
        keys.append(chunk)
    return b"".join(keys).decode(errors="replace")
