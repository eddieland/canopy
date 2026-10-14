"""Review reconcile (DESIGN §6 step 3, §21): close review runs whose `_review` is gone, as worker runs are closed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import db, outbox
from canopy.infra import procs
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
    for row in db.running_review_runs(ctx.conn):
        if procs.running(Path(row["log_path"]), row["pid"]):
            continue
        fields = {"review_run_id": row["id"], "pr": row["pr_url"], "pid": row["pid"]}
        if row["agent_pid"] is not None and procs.kill_group(int(row["agent_pid"])):
            log.warning("killed the reviewer `_review` left behind", extra={**fields, "agent_pid": row["agent_pid"]})
        execute.clean_up(ctx, row, log)
        note = json.dumps({"harness": "the review process is gone"})
        ended = outbox.review_ended(ctx.config, row, "crashed", note)
        if db.finish_review_run(ctx.conn, int(row["id"]), "crashed", note, event=ended):
            procs.drop_lifelock(Path(row["log_path"]))
            closed.append(int(row["id"]))
            log.warning("review process is gone; review run marked crashed", extra=fields)
    return closed
