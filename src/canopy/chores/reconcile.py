"""Chore reconcile (DESIGN §6 step 3, §19): close chore runs whose `_chore` is gone, as worker runs are closed."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.infra import procs

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.infra import logs


def run(ctx: Context, log: logs.TickAdapter) -> list[int]:
    """Mark running chore runs whose `_chore` is dead or never recorded `crashed`. Returns their ids.

    The agent leads its own process group, so whatever is left of it is killed first.
    """
    closed: list[int] = []
    for row in db.running_chore_runs(ctx.conn):
        pid = row["pid"]
        if pid is not None and procs.alive(int(pid)):
            continue
        fields = {"chore_run_id": row["id"], "chore": row["chore"], "pid": pid}
        if row["agent_pid"] is not None and procs.kill_group(int(row["agent_pid"])):
            log.warning("killed the chore agent `_chore` left behind", extra={**fields, "agent_pid": row["agent_pid"]})
        note = json.dumps({"harness": "the chore process is gone"})
        if db.finish_chore_run(ctx.conn, int(row["id"]), "crashed", note):
            closed.append(int(row["id"]))
            log.warning("chore process is gone; chore run marked crashed", extra=fields)
    return closed
