"""One-off tasks (DESIGN §36): the operator's submissions, each one's runs, its conversation, and the stop that ends it.

Only the operator's channels write a task, and every write here refuses inside a tick or any agent's run (`inside_run`,
TRUST_MODEL T1): the submission, and each reply (`conversation.reply`), is what authorizes a task's run, and its text
the operator's instruction. The overseer never reads a task. The tick starts a queued one before the overseer runs
(`runs/task_starts.py`), and `_task` records how its run ended (`runs/task_run.py`), with its report and question as
messages about the task. A run's report file is kept beside the journal, `<state_dir>/tasks/<id>/<run>.md`, as a plan
is (§25), and the tickets it filed are recorded against the task (`task_tickets.py`). A task's runs write nothing about
any ticket of canopy's: their rows name the task.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from canopy.core import contract, conversation, db, outbox, plans, pools, records, sql
from canopy.core.conversation import Refused
from canopy.core.vocab import RunStatus
from canopy.runs import task_tickets

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from canopy.core.config import Config
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
#: A task's report: a markdown file its worker writes at the slot's root, which git there ignores (DESIGN §36).
REPORT = ".canopy-task-report.md"
#: Where reports are kept, `<state_dir>/tasks/<id>/<run>.md`, readable only by the operator, as plans are (§25).
REPORTS_DIR = "tasks"
#: The longest PR URL a task's result may name and have shown.
MAX_PR_URL = 500

#: Where a task stands: stopped, queued for a run a tick will start, waiting on the operator's reply to its latest
#: run's question, or its latest run's status.
type Standing = Literal["stopped", "queued", "awaiting_reply"] | RunStatus


@dataclass(frozen=True)
class Stopped:
    """What `stop` did: whether the task was already stopped, whether it was still queued, and its running run."""

    already: bool
    #: It waited for a run, its first or one a reply asked for: the tick that would have started it starts nothing now.
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
    return records.select(records.Task).where("id = ?", task_id).one(conn)


def every(conn: sqlite3.Connection) -> list[records.Task]:
    """Return every task, the newest first: none is ever deleted (DESIGN §36)."""
    return records.select(records.Task).order_by("id DESC").all(conn)


def queued(conn: sqlite3.Connection) -> list[records.Task]:
    """Return the tasks waiting for a tick to start a run, the oldest first (DESIGN §36).

    A task waits when it is not stopped and has no run running, and has never run, or the operator replied to it
    after its latest run started: each run follows an operator's word, so a task never retries on its own.

    Returns:
        The tasks, by when they were submitted.
    """
    never_run = sql.frag("NOT EXISTS (SELECT 1 FROM task_runs r WHERE r.task_id = tasks.id)")
    # Past the newest message the latest run's prompt carried: a reply no run has taken yet.
    replied = sql.frag(
        "EXISTS (SELECT 1 FROM messages m WHERE m.subject_kind = ? AND m.subject_id = CAST(tasks.id AS TEXT)"
        " AND m.source = 'operator' AND m.id > coalesce("
        "(SELECT r.message_id FROM task_runs r WHERE r.task_id = tasks.id ORDER BY r.id DESC LIMIT 1), 0))",
        conversation.TASK,
    )
    query = (
        records.select(records.Task)
        .where("stopped_at IS NULL")
        .where("NOT EXISTS (SELECT 1 FROM task_runs r WHERE r.task_id = tasks.id AND r.status = 'running')")
        .where("{} OR {}", never_run, replied)
        .order_by("id")
    )
    return query.all(conn)


def standing(
    task: records.Task,
    latest: records.TaskRun | None,
    *,
    queued: bool,
    awaiting: bool = False,
) -> Standing:
    """Where `task` stands, given its latest run, `latest`: `stopped`, `queued`, `awaiting_reply`, or that run's status.

    `queued` says whether a tick would start a run of it now: its first, or the one a reply asked for. `awaiting` says
    whether its latest question waits on a reply (`awaiting`); left False, a task waiting on one stands as its blocked
    run does, as `canopy task list` words it.

    Returns:
        `stopped` once stopped and no run of it runs, `queued`, `awaiting_reply` when `awaiting`, else its latest run's.
    """
    if task.stopped_at is not None and (latest is None or latest.status is not RunStatus.RUNNING):
        return "stopped"
    if latest is None or queued:
        return "queued"
    if awaiting and latest.status is not RunStatus.RUNNING:
        return "awaiting_reply"
    return latest.status


def moved_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether the operator submitted, replied to, or stopped a task after `since`, a time the journal wrote (§6, §36).

    Returns:
        True if one did: it ends the loop's wait, so the run it asks for starts at the next tick, not the one after
        the wait.
    """
    query = sql.select("1").from_("tasks").where("submitted_at > ? OR stopped_at > ?", since, since).limit(1)
    replied = (
        sql.select("1")
        .from_("messages")
        .where("subject_kind = ? AND source = 'operator' AND at > ?", conversation.TASK, since)
        .limit(1)
    )
    return sql.execute(conn, query).fetchone() is not None or sql.execute(conn, replied).fetchone() is not None


@dataclass(frozen=True)
class Awaiting:
    """A task whose latest run asked the operator a question that no reply has followed (DESIGN §36)."""

    task_id: int
    #: The question, a message of the run's.
    message_id: int
    run_id: int | None
    #: When the run asked it.
    at: str


def awaiting(conn: sqlite3.Connection) -> list[Awaiting]:
    """Return every task not stopped whose latest question waits on a reply, by id: each raises `awaiting_reply`.

    Returns:
        The tasks, with the question each waits on, never its text: the item names the task.
    """
    # Each task's latest question, as `conversation.task_question` reads one, for every task at once.
    query = (
        records.select(records.Message, "m")
        .join("tasks t ON m.subject_id = CAST(t.id AS TEXT)")
        .where("m.subject_kind = ? AND m.kind = 'question' AND t.stopped_at IS NULL", conversation.TASK)
        .where(
            "m.id = (SELECT max(q.id) FROM messages q"
            " WHERE q.subject_kind = m.subject_kind AND q.subject_id = m.subject_id AND q.kind = 'question')",
        )
        .where(
            "NOT EXISTS (SELECT 1 FROM messages o WHERE o.subject_kind = m.subject_kind"
            " AND o.subject_id = m.subject_id AND o.source = 'operator' AND o.id > m.id)",
        )
        .order_by("t.id")
    )
    return [Awaiting(int(m.subject_id), m.id, m.task_run_id, m.at) for m in query.all(conn)]


def messages_of(conn: sqlite3.Connection, task_id: int) -> list[records.Message]:
    """Return task `task_id`'s conversation, oldest first: its runs' reports and questions, and the operator's replies.

    Returns:
        The messages, by id.
    """
    query = (
        records.select(records.Message)
        .where("subject_kind = ? AND subject_id = ?", conversation.TASK, str(task_id))
        .order_by("id")
    )
    return query.all(conn)


def newest_messages(conn: sqlite3.Connection) -> dict[int, int]:
    """Return the id of each task's newest message, by the task's id; a task with none is not listed.

    A reply to a task whose run still runs queues nothing yet, so it changes no summary: this is how a reader of the
    tasks list knows a conversation moved all the same.

    Returns:
        The ids.
    """
    query = (
        sql.select("subject_id, max(id)")
        .from_("messages")
        .where("subject_kind = ?", conversation.TASK)
        .group_by("subject_id")
    )
    return {int(r[0]): int(r[1]) for r in sql.execute(conn, query)}


def runs_of(conn: sqlite3.Connection, task_id: int) -> list[records.TaskRun]:
    """Return task `task_id`'s runs, the oldest first."""
    query = records.select(records.TaskRun).where("task_id = ?", task_id).order_by("id")
    return query.all(conn)


def latest_runs(conn: sqlite3.Connection) -> dict[int, records.TaskRun]:
    """Return each task's newest run, by the task's id; a task never run has none."""
    newest = sql.select("max(id)").from_("task_runs").group_by("task_id")
    query = records.select(records.TaskRun).where("id IN ({})", newest)
    return {r.task_id: r for r in query.all(conn)}


def get_run(conn: sqlite3.Connection, run_id: int) -> records.TaskRun | None:
    """Return task run `run_id`, or None if there is none."""
    return records.select(records.TaskRun).where("id = ?", run_id).one(conn)


def running(conn: sqlite3.Connection) -> list[records.TaskRun]:
    """Return the task runs running now, the oldest first."""
    query = records.select(records.TaskRun).where("status = 'running'").order_by("started_at, id")
    return query.all(conn)


def stop(conn: sqlite3.Connection, task_id: int) -> Stopped:
    """Mark task `task_id` stopped, in one transaction with reading its running run (DESIGN §36).

    A stopped task is never started again; one still queued, new or replied to, is dropped. Its runs, and the task,
    stay to read. The tick
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
        waiting = any(t.id == task_id for t in queued(conn))
        if task.stopped_at is None:
            sql.execute(conn, sql.update("tasks").set(stopped_at=db.now()).where("id = ?", task_id))
    return Stopped(
        already=task.stopped_at is not None,
        dropped=waiting,
        running=next((r for r in runs if r.status is RunStatus.RUNNING), None),
    )


def branch(prefix: str, task_id: int) -> str:
    """Return task `task_id`'s branch, `<prefix>task/<id>`: every run of the task works on it (DESIGN §36)."""
    return f"{prefix}{BRANCH_PART}{task_id}"


def prs(result: Mapping[str, object]) -> list[str]:
    """The PRs a task run's stored result names, each a plain printable https:// URL; anything else is left out.

    Returns:
        The URLs, in the order the result lists them.
    """
    found = result.get("prs")
    listed = cast("list[object]", found) if isinstance(found, list) else list[object]()
    return [u for u in listed if isinstance(u, str) and contract.plain_url(u, MAX_PR_URL) and u.isprintable()]


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
        newest = (
            sql.select("max(id)")
            .from_("messages")
            .where("subject_kind = ? AND subject_id = ?", conversation.TASK, str(task.id))
        )
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
            message_id=sql.execute(conn, newest).fetchone()[0],
        )
        run_id = int(sql.execute(conn, run).lastrowid or 0)
        log_path = str(logs_dir / f"{run_id}.log")
        sql.execute(conn, sql.update("task_runs").set(log_path=log_path).where("id = ?", run_id))
    return run_id


def set_git_link(conn: sqlite3.Connection, run_id: int, link: bytes | None) -> None:
    """Record what the slot's `.git` file held when task run `run_id` started, before any git step (DESIGN §8)."""
    sql.execute(conn, sql.update("task_runs").set(git_link=link).where("id = ?", run_id))


def report_path(state_dir: Path, task_id: int, run_id: int) -> Path:
    """Where the report task run `run_id` left is kept. Built from the ids, never read from a row.

    Returns:
        `<state_dir>/tasks/<task_id>/<run_id>.md`. The file may not exist.
    """
    return state_dir / REPORTS_DIR / str(task_id) / plans.file_name(run_id)


def keep_report(state_dir: Path, task_id: int, run_id: int, text: str) -> plans.Written:
    """Write the report task run `run_id` left to its file, once, readable only by the operator (DESIGN §36).

    Returns:
        The file's hash and size, for its run's row.

    Raises:
        PlanFileError: `tasks/` or the task's directory is not the operator's own, or the file's name is taken.
    """
    return plans.write_new(state_dir / REPORTS_DIR, str(task_id), plans.file_name(run_id), text, what="report")


def latest_report(conn: sqlite3.Connection, state_dir: Path, task_id: int) -> tuple[records.TaskRun, str] | None:
    """Return the newest report a run of task `task_id` left, as its file stands, with the run: the next run's copy.

    Only a report the journal records is read, never through a link, and one whose file is no longer a report is
    passed over for an older one.

    Returns:
        The run and the report's text, or None when no run left one that still reads as one.
    """
    query = (
        records.select(records.TaskRun).where("task_id = ? AND report_sha256 IS NOT NULL", task_id).order_by("id DESC")
    )
    for run in query.all(conn):
        reading = plans.read(report_path(state_dir, task_id, run.id))
        if reading.text is not None:
            return run, reading.text
    return None


def set_report(conn: sqlite3.Connection, run_id: int, sha256: str) -> None:
    """Record the hash of the report task run `run_id` left, as `_task` kept it in the state directory (DESIGN §36)."""
    sql.execute(conn, sql.update("task_runs").set(report_sha256=sha256).where("id = ?", run_id))


def close_run(
    conn: sqlite3.Connection,
    config: Config,
    run_id: int,
    status: RunStatus,
    result_json: str,
    *,
    head: str | None,
    tickets: Iterable[str] = (),
) -> bool:
    """Close task run `run_id` as `status`, with its result and the head its branch was at on origin (DESIGN §36).

    In the same transaction it records the run's messages about its task, its report and a `blocked` run's question,
    each naming the run; `tickets`, the keys `task_tickets.check` passed, against the task; and its `task.ended` event,
    naming the keys it recorded, when a sink takes `tasks`.

    Returns:
        True if this call closed it; False when it was already closed, by reconcile or a stop: nothing is recorded.

    Raises:
        DatabaseError: the run's row is gone, which nothing but a broken journal does.
    """
    close = (
        sql.update("task_runs")
        .set(ended_at=db.now(), status=str(status), result_json=result_json, head=head)
        .where("id = ? AND status = 'running'", run_id)
    )
    with db.transaction(conn):
        if sql.execute(conn, close).rowcount != 1:
            return False
        run = get_run(conn, run_id)
        if run is None:
            raise sqlite3.DatabaseError(f"task run {run_id} vanished as it closed")
        last: int | None = None
        for kind, body in conversation.run_messages(status, result_json):
            last = db.insert_message(
                conn,
                conversation.TASK,
                str(run.task_id),
                source="worker",
                kind=kind,
                channel="run",
                body=body,
                task_run_id=run_id,
            )
        recorded = task_tickets.record(conn, run.task_id, run_id, tickets)
        event = outbox.task_ended(config, run, status, result_json, head=head, message=last, tickets=recorded)
        if event is not None:
            db.record_event(conn, event)
    return True


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
