"""Which of canopy's running work each process on the machine belongs to, for the system resources page.

A run's own process (`canopy _run`, `_chore`, `_review`, and their kin) claims its run with its pid as it starts
(`db.claim_run`), and records its agent's pid as it starts the agent, so the journal says which process works which
run. The page then ties what keeps the machine busy to the ticket, review, chore, task, or epic it is for, rather than
leaving the operator to read a run's id out of a command line. Only running work is matched: a pid an ended run
recorded may since be another process's. The run's process is tagged, or its agent's where the run's process is gone,
as after the harness lost it; the processes under it are its children, which the page's tree shows under it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import records
from canopy.core.vocab import ChoreRunStatus, ReviewRunStatus, RunStatus
from canopy.serve.schema.host import HostProcesses, ProcessWork

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator


def tagged(conn: sqlite3.Connection, found: HostProcesses) -> HostProcesses:
    """`found` with each process a running run recorded tagged with that run's work.

    Returns:
        `found` itself where no process was read, as off Linux; else a copy whose processes carry their `work`.
    """
    if found.processes is None:
        return found
    pids = {p.pid for p in found.processes}
    by_pid: dict[int, ProcessWork] = {}
    for work, pid, agent in _running(conn):
        at = pid if pid in pids else agent if agent in pids else None
        if at is not None:
            by_pid.setdefault(at, work)
    return found.model_copy(
        update={"processes": [p.model_copy(update={"work": by_pid.get(p.pid)}) for p in found.processes]},
    )


# Each running run of every kind, with the pid its process recorded and its agent's, either None until recorded.
def _running(conn: sqlite3.Connection) -> Iterator[tuple[ProcessWork, int | None, int | None]]:
    for run in records.select(records.Run).where("status = ?", RunStatus.RUNNING).all(conn):
        yield ProcessWork(kind="run", id=run.id, ticket_key=run.ticket_key), run.pid, run.worker_pid
    for review in records.select(records.ReviewRun).where("status = ?", ReviewRunStatus.RUNNING).all(conn):
        work = ProcessWork(kind="review", id=review.id, pr_url=review.pr_url, ticket_key=review.ticket_key)
        yield work, review.pid, review.agent_pid
    for chore in records.select(records.ChoreRun).where("status = ?", ChoreRunStatus.RUNNING).all(conn):
        yield ProcessWork(kind="chore", id=chore.id, chore=chore.chore), chore.pid, chore.agent_pid
    for task in records.select(records.TaskRun).where("status = ?", RunStatus.RUNNING).all(conn):
        yield ProcessWork(kind="task", id=task.id, task_id=task.task_id), task.pid, task.agent_pid
    for epic in records.select(records.EpicRun).where("status = ?", RunStatus.RUNNING).all(conn):
        yield ProcessWork(kind="epic", id=epic.id, epic_id=epic.epic_id), epic.pid, epic.agent_pid
