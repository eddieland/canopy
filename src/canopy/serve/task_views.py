"""One-off tasks as the API sends them (DESIGN §36): the tasks list, a task's page, one run with its session and report.

Reads only. A task's text is the operator's, and what its runs wrote is an agent's: control characters are dropped from
both, line breaks kept, and the UI renders them as text. A report is read from its file every time, bounded and never
through a link, as `canopy show task:N` reads it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import contract, conversation, db, plans, sql, task_tickets, tasks
from canopy.core.vocab import RunStatus
from canopy.serve.task_schema import TaskDetail, TaskReport, TaskRun, TaskRunDetail, TaskSummary, TaskTicket
from canopy.serve.transcript_views import removed_after, session_transcript
from canopy.serve.views import lines, message, models_served, new_tokens, run_state, said, shown_path

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from collections.abc import Set as AbstractSet

    from canopy.core import records
    from canopy.core.context import Context
    from canopy.serve.task_schema import TaskStanding
    from canopy.serve.transcript_schema import Transcript

#: A task's latest run's status as where the task stands, every status the same word.
RUN_STANDINGS: Mapping[RunStatus, TaskStanding] = {
    RunStatus.RUNNING: "running",
    RunStatus.DONE: "done",
    RunStatus.BLOCKED: "blocked",
    RunStatus.FAILED: "failed",
    RunStatus.UNKNOWN: "unknown",
    RunStatus.UNPUSHED: "unpushed",
    RunStatus.CRASHED: "crashed",
    RunStatus.TIMEOUT: "timeout",
    RunStatus.STOPPED: "stopped",
}


def tasks_list(ctx: Context) -> list[TaskSummary]:
    """Every task, the newest first, as `canopy task list` lists them: none is ever deleted (DESIGN §36).

    Returns:
        Each task's summary, with where it stands and its newest run.
    """
    latest = tasks.latest_runs(ctx.conn)
    waiting = {t.id for t in tasks.queued(ctx.conn)}
    asked = {a.task_id: a.message_id for a in tasks.awaiting(ctx.conn)}
    counts = _run_counts(ctx.conn)
    return [
        _summary(ctx, t, latest.get(t.id), waiting=waiting, asked=asked, runs=counts.get(t.id, 0))
        for t in tasks.every(ctx.conn)
    ]


def task_detail(ctx: Context, task_id: int) -> TaskDetail | None:
    """Task `task_id`, as `canopy show task:N` prints it, or None if canopy has no such task.

    Returns:
        The task's summary, every run, its conversation, and the tickets its runs filed.
    """
    task = tasks.get(ctx.conn, task_id)
    if task is None:
        return None
    runs = tasks.runs_of(ctx.conn, task_id)
    waiting = {t.id for t in tasks.queued(ctx.conn)}
    asked = {a.task_id: a.message_id for a in tasks.awaiting(ctx.conn)}
    root = ctx.workspace.root
    return TaskDetail(
        task=_summary(ctx, task, runs[-1] if runs else None, waiting=waiting, asked=asked, runs=len(runs)),
        runs=[task_run(r, root) for r in runs],
        messages=[message(m) for m in tasks.messages_of(ctx.conn, task_id)],
        tickets=[_ticket(t) for t in task_tickets.of_task(ctx.conn, task_id)],
    )


def task_run(row: records.TaskRun, root: Path) -> TaskRun:
    """One task run's row, its log's path from the workspace `root`.

    Returns:
        The run as the API sends it.
    """
    return TaskRun(
        id=row.id,
        status=row.status,
        state=run_state(row.status),
        started_at=db.parse_time(row.started_at),
        ended_at=db.parse_time(row.ended_at) if row.ended_at else None,
        branch=row.branch,
        head=row.head,
        summary=said(row),
        prs=tasks.prs(contract.stored_object(row.result_json)),
        reported=row.report_sha256 is not None,
        session_id=row.session_id or None,
        cost_usd=row.cost_usd,
        new_tokens=new_tokens(row),
        peak_context=row.tokens_peak_context,
        log_path=shown_path(row.log_path, root),
    )


def task_run_detail(ctx: Context, task_id: int, run_id: int) -> TaskRunDetail | None:
    """Run `run_id` of task `task_id`, or None if the task has no such run.

    Returns:
        The run, its whole summary and question, the harness's note, the tickets recorded from it, and its models.
    """
    row = _run_of(ctx.conn, task_id, run_id)
    if row is None:
        return None
    stored = contract.stored_object(row.result_json)
    question = lines(str(stored.get("question") or "")) if row.status is RunStatus.BLOCKED else ""
    return TaskRunDetail(
        task_id=task_id,
        run=task_run(row, ctx.workspace.root),
        summary=lines(str(stored.get("summary") or "")) or None,
        question=question or None,
        note=lines(str(stored.get("harness") or "")) or None,
        tickets=[_ticket(t) for t in task_tickets.of_task(ctx.conn, task_id) if t.task_run_id == run_id],
        models=models_served(
            ctx.conn,
            "task_runs",
            run_id,
            ended=row.ended_at is not None,
            session_id=row.session_id or None,
        ),
    )


def task_run_transcript(ctx: Context, task_id: int, run_id: int) -> Transcript | None:
    """A task run's session in its log, or None if task `task_id` has no such run.

    Returns:
        The transcript, its status saying whether the run recorded a session and whether its log could be read.
    """
    row = _run_of(ctx.conn, task_id, run_id)
    if row is None:
        return None
    log = Path(row.log_path)
    return session_transcript(log, row.session_id, removed_after(ctx.conn, log, row.ended_at, "run_files_days"))


def task_report(ctx: Context, task_id: int, run_id: int) -> TaskReport | None:
    """The report run `run_id` of task `task_id` left, as its file stands, or None if the run left none.

    The path is built from the ids, never read from a row, and the file read as a plan's is: bounded, never through a
    link.

    Returns:
        The report's text, or why its file is no longer one, its hash, and whether it was edited since the run.
    """
    row = _run_of(ctx.conn, task_id, run_id)
    if row is None or row.report_sha256 is None:
        return None
    path = tasks.report_path(ctx.state_dir, task_id, run_id)
    reading = plans.read(path)
    return TaskReport(
        task_id=task_id,
        run_id=run_id,
        path=str(path),
        text=conversation.printable(reading.text) if reading.text is not None else None,
        problem=reading.problem,
        sha256=reading.sha256,
        edited=reading.sha256 != row.report_sha256,
    )


def _summary(
    ctx: Context,
    task: records.Task,
    latest: records.TaskRun | None,
    *,
    waiting: AbstractSet[int],
    asked: Mapping[int, int],
    runs: int,
) -> TaskSummary:
    found = tasks.standing(task, latest, queued=task.id in waiting, awaiting=task.id in asked)
    return TaskSummary(
        id=task.id,
        text=lines(task.text),
        repo=task.repo,
        project=task.project,
        branch=tasks.branch(ctx.config.trust.branch_prefix, task.id),
        channel=task.channel,
        submitted_at=db.parse_time(task.submitted_at),
        stopped_at=db.parse_time(task.stopped_at) if task.stopped_at else None,
        standing=_standing(found),
        question_id=asked.get(task.id),
        latest=task_run(latest, ctx.workspace.root) if latest is not None else None,
        runs=runs,
    )


def _standing(found: tasks.Standing) -> TaskStanding:
    """Where a task stands, as the API's vocabulary spells it: the same word.

    Returns:
        The word.
    """
    return RUN_STANDINGS[found] if isinstance(found, RunStatus) else found


def _run_counts(conn: sqlite3.Connection) -> dict[int, int]:
    """How many runs each task has had, by the task's id; a task never run is not listed.

    Returns:
        The counts.
    """
    query = sql.select("task_id, count(*)").from_("task_runs").group_by("task_id")
    return {int(r[0]): int(r[1]) for r in sql.execute(conn, query)}


def _ticket(row: records.TaskTicket) -> TaskTicket:
    return TaskTicket(key=row.key, run_id=row.task_run_id, at=db.parse_time(row.at))


def _run_of(conn: sqlite3.Connection, task_id: int, run_id: int) -> records.TaskRun | None:
    row = tasks.get_run(conn, run_id)
    return row if row is not None and row.task_id == task_id else None
