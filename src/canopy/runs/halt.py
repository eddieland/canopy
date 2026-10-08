"""`canopy stop --now`: end the run working a ticket the operator stopped (DESIGN §22).

`canopy stop` marks the start record stopped first, so no dispatch starts another run. Ending the running one kills its
`_run`, which leads its own process group, and its worker's, then closes the run `stopped` as reconcile closes a run
whose `_run` is gone: its slots returned and its desk removed. `stopped` raises no attention item and counts toward
attempt limits like any ended run.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.infra import procs
from canopy.runs import reconcile

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context
    from canopy.infra import logs

NOTE = "the operator stopped the ticket with `canopy stop --now`"


def end(ctx: Context, run: sqlite3.Row, log: logs.TickAdapter) -> bool:
    """Kill run `run`'s processes and close it `stopped`. Returns False if it had already ended: nothing changes.

    Raises:
        treehouse.TreehouseError: a slot could not be returned; the next tick's reconcile returns it.
    """
    for column in ("pid", "worker_pid"):
        pid = run[column]
        # Never this process's own group: a `_run` claimed in-process, as tests run it, has this pid.
        if pid is not None and int(pid) not in (os.getpid(), os.getpgid(0)):
            procs.kill_group(int(pid))
    current = db.get_run(ctx.conn, int(run["id"]))
    if current is None or current["status"] != "running":
        return False
    reconcile.end_run(ctx, current, "stopped", NOTE, log)
    return True
