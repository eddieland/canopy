"""The operator's one-off tasks (DESIGN §36): what `canopy task list` and `canopy show task:N` print.

Each run is readable on its own, with its session's transcript and the report it left: untrusted text, read back from
its log and from the state directory. The overseer never reads a task.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.serve import task_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import TaskId, TaskRunId, not_found
from canopy.serve.task_schema import TaskDetail, TaskReport, TaskRunDetail, TaskSummary
from canopy.serve.transcript_schema import Transcript

TAG = "tasks"
router = APIRouter(tags=[TAG])


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
