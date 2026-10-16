"""Chore reconcile (DESIGN §6 step 3, §19): close chore runs whose `_chore` is gone, as worker runs are closed."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import dead_runs, outbox
from canopy.core.vocab import ChoreRunStatus

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.infra import logs


def run(ctx: Context, log: logs.TickAdapter) -> list[int]:
    """Mark running chore runs whose `_chore` is gone `crashed`. Returns their ids.

    The agent leads its own process group, so whatever is left of it is killed first.

    Returns:
        The ids of the chore runs this call closed. A run another process closed first is not among them.
    """
    closed: list[int] = []
    for row in dead_runs.find(ctx.conn, "chore_runs"):
        fields = {"chore_run_id": row["id"], "chore": row["chore"], "pid": row["pid"]}
        dead_runs.kill_agent("chore_runs", row, log, fields)
        note = json.dumps({"harness": "the chore process is gone"})
        ended = outbox.chore_ended(ctx.config, row, ChoreRunStatus.CRASHED, note)
        if dead_runs.crash(ctx.conn, "chore_runs", row, note, event=ended):
            closed.append(int(row["id"]))
            log.warning("chore process is gone; chore run marked crashed", extra=fields)
    return closed
