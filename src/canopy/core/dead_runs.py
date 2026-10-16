"""What every kind of run's reconcile shares (DESIGN §6 step 3): runs whose own process is gone, found and ended.

A run's own process is `_run`, `_chore`, or `_review`, and it is alive while it holds its lifelock (DESIGN §6). The
agent it starts leads its own process group, so it can outlive that process; it is killed before the run is closed and
whatever it held goes back. Each kind's reconcile then closes the run its own way: a worker run with its messages and
slots, a review with its slot, a chore with nothing more.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.core.vocab import AnyRunStatus, ChoreRunStatus, ReviewRunStatus, RunStatus
from canopy.infra import procs

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.db import Event, RunTable
    from canopy.infra import logs

# Each run table's `crashed`: what a run whose process is gone is closed as.
CRASHED: Mapping[RunTable, AnyRunStatus] = {
    "runs": RunStatus.CRASHED,
    "chore_runs": ChoreRunStatus.CRASHED,
    "review_runs": ReviewRunStatus.CRASHED,
}


def find(conn: sqlite3.Connection, table: RunTable) -> list[sqlite3.Row]:
    """Return `table`'s running runs whose own process is gone, oldest first.

    Returns:
        The rows, as `db.running_runs` reads them.
    """
    return [r for r in db.running_runs(conn, table) if not procs.running(Path(r["log_path"]), r["pid"])]


def kill_agent(table: RunTable, row: sqlite3.Row, log: logs.TickAdapter, fields: Mapping[str, object]) -> None:
    """Kill whatever is left of the agent run `row` in `table` started, logged with `fields` if there was any."""
    pid = row[db.AGENT_PID[table]]
    if pid is not None and procs.kill_group(int(pid)):
        log.warning("killed the agent a gone process left behind", extra={**fields, "agent_pid": pid})


def crash(conn: sqlite3.Connection, table: RunTable, row: sqlite3.Row, note: str, *, event: Event | None) -> bool:
    """Close run `row` in `table` `crashed` with `note`, its result, and `event`; then remove its lifelock's file.

    Returns:
        True if this call closed the run. False if another process closed it first, which removes the file itself.
    """
    if not db.finish_run(conn, table, int(row["id"]), CRASHED[table], note, event=event):
        return False
    procs.drop_lifelock(Path(row["log_path"]))
    return True
