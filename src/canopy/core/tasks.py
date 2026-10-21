"""One-off tasks in the journal (DESIGN §36): the operator's submissions, their runs, and what each run reported.

A task is work the operator hands canopy in their own words, about no ticket. Its submission is its authorization, so
only the operator's channels write one (`submit`), as they write a start record (§22), and only they stop one (`stop`).
Each run of it is a row of `task_runs`, apart from the ticket runs in `runs`: it names no ticket, and nothing a task
writes in the journal does. What a run reports, its summary and its question, is a message in the task's conversation
that names the run, written in the transaction that closes it (`close_run`), as a worker run's is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from canopy.core import contract, conversation, db, records, sql
from canopy.core.vocab import TaskRunStatus

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from canopy.core.config import Config
    from canopy.core.workspace import Workspace

#: The subject of a task's conversation, `task:N` (D075).
SUBJECT = conversation.TASK
#: A task's text is the operator's words, bounded as their message is.
MAX_TEXT = conversation.MAX_OPERATOR
#: The longest PR URL a task run's report names.
MAX_PR_URL = 500
#: What a task's runs lease their slot as: `canopy:task:<N>`, a holder no ticket key can name.
HOLDER_KEY = "task:"
#: Where a task's branch sits under `trust.branch_prefix`: `<prefix>task/<N>`, a shape no ticket's branch can take,
#: since a key holds no `/` (DESIGN §8).
BRANCH_DIR = "task/"


def branch_name(prefix: str, task_id: int) -> str:
    """Return the branch task `task_id`'s runs push to: `<branch_prefix>task/<N>`."""
    return f"{prefix}{BRANCH_DIR}{task_id}"


def holder_key(task_id: int) -> str:
    """Return the key a run of task `task_id` leases its slot under, which the pool records as `canopy:task:<N>`."""
    return f"{HOLDER_KEY}{task_id}"


def submit(
    conn: sqlite3.Connection,
    config: Config,
    ws: Workspace,
    text: str,
    *,
    repo: str | None,
    project: str | None,
    channel: str,
) -> records.Task:
    """Record a task the operator submitted: their text, the repository it runs in, and the project its tickets go in.

    `repo` may be left out only when the workspace has one repository.

    Returns:
        The task, queued for the next tick.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs, `bad_body` for empty text or text over
            `MAX_TEXT` characters, `unknown_repo` for a repository the map does not name, or none named in a workspace
            of several, `bad_project` for a project that is not a plain key prefix, and `no_read_tools` when no
            tracker tools are known for the private worker that runs it.
        RuntimeError: the task was not there to read back once written.
    """
    conversation.check_operator()
    body = text.strip()
    if not body:
        raise conversation.Refused("bad_body", "the task's text is empty")
    if len(body) > MAX_TEXT:
        raise conversation.Refused("bad_body", f"the task's text is {len(body)} characters; the most is {MAX_TEXT}")
    named = _repo(ws, repo)
    if project is not None and (len(project) > conversation.MAX_KEY or not conversation.KEY_RE.fullmatch(project)):
        raise conversation.Refused(
            "bad_project",
            f"--project must match {conversation.KEY_RE.pattern}, as a ticket key's prefix does",
        )
    if config.tracker.tools() is None:
        raise conversation.Refused(
            "no_read_tools",
            f"no tracker tools are known for provider {config.tracker.provider!r}: set tracker.mcp_server and "
            "tracker.read_tools in your user config, so a task's worker, the private worker, can run",
        )
    insert = sql.insert(
        "tasks",
        text=body,
        repo=named,
        project=project,
        submitted_at=db.now(),
        channel=channel,
    )
    task_id = sql.execute(conn, insert).lastrowid
    task = get(conn, int(task_id or 0))
    if task is None:
        raise RuntimeError("the task just recorded is gone")
    return task


def _repo(ws: Workspace, repo: str | None) -> str:
    """The repository a task runs in: `repo`, or the workspace's one repository when none is named.

    Returns:
        Its name, as the map spells it.

    Raises:
        Refused: (`unknown_repo`) `repo` is not in the map, or none is named in a workspace of several or none.
    """
    names = ", ".join(r.name for r in ws.repos) or "none yet"
    if repo is None:
        if len(ws.repos) != 1:
            raise conversation.Refused(
                "unknown_repo",
                f"--repo is required: name the repository the task runs in ({names})",
            )
        return ws.repos[0].name
    found = ws.repo(repo)
    if found is None:
        raise conversation.Refused("unknown_repo", f"{repo!r} is not a repository in this workspace ({names})")
    return found.name


def get(conn: sqlite3.Connection, task_id: int) -> records.Task | None:
    """Return task `task_id`, or None if there is none."""
    return records.fetch_one(conn, records.Task, sql.select("*").from_("tasks").where("id = ?", task_id))


def every(conn: sqlite3.Connection) -> list[records.Task]:
    """Return every task, the newest first."""
    return records.fetch_all(conn, records.Task, sql.select("*").from_("tasks").order_by("id DESC"))


def queued(conn: sqlite3.Connection) -> list[records.Task]:
    """Return the tasks waiting for a run, the oldest first: not stopped, and never run (DESIGN §36).

    Returns:
        The tasks, by when they were submitted.
    """
    never_run = "NOT EXISTS (SELECT 1 FROM task_runs r WHERE r.task_id = tasks.id)"
    query = sql.select("*").from_("tasks").where("stopped_at IS NULL").where(never_run).order_by("id")
    return records.fetch_all(conn, records.Task, query)


@dataclass(frozen=True)
class Stopped:
    """What `stop` did: whether the task was already stopped, whether it was still queued, and its running run."""

    already: bool
    #: Whether it had never run, so stopping it dropped it before any run started.
    dropped: bool
    running: records.TaskRun | None


def stop(conn: sqlite3.Connection, task_id: int) -> Stopped:
    """Mark a task stopped, in one transaction with reading the run working it (DESIGN §36).

    A stopped task is started by nothing again; a queued one is dropped before it runs. The run working it, if one
    is, is the caller's to end or to let finish, as `canopy stop` does for a ticket's run. Nothing is deleted.

    Returns:
        Whether the task was already stopped, whether it was still queued, and the run working it, if one is.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs, `unknown` when there is no task `task_id`.
    """
    conversation.check_operator()
    with db.transaction(conn):
        task = get(conn, task_id)
        if task is None:
            raise conversation.Refused("unknown", f"there is no task {task_id}")
        if task.stopped_at is None:
            sql.execute(conn, sql.update("tasks").set(stopped_at=db.now()).where("id = ?", task_id))
        runs = runs_of(conn, task_id)
    running = next((r for r in runs if r.status is TaskRunStatus.RUNNING), None)
    return Stopped(already=task.stopped_at is not None, dropped=not runs, running=running)


def moved_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether the operator submitted or stopped a task after `since`, a time the journal wrote: a wake (§6, §36).

    Returns:
        True if one did.
    """
    query = sql.select("1").from_("tasks").where("submitted_at > ? OR stopped_at > ?", since, since).limit(1)
    return sql.execute(conn, query).fetchone() is not None


# A task's runs


def insert_run(
    conn: sqlite3.Connection,
    *,
    task: records.Task,
    tick_id: int,
    branch: str,
    slot: Path,
    lease_id: str,
    lease_holder: str,
    base_branch: str,
    pool: str,
    logs_dir: Path,
) -> records.TaskRun:
    """Record a running run of `task` in the slot it leased, its log in `logs_dir`, named by the run's id.

    Returns:
        The run, `running`, not yet claimed by a process.

    Raises:
        sqlite3.IntegrityError: the task already has a run running.
        RuntimeError: the run was not there to read back once written.
    """
    with db.transaction(conn):
        insert = sql.insert(
            "task_runs",
            task_id=task.id,
            tick_id=tick_id,
            repo=task.repo,
            branch=branch,
            slot_path=str(slot),
            lease_id=lease_id,
            lease_holder=lease_holder,
            base_branch=base_branch,
            pool=pool,
            started_at=db.now(),
            log_path="",
        )
        run_id = int(sql.execute(conn, insert).lastrowid or 0)
        log_path = logs_dir / f"{run_id}.log"
        sql.execute(conn, sql.update("task_runs").set(log_path=str(log_path)).where("id = ?", run_id))
    run = get_run(conn, run_id)
    if run is None:
        raise RuntimeError(f"task run {run_id} vanished")
    return run


def get_run(conn: sqlite3.Connection, run_id: int) -> records.TaskRun | None:
    """Return task run `run_id`, or None if there is none."""
    return records.fetch_one(conn, records.TaskRun, sql.select("*").from_("task_runs").where("id = ?", run_id))


def runs_of(conn: sqlite3.Connection, task_id: int) -> list[records.TaskRun]:
    """Return task `task_id`'s runs, the oldest first."""
    query = sql.select("*").from_("task_runs").where("task_id = ?", task_id).order_by("id")
    return records.fetch_all(conn, records.TaskRun, query)


def running(conn: sqlite3.Connection) -> list[records.TaskRun]:
    """Return every task run still running, the oldest first."""
    query = sql.select("*").from_("task_runs").where("status = ?", TaskRunStatus.RUNNING).order_by("id")
    return records.fetch_all(conn, records.TaskRun, query)


def set_link(conn: sqlite3.Connection, run_id: int, link: bytes | None) -> None:
    """Record what the run's slot's `.git` file held when `_task` started, for a reconcile that tidies it after it."""
    sql.execute(conn, sql.update("task_runs").set(git_link=link).where("id = ?", run_id))


def close_run(
    conn: sqlite3.Connection,
    run: records.TaskRun,
    status: TaskRunStatus,
    result_json: str | None,
    *,
    head: str | None = None,
) -> bool:
    """Close a running task run as `status`, with its pushed `head`, and record its messages, in one transaction.

    Its messages are a report, and for a `blocked` run its question, in the task's conversation, each naming the run.

    Returns:
        True if this closed the run. False if it was already closed: nothing is recorded.
    """
    with db.transaction(conn):
        close = (
            sql.update("task_runs")
            .set(ended_at=db.now(), status=status, result_json=result_json, head=head)
            .where("id = ? AND status = ?", run.id, TaskRunStatus.RUNNING)
        )
        if sql.execute(conn, close).rowcount != 1:
            return False
        for kind, body in run_messages(status, result_json):
            db.insert_message(
                conn,
                SUBJECT,
                str(run.task_id),
                source="worker",
                kind=kind,
                channel="run",
                body=body,
                task_run_id=run.id,
            )
    return True


def run_messages(status: TaskRunStatus, result_json: str | None) -> list[tuple[str, str]]:
    """Return the `(kind, body)` messages a task run that closed as `status` reports.

    That is a report, the worker's summary, or else the harness's note, or else the status, then each PR, a plain
    https:// URL, on a line of its own; and for a `blocked` run its question.
    """
    result = contract.stored_object(result_json)
    summary = _text(result.get("summary")) or _text(result.get("harness")) or f"ended {status}"
    urls = [u for u in _strings(result.get("prs")) if contract.plain_url(u, MAX_PR_URL)]
    found = [("report", "\n".join([summary, *urls]))]
    question = _text(result.get("question"))
    if status is TaskRunStatus.BLOCKED and question:
        found.append(("question", question))
    return found


def messages_of(conn: sqlite3.Connection, task_id: int, limit: int) -> list[records.Message]:
    """Return task `task_id`'s latest `limit` messages, the oldest first."""
    return db.messages_of(conn, SUBJECT, str(task_id), limit)


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast("list[object]", value)
    return [v.strip() for v in items if isinstance(v, str)]


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
