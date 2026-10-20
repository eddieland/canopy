"""Which models served each agent run, read a few runs at a time after each tick (DESIGN §13, Each agent's model).

No event a run prints names the model, so a run's session is read from the runtime's own record once the run has
ended. Each live tick reads at most `PER_TICK` after it closes, never-read runs the newest first, so a run that just
ended is attributed by the next tick and the journal's history fills in over the ticks after it; nothing reads them
between ticks (D042). A read never fails the tick: one that fails is recorded so, and read again later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import run_models
from canopy.core.vocab import ModelsRead
from canopy.runtime import session_models

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.infra import logs

#: How many runs' sessions one tick reads: each read starts the runtime once, so a few seconds each.
PER_TICK = 5


def attribute(ctx: Context, log: logs.TickAdapter) -> int:
    """Read the sessions of up to `PER_TICK` runs that are due, and record which models served each.

    A read that fails ends the batch, since the next would likely fail the same way, and is read again later.

    Returns:
        How many runs were read, whatever each read found.
    """
    read = 0
    for run in run_models.due(ctx.conn, limit=PER_TICK):
        found = session_models.read(ctx.runner, cwd=ctx.repo_root, session_id=run.session_id)
        status = ModelsRead(found.outcome)
        run_models.record(ctx.conn, run, status, found.models, error=found.error)
        read += 1
        if status is ModelsRead.FAILED:
            log.warning(
                "could not read which models served a run",
                extra={"run_table": run.run_table, "run_id": run.run_id, "error": found.error},
            )
            break
    if read:
        log.info("read which models served runs", extra={"runs": read})
    return read
