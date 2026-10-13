"""Telling a terminal hanging up from a deliberate SIGHUP, for `canopy loop`'s reload (DESIGN §6).

Both arrive as SIGHUP. A terminal that hung up stays hung up: its descriptors are no longer terminals to `isatty`. So
`watch` holds the controlling terminal open from the start, and asks it at each signal. With no controlling terminal
(cron, a service manager, `setsid`), no SIGHUP is a hangup.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Generator
from contextlib import contextmanager

# The controlling terminal, whichever descriptors point at it: output sent to a file still hangs up with it.
_CONTROLLING_TERMINAL = "/dev/tty"


@contextmanager
def watch() -> Generator[Callable[[], bool]]:
    """Yield a function saying whether the controlling terminal this process had on entry has since hung up."""
    try:
        fd = os.open(_CONTROLLING_TERMINAL, os.O_RDONLY | os.O_NOCTTY)
    except OSError:  # ENXIO: no controlling terminal
        yield lambda: False
        return
    try:
        yield lambda: not os.isatty(fd)
    finally:
        os.close(fd)
