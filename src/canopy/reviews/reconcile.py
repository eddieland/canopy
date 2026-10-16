"""Review reconcile (DESIGN §6 step 3, §21): close review runs whose `_review` is gone, as worker runs are closed."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import db, dead_runs, outbox
from canopy.core.vocab import ReviewRunStatus
from canopy.reviews import execute

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.infra import logs


def run(ctx: Context, log: logs.TickAdapter) -> list[int]:
    """Mark running review runs whose `_review` is gone `crashed`, and return their slots.

    The reviewer leads its own process group, so whatever is left of it is killed before its slot goes back.

    Returns:
        The ids of the review runs this call closed. A run another process closed first is not among them.
    """
    closed: list[int] = []
    for row in dead_runs.find(ctx.conn, "review_runs"):
        # Read again as a typed row, for what returns its slot and builds its event.
        run = db.get_review_run(ctx.conn, int(row["id"]))
        if run is None:
            continue
        fields = {"review_run_id": run.id, "pr": run.pr_url, "pid": run.pid}
        dead_runs.kill_agent("review_runs", row, log, fields)
        execute.clean_up(ctx, run, log)
        note = json.dumps({"harness": "the review process is gone"})
        ended = outbox.review_ended(ctx.config, run, ReviewRunStatus.CRASHED, note)
        if dead_runs.crash(ctx.conn, "review_runs", row, note, event=ended):
            closed.append(run.id)
            log.warning("review process is gone; review run marked crashed", extra=fields)
    return closed
