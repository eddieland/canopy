"""One-off tasks' runs (DESIGN §36): started by the tick in code, closed when their process is gone, and stopped.

A queued task starts after reconcile and before the overseer, oldest first, under the dispatch lock: one run per task,
at most `capacity.max_tasks` task runs at once, within `capacity.max_workers`, which counts worker, review, and task
runs together. A task the guards hold waits for a later tick, as does one whose repository has no slot to lease or no
clone; nothing refuses it, and nothing retries a run of it. A dry tick starts none (D036). The run leases its slot as
`canopy:task:<N>`, and its detached `canopy _task` does the rest (`task_worker.py`). No overseer reads or decides any of
it, and no ticket is named in anything it writes.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import conversation, db, dead_runs, notice, pools, prompts, tasks
from canopy.core.vocab import TaskRunStatus
from canopy.infra import lock, logs, procs
from canopy.infra.text import one_line
from canopy.runs import tidy

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

#: Where task runs' logs, prompts, and object directories are: `<state_dir>/tasks/runs/`, the operator's only.
RUNS_DIR = Path("tasks") / "runs"
#: How a task run's agent is named in `CANOPY_RUN_ID`, apart from a worker run's plain id: `task-<id>`.
RUN_ID_PREFIX = "task-"
#: What `canopy stop task:N --now` closes the run working it with.
STOPPED_NOTE = "the operator stopped the task with `canopy stop --now`"
#: How much of a task's text names its run's session (DESIGN §13).
TITLE_CHARS = 60


@dataclass(frozen=True)
class Started:
    """A task run a tick started: its id, its task's, and the pid of its `canopy _task`."""

    run_id: int
    task_id: int
    pid: int


def start_queued(ctx: Context, tick_id: int, log: logs.TickAdapter, *, dry_run: bool) -> list[Started]:
    """Start the queued tasks the guards let start now, oldest first, in tick `tick_id` (DESIGN §36).

    Held under the dispatch lock, so no dispatch or review counts capacity while a task takes some. A dry tick starts
    nothing, and leaves every task queued for a live one.

    Returns:
        The runs started.
    """
    if dry_run:
        return []
    waiting = tasks.queued(ctx.conn)
    if not waiting:
        return []
    started: list[Started] = []
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        for task in waiting:
            held = _held(ctx)
            if held is not None:
                log.info("tasks wait", extra={"tasks": [t.id for t in waiting if t.id >= task.id], "reason": held})
                break
            run = _start(ctx, tick_id, task, log)
            if run is not None:
                started.append(run)
    return started


def runs_dir(ctx: Context) -> Path:
    """Where task runs' logs, prompts, and object directories live, readable only by the operator (TRUST_MODEL T2).

    Returns:
        `<state_dir>/tasks/runs`, created mode 0700 if it was missing.
    """
    path = ctx.state_dir / RUNS_DIR
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def prompt_file(ctx: Context, run_id: int) -> Path:
    """Return the file holding task run `run_id`'s rendered prompt."""
    return runs_dir(ctx) / f"{run_id}.prompt"


def objects_dir(ctx: Context, run_id: int) -> Path:
    """Return task run `run_id`'s object directory, as a worker run's is (DESIGN §8)."""
    return tidy.objects_dir(runs_dir(ctx), run_id)


def session_title(task: records.Task) -> str:
    """A task run's session title: `task:<N>: ` and the start of the operator's text, on one line.

    Returns:
        The title.
    """
    text = one_line(task.text)
    cut = text if len(text) <= TITLE_CHARS else f"{text[: TITLE_CHARS - 3]}..."
    return f"{conversation.TASK}:{task.id}: {cut}"


def reconcile(ctx: Context, log: logs.TickAdapter) -> set[str]:
    """Close task runs whose `canopy _task` is gone as `crashed`, and return their slots (DESIGN §6 step 3).

    The agent leads its own process group, so whatever is left of it is killed before its slot goes back.

    Returns:
        The lease ids it dealt with, returned or kept, which the worker runs' reconcile then leaves alone.

    Raises:
        pools.PoolError: a slot could not be returned. The tick stops, as for a worker run's slot.
    """
    dealt: set[str] = set()
    for row in dead_runs.find(ctx.conn, "task_runs"):
        run = tasks.get_run(ctx.conn, int(row["id"]))
        if run is None:
            continue
        dead_runs.kill_agent("task_runs", row, log, {"task_run_id": run.id, "task": run.task_id, "pid": run.pid})
        dealt |= end(ctx, run, TaskRunStatus.CRASHED, "the task's process is gone", log)
    return dealt


def stop(ctx: Context, run: records.TaskRun, log: logs.TickAdapter) -> bool:
    """End task run `run` now, for `canopy stop task:N --now`: kill its processes, and close it `stopped`.

    Returns:
        True once the run is closed, or False if it had already ended: nothing changes.

    Raises:
        pools.PoolError: its slot could not be returned; the next tick's reconcile returns it.
    """
    for pid in (run.pid, run.agent_pid):
        # Never this process's own group: a `_task` claimed in-process, as tests run it, has this pid.
        if pid is not None and pid not in (os.getpid(), os.getpgid(0)):
            procs.kill_group(pid)
    current = tasks.get_run(ctx.conn, run.id)
    if current is None or current.status is not TaskRunStatus.RUNNING:
        return False
    end(ctx, current, TaskRunStatus.STOPPED, STOPPED_NOTE, log)
    return True


def end(ctx: Context, run: records.TaskRun, status: TaskRunStatus, note: str, log: logs.TickAdapter) -> set[str]:
    """Close a task run whose `canopy _task` is gone, or was killed, as `status`: tidy and return its slot.

    The slot is tidied as `_task` would have (DESIGN §8): its `.git` file checked against what `_task` recorded, and
    the slot moved off the run's own objects. One that cannot be tidied is kept, and so is the object directory.

    Returns:
        The lease ids it dealt with, returned or kept.

    Raises:
        pools.PoolError: the slot could not be returned.
    """
    fields = {"task_run_id": run.id, "task": run.task_id, "slot": run.slot_path, "repo": run.repo}
    objects = objects_dir(ctx, run.id)
    if tidy.tidy(
        ctx.runner,
        Path(run.slot_path),
        link=run.git_link,
        base=run.base_branch,
        objects=objects,
        log=log,
        fields=fields,
    ):
        outcome = ctx.pool_of(run.pool, run.repo).return_slot(
            Path(run.slot_path),
            lease_id=run.lease_id,
            lease_holder=run.lease_holder,
        )
        tidy.remove_objects(objects, log)
        fields["returned"] = outcome.value
    tasks.close_run(ctx.conn, run, status, json.dumps({"harness": note}))
    procs.drop_lifelock(Path(run.log_path))
    log.warning("task run closed without its `_task`", extra={**fields, "status": status, "note": note})
    return {run.lease_id}


def _held(ctx: Context) -> str | None:
    """Why no task may start now: `capacity.max_tasks`, `capacity.max_workers`, or no tracker tools to run it with.

    Returns:
        The reason, or None when one may start.
    """
    cap = ctx.config.capacity
    running = len(tasks.running(ctx.conn))
    if running >= cap.max_tasks:
        return f"{running} of capacity.max_tasks ({cap.max_tasks}) task runs are running"
    busy = running + len(db.running_runs(ctx.conn, "runs")) + len(db.running_runs(ctx.conn, "review_runs"))
    if busy >= cap.max_workers:
        return f"{busy} of capacity.max_workers ({cap.max_workers}) workers, reviews, and task runs are running"
    # A task's worker is the private worker, whose definition needs them to keep it off the tracker (DESIGN §22).
    if ctx.config.tracker.tools() is None:
        return "no tracker tools are known for the private worker: set tracker.mcp_server and tracker.read_tools"
    return None


def _start(ctx: Context, tick_id: int, task: records.Task, log: logs.TickAdapter) -> Started | None:
    """Lease a slot for `task`, record its run, render its prompt, and spawn `canopy _task` for it.

    A repository with no clone, a pool with no slot, or a prompt that does not render leaves the task queued, its slot
    returned. A process that does not start ends the run `crashed`: the task's run was made, and is not tried again.

    Returns:
        The run started, or None when the task waits.
    """
    fields = {"task": task.id, "repo": task.repo}
    repo = ctx.workspace.repo(task.repo)
    if repo is None or not repo.cloned:
        log.warning("task waits: its repository is not in the map, or has no clone", extra=fields)
        return None
    pool = ctx.pool(repo.name)
    try:
        lease = pool.lease(tasks.holder_key(task.id))
    except pools.PoolError as e:
        log.warning("task waits: no slot", extra={**fields, "error": str(e)})
        return None
    branch = tasks.branch_name(ctx.config.trust.branch_prefix, task.id)
    try:
        prompt = _prompt(ctx, task, branch, lease)
    except (OSError, prompts.PromptError) as e:
        _give_back(pool, lease)
        log.error("task waits: its prompt does not render", extra={**fields, "error": str(e)})  # noqa: TRY400
        return None
    run = tasks.insert_run(
        ctx.conn,
        task=task,
        tick_id=tick_id,
        branch=branch,
        slot=lease.path,
        lease_id=lease.lease_id,
        lease_holder=lease.lease_holder,
        base_branch=lease.base_branch,
        pool=ctx.config.pools.backend,
        logs_dir=runs_dir(ctx),
    )
    try:
        logs.write_private(prompt_file(ctx, run.id), prompt)
        # `python -m canopy`, not `canopy` from PATH: the child is this same installation.
        argv = [sys.executable, "-m", "canopy", "_task", str(run.id)]
        pid = ctx.runner.spawn(argv, cwd=ctx.repo_root, log_path=Path(run.log_path))
    except (OSError, procs.ProcError) as e:
        _give_back(pool, lease)
        tasks.close_run(ctx.conn, run, TaskRunStatus.CRASHED, json.dumps({"harness": f"could not start: {e}"}))
        log.error("task run did not start", extra={**fields, "task_run_id": run.id, "error": str(e)})  # noqa: TRY400
        return None
    db.claim_run(ctx.conn, "task_runs", run.id, pid)
    log.info("task run started", extra={**fields, "task_run_id": run.id, "branch": branch, "slot": str(lease.path)})
    return Started(run.id, task.id, pid)


def _prompt(ctx: Context, task: records.Task, branch: str, lease: pools.Lease) -> str:
    """Render task `task`'s prompt for a run in `lease`'s slot, on `branch` (DESIGN §36).

    Returns:
        The prompt.
    """
    cfg = ctx.config
    values: dict[str, str | None] = {
        "TASK": task.text,
        "TASK_ID": str(task.id),
        "REPOSITORY": task.repo,
        "SLOT": str(lease.path),
        "BRANCH": branch,
        "BASE": lease.base_branch,
        "TRACKER_PROVIDER": cfg.tracker.provider,
        "TIMEOUT_MINUTES": str(cfg.runtime.worker_timeout_minutes),
    }
    return prompts.render_task(cfg, values, notice=notice.for_prompt(ctx.conn))


def _give_back(pool: pools.Pool, lease: pools.Lease) -> None:
    """Return a slot a task's start leased and cannot use. A return that fails is left to the next tick's reconcile."""
    with contextlib.suppress(pools.PoolError):
        pool.return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
