"""The operator's one-off tasks (DESIGN §36): what `canopy task list` and `canopy show task:N` print.

Each run is readable on its own, with its session's transcript and the report it left: untrusted text, read back from
its log and from the state directory. The overseer never reads a task.

The operator submits, replies to, and stops one through the functions `canopy task submit`, `canopy reply task:N`, and
`canopy stop task:N` call, with channel `web`, so a submission is their authorization as the shell's is (TRUST_MODEL
T1).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.core import conversation
from canopy.core import tasks as task_rows
from canopy.core.vocab import RunStatus
from canopy.infra import logs
from canopy.serve import task_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, TaskId, TaskRunId, not_found
from canopy.serve.schema import ReplyRequest
from canopy.serve.schema.task import (
    TaskDetail,
    TaskReplied,
    TaskReport,
    TaskRunDetail,
    TaskStopped,
    TaskSubmitRequest,
    TaskSubmitted,
    TaskSummary,
)
from canopy.serve.schema.ticket import StopRequest
from canopy.serve.schema.transcript import Transcript

TAG = "tasks"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get("/tasks", operation_id="listTasks", summary="List the tasks")
def tasks(backend: BackendDep) -> list[TaskSummary]:
    """Every task the operator submitted, the newest first, with where each stands, as `canopy task list` lists them."""
    with backend.open() as ctx:
        return task_views.tasks_list(ctx)


@router.get("/tasks/{task_id}", operation_id="getTask", summary="Get a task", responses=not_found("task"))
def task(task_id: TaskId, backend: BackendDep) -> TaskDetail:
    """One task: what `canopy show task:N` prints, its text, every run, its conversation, and its tickets."""
    with backend.open() as ctx:
        found = task_views.task_detail(ctx, task_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no task:{task_id}")
    return found


@router.get(
    "/tasks/{task_id}/runs/{run_id}",
    operation_id="getTaskRun",
    summary="Get a task run",
    responses=not_found("run of this task"),
)
def task_run(task_id: TaskId, run_id: TaskRunId, backend: BackendDep) -> TaskRunDetail:
    """One run of the task: its row, the whole of its summary and question, the harness's note, and its tickets.

    A run is found only under its own task.
    """
    with backend.open() as ctx:
        found = task_views.task_run_detail(ctx, task_id, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"task:{task_id} has no run {run_id}")
    return found


# Agent output, read back from the run's log on each request; never on the stream (DESIGN §22).
@router.get(
    "/tasks/{task_id}/runs/{run_id}/transcript",
    operation_id="getTaskRunTranscript",
    summary="Get a task run's transcript",
    responses=not_found("run of this task"),
)
def task_run_transcript(task_id: TaskId, run_id: TaskRunId, backend: BackendDep) -> Transcript:
    """The task run's session, read back from its log: agent output, untrusted and bounded."""
    with backend.open() as ctx:
        found = task_views.task_run_transcript(ctx, task_id, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"task:{task_id} has no run {run_id}")
    return found


@router.get(
    "/tasks/{task_id}/runs/{run_id}/report",
    operation_id="getTaskRunReport",
    summary="Get a task run's report",
    responses=not_found("report this run of the task left"),
)
def task_run_report(task_id: TaskId, run_id: TaskRunId, backend: BackendDep) -> TaskReport:
    """The report the run left, as its file in the state directory stands now: the worker's Markdown, untrusted.

    A run that left none is a 404; a file no longer a report says why, as `canopy show task:N` does.
    """
    with backend.open() as ctx:
        found = task_views.task_report(ctx, task_id, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} of task:{task_id} left no report")
    return found


@router.post("/tasks", operation_id="submitTask", summary="Submit a task", responses=REFUSED)
def submit(body: TaskSubmitRequest, backend: BackendDep) -> TaskSubmitted:
    """`canopy task submit`: queue the operator's text as a task; the next tick starts it, as capacity allows.

    Refused `bad_body` for an empty text or one too long, `unknown_repo` for a repository the workspace has not, or
    none named in a workspace of several, and `bad_project` for a project no tracker could name.
    """
    with backend.open() as ctx:
        try:
            task = task_rows.submit(
                ctx.conn,
                ctx.workspace,
                body.text,
                repo=body.repo,
                project=body.project,
                channel=WEB,
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
        branch = task_rows.branch(ctx.config.trust.branch_prefix, task.id)
        no_capacity = ctx.config.capacity.max_tasks == 0
    _log.info("task submitted", extra={"task": task.id, "repo": task.repo, "channel": WEB})
    return TaskSubmitted(id=task.id, repo=task.repo, branch=branch, no_capacity=no_capacity)


@router.post("/tasks/{task_id}/replies", operation_id="replyTask", summary="Reply to a task", responses=REFUSED)
def reply(task_id: TaskId, body: ReplyRequest, backend: BackendDep) -> TaskReplied:
    """`canopy reply task:N`: the operator's next instruction, answering its run's question if one asked.

    It queues the task's next run, on its branch, once no run of it is working. Idempotent on the submission id.
    """
    ref = conversation.Ref(conversation.TASK, str(task_id))
    with backend.open() as ctx:
        try:
            replied = conversation.reply(ctx.conn, ref, body.body, channel=WEB, submission=body.submission)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        running = next((r.id for r in task_rows.runs_of(ctx.conn, task_id) if r.status is RunStatus.RUNNING), None)
    _log.info("operator replied", extra={"subject": str(ref), "message_id": replied.message_id, "channel": WEB})
    return TaskReplied(message_id=replied.message_id, answers=replied.answers, new=replied.new, running_run=running)


@router.post("/tasks/{task_id}/stop", operation_id="stopTask", summary="Stop a task", responses=REFUSED)
def stop(task_id: TaskId, body: StopRequest, backend: BackendDep) -> TaskStopped:
    """`canopy stop task:N`: no tick starts it again; a running run finishes unless `now` ends it, as `--now` does."""
    with backend.open() as ctx:
        try:
            stopped = task_rows.stop(ctx.conn, task_id)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        _log.info("task stopped", extra={"task": task_id, "now": body.now, "channel": WEB})
        run = stopped.running
        ended = run is not None and body.now and backend.end_task_run(ctx, run)
    return TaskStopped(
        already=stopped.already,
        dropped=stopped.dropped,
        running_run=run.id if run is not None else None,
        ended=ended,
    )
