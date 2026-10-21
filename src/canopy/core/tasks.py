"""One-off tasks (DESIGN §36): the operator's submissions, each one's runs, and the stop that ends them.

Only the operator's channels write a task, and every write here refuses inside a tick or any agent's run (`inside_run`,
TRUST_MODEL T1): the submission is what authorizes a task's run, and its text is the operator's instruction. The
overseer never reads a task. The tick starts a queued one before the overseer runs (`runs/tasks.py`), and `_task`
records how its run ended (`runs/task_run.py`). A task's runs write nothing about any ticket: their rows name the task.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import conversation, db, pools, records, sql
from canopy.core.conversation import Refused
from canopy.core.vocab import RunStatus

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.vocab import PoolKind
    from canopy.core.workspace import Workspace

#: The most a task's text holds, as an operator message does.
MAX_TEXT = conversation.MAX_OPERATOR
#: A tracker project's key, as a ticket key's part before its last `-` spells it (DESIGN §18).
PROJECT_RE = conversation.KEY_RE
MAX_PROJECT = 100
#: What a task's slot is leased as, after `canopy:` (DESIGN §18): `canopy:task:<id>`, which no ticket key can be.
HOLDER_KEY = "task:"
#: The branch of task N is `<branch_prefix>task/N`: a ticket key has no `/`, so no ticket's branch takes this shape.
BRANCH_PART = "task/"


@dataclass(frozen=True)
class Stopped:
    """What `stop` did: whether the task was already stopped, whether it was still queued, and its running run."""

    already: bool
    #: It had not started: the tick that would have started it starts nothing for it now.
    dropped: bool
    running: records.TaskRun | None


def submit(
    conn: sqlite3.Connection,
    workspace: Workspace,
    text: str,
    *,
    repo: str | None,
    project: str | None,
    channel: str,
) -> records.Task:
    """Record the operator's task, to run in repository `repo`, queued for the next tick to start (DESIGN §36).

    `repo` may be None only in a workspace of one repository. `project` names the tracker project the task's tickets
    may go in; None for none.

    Returns:
        The task, as recorded.

    Raises:
        Refused: `inside_run` inside a tick or a run, `bad_body` for an empty text or one over `MAX_TEXT` characters,
            `unknown_repo` for a repository the map does not name, or none named in a workspace of several, and
            `bad_project` for a project that is not a plain key.
        DatabaseError: the row was not recorded, which nothing but a broken journal does.
    """
    conversation.check_operator()
    body = text.strip()
    if not body:
        raise Refused("bad_body", "the task's text is empty")
    if len(body) > MAX_TEXT:
        raise Refused("bad_body", f"the task's text is {len(body)} characters; the most is {MAX_TEXT}")
    name = _repository(workspace, repo)
    if project is not None and not (len(project) <= MAX_PROJECT and PROJECT_RE.fullmatch(project)):
        raise Refused("bad_project", f"--project must match {PROJECT_RE.pattern}, at most {MAX_PROJECT} characters")
    insert = sql.insert("tasks", text=body, repo=name, project=project, channel=channel, submitted_at=db.now())
    task_id = sql.execute(conn, insert).lastrowid
    found = get(conn, int(task_id or 0))
    if found is None:
        raise sqlite3.DatabaseError("the task's row was not recorded")
    return found


def get(conn: sqlite3.Connection, task_id: int) -> records.Task | None:
    """Return task `task_id`, or None if there is none."""
    return records.fetch_one(conn, records.Task, sql.select("*").from_("tasks").where("id = ?", task_id))


def every(conn: sqlite3.Connection) -> list[records.Task]:
    """Return every task, the newest first: none is ever deleted (DESIGN §36)."""
    return records.fetch_all(conn, records.Task, sql.select("*").from_("tasks").order_by("id DESC"))


def queued(conn: sqlite3.Connection) -> list[records.Task]:
    """Return the tasks waiting for a tick to start them, the oldest first: not stopped, and never run.

    Returns:
        The tasks, by when they were submitted.
    """
    never_run = "NOT EXISTS (SELECT 1 FROM task_runs r WHERE r.task_id = tasks.id)"
    query = sql.select("*").from_("tasks").where("stopped_at IS NULL").where(never_run).order_by("id")
    return records.fetch_all(conn, records.Task, query)


def moved_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether the operator submitted or stopped a task after `since`, a time the journal wrote (§6, §36).

    Returns:
        True if one did: it ends the loop's wait, so a submission starts at the next tick, not the one after the wait.
    """
    query = sql.select("1").from_("tasks").where("submitted_at > ? OR stopped_at > ?", since, since).limit(1)
    return sql.execute(conn, query).fetchone() is not None


def runs_of(conn: sqlite3.Connection, task_id: int) -> list[records.TaskRun]:
    """Return task `task_id`'s runs, the oldest first."""
    query = sql.select("*").from_("task_runs").where("task_id = ?", task_id).order_by("id")
    return records.fetch_all(conn, records.TaskRun, query)


def latest_runs(conn: sqlite3.Connection) -> dict[int, records.TaskRun]:
    """Return each task's newest run, by the task's id; a task never run has none."""
    newest = sql.select("max(id)").from_("task_runs").group_by("task_id")
    query = sql.select("*").from_("task_runs").where("id IN ({})", newest)
    return {r.task_id: r for r in records.fetch_all(conn, records.TaskRun, query)}


def get_run(conn: sqlite3.Connection, run_id: int) -> records.TaskRun | None:
    """Return task run `run_id`, or None if there is none."""
    return records.fetch_one(conn, records.TaskRun, sql.select("*").from_("task_runs").where("id = ?", run_id))


def running(conn: sqlite3.Connection) -> list[records.TaskRun]:
    """Return the task runs running now, the oldest first."""
    query = sql.select("*").from_("task_runs").where("status = 'running'").order_by("started_at, id")
    return records.fetch_all(conn, records.TaskRun, query)


def stop(conn: sqlite3.Connection, task_id: int) -> Stopped:
    """Mark task `task_id` stopped, in one transaction with reading its running run (DESIGN §36).

    A stopped task is never started again; one still queued is dropped. Its runs, and the task, stay to read. The tick
    reads `queued` and inserts its run in one transaction too, so whichever commits first wins.

    Returns:
        Whether it was already stopped, whether it was still queued, and its run still running, if one is.

    Raises:
        Refused: `inside_run` inside a tick or a run, and `unknown` for a task canopy has no record of.
    """
    conversation.check_operator()
    with db.transaction(conn):
        task = get(conn, task_id)
        if task is None:
            raise Refused("unknown", f"canopy has no task:{task_id}")
        runs = runs_of(conn, task_id)
        if task.stopped_at is None:
            sql.execute(conn, sql.update("tasks").set(stopped_at=db.now()).where("id = ?", task_id))
    return Stopped(
        already=task.stopped_at is not None,
        dropped=task.stopped_at is None and not runs,
        running=next((r for r in runs if r.status is RunStatus.RUNNING), None),
    )


def branch(prefix: str, task_id: int) -> str:
    """Return task `task_id`'s branch, `<prefix>task/<id>`: every run of the task works on it (DESIGN §36)."""
    return f"{prefix}{BRANCH_PART}{task_id}"


def holder(task_id: int) -> str:
    """Return the lease holder of task `task_id`'s slot, `canopy:task:<id>`."""
    return pools.holder_for(f"{HOLDER_KEY}{task_id}")


def held_by_task(lease_holder: str) -> bool:
    """Whether `lease_holder` is a task's, which no ticket's work is: the overseer is told only that it is busy.

    Returns:
        True for `canopy:task:<anything>`.
    """
    return lease_holder.startswith(pools.holder_for(HOLDER_KEY))


def insert_run(
    conn: sqlite3.Connection,
    *,
    task: records.Task,
    tick_id: int,
    branch_name: str,
    lease: pools.Lease,
    pool: PoolKind,
    logs_dir: Path,
) -> int | None:
    """Record task `task`'s run in the slot `lease` holds, logging to `<logs_dir>/<id>.log`, if the task still waits.

    Checked in the transaction that inserts it, so a `stop` that commits first starts nothing, and so does a run
    another tick already started.

    Returns:
        The new run's id, or None when the task was stopped or has a run.
    """
    with db.transaction(conn):
        if all(t.id != task.id for t in queued(conn)):
            return None
        run = sql.insert(
            "task_runs",
            task_id=task.id,
            tick_id=tick_id,
            branch=branch_name,
            repo=task.repo,
            slot_path=str(lease.path),
            lease_id=lease.lease_id,
            lease_holder=lease.lease_holder,
            base_branch=lease.base_branch,
            pool=str(pool),
            started_at=db.now(),
            log_path="",
        )
        run_id = int(sql.execute(conn, run).lastrowid or 0)
        log_path = str(logs_dir / f"{run_id}.log")
        sql.execute(conn, sql.update("task_runs").set(log_path=log_path).where("id = ?", run_id))
    return run_id


def set_git_link(conn: sqlite3.Connection, run_id: int, link: bytes | None) -> None:
    """Record what the slot's `.git` file held when task run `run_id` started, before any git step (DESIGN §8)."""
    sql.execute(conn, sql.update("task_runs").set(git_link=link).where("id = ?", run_id))


def close_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: RunStatus,
    result_json: str,
    *,
    head: str | None,
) -> bool:
    """Close task run `run_id` as `status`, with its result and the head its branch was at on origin.

    Returns:
        True if this call closed it; False when it was already closed, by reconcile or a stop.
    """
    close = (
        sql.update("task_runs")
        .set(ended_at=db.now(), status=str(status), result_json=result_json, head=head)
        .where("id = ? AND status = 'running'", run_id)
    )
    return sql.execute(conn, close).rowcount == 1


def _repository(workspace: Workspace, repo: str | None) -> str:
    """The repository a task runs in: `repo`, or the workspace's only one.

    Returns:
        Its name as the map spells it.

    Raises:
        Refused: (`unknown_repo`) `repo` is not in the map, or is None in a workspace of several.
    """
    names = ", ".join(r.name for r in workspace.repos) or "none yet"
    if repo is None:
        if len(workspace.repos) == 1:
            return workspace.repos[0].name
        raise Refused("unknown_repo", f"--repo is required: name the repository the task runs in ({names})")
    found = workspace.repo(repo)
    if found is None:
        raise Refused("unknown_repo", f"{repo!r} is not a repository in this workspace ({names})")
    return found.name
