"""Stopping a detached run cleanly: SIGTERM, SIGHUP, and SIGINT become an exception only the cleanup code catches.

`canopy _run` and `canopy _chore` run detached and must return what they hold (slots, a desk) and close their journal
row however they end. SIGKILL cannot be caught; reconcile handles that.
"""

from __future__ import annotations

import signal
from collections.abc import Callable
from types import FrameType, TracebackType
from typing import Self


class Stopped(BaseException):
    """This process got a signal asking it to stop. A BaseException, so only the cleanup code catches it."""

    def __init__(self, signum: int) -> None:
        """Record which signal."""
        super().__init__(f"stopped by signal {signal.Signals(signum).name}")
        self.signum = signum


class StopOnSignal:
    """While armed, SIGTERM, SIGHUP, and SIGINT raise `Stopped`, so cleanup runs. Disarmed, they are ignored."""

    SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)

    def __init__(self) -> None:
        """Start armed; nothing is installed until the block is entered."""
        self.armed = True
        self._previous: dict[signal.Signals, Callable[[int, FrameType | None], object] | int | None] = {}

    def _handle(self, signum: int, frame: FrameType | None) -> None:  # noqa: ARG002
        if self.armed:
            self.armed = False
            raise Stopped(signum)

    def __enter__(self) -> Self:
        """Install the handlers.

        Returns:
            This object, so the block can disarm it (`armed = False`) before cleanup it must not interrupt.
        """
        for s in self.SIGNALS:
            self._previous[s] = signal.signal(s, self._handle)
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        """Put back the handlers that were there before."""
        for s, handler in self._previous.items():
            signal.signal(s, handler)
