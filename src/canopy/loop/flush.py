"""The loop's delivery between ticks (DESIGN §6, §20): what a sink takes reaches it without waiting for a tick.

A tick is the overseer's turn, and its pace is set by what a model run costs; a delivery costs none, only each sink's
command run over rows the journal already holds. So during each wait the loop delivers every `EVERY_SECONDS`, as the
end of a tick does (`attention.publish`): each sink is given what it has not heard, and `attention.md` is rewritten
when one was sent something. It runs under the tick lock, so it never overlaps a tick or a `canopy tick` run by hand,
and it starts no overseer.

A sink whose last delivery failed is left for the next tick, so one that hangs costs a tick its timeout, never every
step of the wait.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.infra import lock
from canopy.loop import attention

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.infra import logs

#: How long the loop's wait leaves between two deliveries, so an event waits for its sink under a minute.
EVERY_SECONDS = 30.0


def run(ctx: Context, log: logs.TickAdapter, *, ui: str | None = None) -> None:
    """Deliver once outside a tick, to the sinks that are not failing. Never raises: the loop's wait goes on.

    `ui` is where notifications' links open the web UI, when the loop serves it. With no sink configured there is
    nothing to deliver, and the attention list stays the latest tick's.
    """
    if not ctx.config.notify.all_sinks():
        return
    try:
        with lock.hold(ctx.lock_path):
            attention.publish(ctx, log, ui=ui, between_ticks=True)
    except lock.LockBusyError:
        log.info("delivery skipped: a tick holds the lock")
    except Exception as e:
        log.exception("delivering between ticks raised", extra={"error": str(e)})
