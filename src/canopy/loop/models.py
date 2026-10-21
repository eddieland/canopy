"""Which models served the runs left unread, read while `canopy loop` waits between ticks (DESIGN §13).

Each run's session is read by the process that ran it, as it closes the run, and each overseer's by its tick
(`run_models.read_ended`). What that leaves unread is read here: a run whose process died, a read that failed and is
due again, and the history from before canopy read any. The wait after a live tick reads one run at a time, the newest
first, `GAP_SECONDS` apart, and none while the loop is paused. A read that fails, or finding none due, ends the reading
for that wait. It runs in the loop's own process, so nothing reads them outside `canopy loop` (D042), and it never ends
the loop: what it raises is logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import pause, run_models
from canopy.core.vocab import ModelsRead

if TYPE_CHECKING:
    from collections.abc import Callable

    from canopy.core.context import Context
    from canopy.infra import logs

#: How long after one read ends the next may start: each starts the runtime, a few seconds of the operator's machine.
GAP_SECONDS = 10.0


@dataclass
class Backlog:
    """The runs' sessions a wait after a tick reads: one a step, `GAP_SECONDS` apart, till none is due or one fails."""

    clock: Callable[[], float]
    log: logs.TickAdapter
    #: When the last read ended, on `clock`; None before the first.
    last: float | None = None
    #: Whether this wait reads no more: none was due, or a read failed.
    done: bool = False

    def ticked(self) -> None:
        """Note that a tick has ended: the wait after it reads again, whatever ended the reading in the wait before."""
        self.done = False

    def step(self, ctx: Context) -> ModelsRead | None:
        """Read the session of the run due first, unless this wait reads no more, one was read too recently, or paused.

        Returns:
            How the read ended; None when none was made.
        """
        if self.done or (self.last is not None and self.clock() - self.last < GAP_SECONDS):
            return None
        if pause.paused(ctx.conn) is not None:
            return None
        status: ModelsRead | None = None
        try:
            for run in run_models.due(ctx.conn, limit=1):
                status = run_models.read(ctx, run, self.log)
        except Exception as e:
            self.log.exception("reading which models served a run raised", extra={"error": str(e)})
            status = ModelsRead.FAILED
        self.last = self.clock()
        # A failed read ends the reading for this wait, since the next would likely fail the same way.
        self.done = status is None or status is ModelsRead.FAILED
        return status
