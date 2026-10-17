"""Asking `canopy loop` for a tick now from the web UI (DESIGN §6), as `t` at the loop's terminal does.

The request is for this process alone, as a reload is: it is asked for here (`TickNow.request`) from the web UI's
thread and taken by the loop's wait, which then ends at once. One asked for during a tick is kept, so the wait after it
ends at once.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TickNow:
    """Whether the operator asked the loop for a tick now. Set by the web UI's thread, taken by the loop's wait."""

    requested: bool = False

    def request(self) -> None:
        """Ask for a tick now."""
        self.requested = True

    def take(self) -> bool:
        """Take the request, if there is one, so that it ends one wait.

        Returns:
            Whether a tick was asked for since the last call.
        """
        asked, self.requested = self.requested, False
        return asked
