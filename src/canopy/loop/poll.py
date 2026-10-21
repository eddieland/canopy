"""The loop's poll (DESIGN §6, §30): the connectors run between ticks, apart from the overseer's pace.

A tick is the overseer's turn, paced by `loop.*`; a poll only reads the world into the journal, every
`connect.every_minutes`, so an operator who ticks rarely still has observations as fresh as they ask for. A poll runs
the sources a tick runs, under the tick lock, so it never overlaps a tick or a `canopy tick` run by hand, and checks the
drafts the `vcs` run read (DESIGN §29). It records its runs with no tick and raises nothing: the attention list is a
tick's, and the next tick runs every source again before it records its items.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.infra import lock
from canopy.loop import connectors
from canopy.runs import drafted

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy.core import observe
    from canopy.core.context import Context
    from canopy.infra import logs


def run(ctx: Context, log: logs.TickAdapter) -> Mapping[str, observe.Observed] | None:
    """Run the connectors once outside a tick, and check the drafts the `vcs` run read whole.

    Returns:
        How each source's run ended, by its name; None when a tick held the lock, so this poll is skipped.
    """
    try:
        with lock.hold(ctx.lock_path):
            ran = connectors.run(ctx, None, log)
            drafted.reconcile(ctx, ran.read, log)
    except lock.LockBusyError:
        log.info("poll skipped: a tick holds the lock")
        return None
    return ran.observed
