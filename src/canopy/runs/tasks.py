"""The tick starts the operator's one-off tasks (DESIGN §36): in code, after reconcile and before the overseer.

The operator's submission, or their reply to it, authorized each run, and the overseer never sees one. Guards in code
hold them, whatever any agent asks: one run per task, at most `capacity.max_tasks` task runs at once, and every run
that holds a slot, a worker's, a review's, or a task's, within `capacity.max_workers`. A task the guards hold waits for
a later tick rather than being refused, and a dry tick starts none (D036). Each start leases a slot in the task's
repository's pool as `canopy:task:<id>`, records the run, renders its prompt, and spawns the detached `canopy _task`
(`task_run.py`).
"""

from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import conversation, db, notice, pools, prompts, tasks
from canopy.core.vocab import RunStatus
from canopy.infra import lock, logs, procs

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy.core import records
    from canopy.core.context import Context

#: Where task runs' logs, prompts, and object directories live: `<state_dir>/task-runs/`, the operator's only.
RUNS_DIR = "task-runs"


@dataclass(frozen=True)
class Started:
    """A task's run the tick started: the task, its run, and the pid of its `canopy _task`."""

    task_id: int
    run_id: int
    pid: int


def start_queued(ctx: Context, tick_id: int, log: logs.TickAdapter) -> list[Started]:
    """Start each queued task the guards let start now, the oldest first, under the dispatch lock (DESIGN §36).

    A task whose repository has no clone, or whose pool has no slot free, waits for a later tick, and the tasks after
    it are still tried; once the task runs fill `capacity.max_tasks`, or every run that holds a slot fills
    `capacity.max_workers`, the rest wait. The caller starts none on a dry tick.

    Returns:
        The runs it started, in the order it started them.
    """
    started: list[Started] = []
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        for task in tasks.queued(ctx.conn):
            held = _held(ctx)
            if held is not None:
                log.info("tasks wait", extra={"task": task.id, "reason": held})
                break
            found = _start(ctx, task, tick_id, log)
            if found is not None:
                started.append(found)
    return started


def runs_dir(ctx: Context) -> Path:
    """Where task runs' logs, prompts, and object directories live, readable only by the operator (TRUST_MODEL T2).

    Returns:
        `<state_dir>/task-runs`, created if it is missing.
    """
    path = ctx.state_dir / RUNS_DIR
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def prompt_file(log_path: Path) -> Path:
    """Return the file holding a task run's rendered prompt: beside its log at `log_path`, as `<run_id>.prompt`."""
    return log_path.with_suffix(".prompt")


def objects_dir(log_path: Path) -> Path:
    """Return a task run's object directory, beside its log at `log_path`, as a worker run's is (DESIGN §8)."""
    return log_path.with_suffix(".objects")


def _held(ctx: Context) -> str | None:
    """Why no task may start now: the task runs fill `max_tasks`, or the runs holding slots fill `max_workers`.

    Returns:
        The reason, or None when one may start.
    """
    capacity = ctx.config.capacity
    running = len(db.running_runs(ctx.conn, "task_runs"))
    if running >= capacity.max_tasks:
        return f"{running} of {capacity.max_tasks} task runs are running"
    busy = db.busy_workers(ctx.conn)
    if busy >= capacity.max_workers:
        return f"{busy} of {capacity.max_workers} workers, reviews, and tasks are running"
    return None


def _start(ctx: Context, task: records.Task, tick_id: int, log: logs.TickAdapter) -> Started | None:
    """Lease a slot for `task`, record its run, and spawn its `canopy _task`.

    Returns:
        The run, or None when the task waits: its repository has no clone, its pool no slot, or a stop came first.
    """
    fields = {"task": task.id, "repo": task.repo}
    repo = ctx.workspace.repo(task.repo)
    if repo is None or not repo.cloned:
        # The tick raises `repo_missing` for a repository in the map with no clone; one gone from the map stays so.
        log.warning("task waits: its repository has no clone here", extra=fields)
        return None
    pool = ctx.pool(repo.name)
    try:
        lease = pool.lease(f"{tasks.HOLDER_KEY}{task.id}")
    except pools.PoolError as e:
        log.warning("task waits: no slot", extra={**fields, "error": str(e)})
        return None
    run_id = tasks.insert_run(
        ctx.conn,
        task=task,
        tick_id=tick_id,
        branch_name=tasks.branch(ctx.config.trust.branch_prefix, task.id),
        lease=lease,
        pool=ctx.config.pools.backend,
        logs_dir=runs_dir(ctx),
    )
    if run_id is None:
        _give_back(pool, lease, log, fields)
        return None
    try:
        pid = _spawn(ctx, task, run_id, lease)
    except _NotStarted as e:
        _give_back(pool, lease, log, fields)
        log.error("task run not started", extra={**fields, "task_run_id": run_id, "error": str(e)})  # noqa: TRY400
        return None
    log.info("task run started", extra={**fields, "task_run_id": run_id, "pid": pid, "slot": str(lease.path)})
    return Started(task.id, run_id, pid)


class _NotStarted(Exception):  # noqa: N818  (an outcome the run is closed with, not an error of the tick's)
    """The run's prompt could not be rendered, or its process started; the run is closed `crashed`, saying why."""


def _spawn(ctx: Context, task: records.Task, run_id: int, lease: pools.Lease) -> int:
    """Render run `run_id`'s prompt, write it beside its log, and spawn its detached `canopy _task`.

    Returns:
        The pid of `canopy _task`, which claims the run.

    Raises:
        _NotStarted: the prompt could not be rendered or written, or the process started. The run is closed `crashed`
            with why, so the task does not start again: a task never retries on its own (DESIGN §36).
        RuntimeError: the run's row is gone, which nothing but a broken journal does.
    """
    run = tasks.get_run(ctx.conn, run_id)
    if run is None:
        raise RuntimeError(f"task run {run_id} vanished")
    values = {
        "TASK_ID": str(task.id),
        "TASK": task.text,
        "REPO": task.repo,
        "SLOT": str(lease.path),
        "BRANCH": run.branch,
        "BASE": lease.base_branch,
        "TIMEOUT_MINUTES": str(ctx.config.runtime.worker_timeout_minutes),
        # Earlier runs' reports and questions, data, and the operator's replies, instructions, up to the newest message
        # when the run started (DESIGN §36). None on a task's first run, which leaves the section out.
        "CONVERSATION": conversation.prompt_task_conversation(ctx.conn, task.id, run.message_id),
    }
    log_path = Path(run.log_path)
    try:
        prompt = prompts.render_task(ctx.config, values, notice=notice.for_prompt(ctx.conn))
        logs.write_private(prompt_file(log_path), prompt)
        # `python -m canopy`, not `canopy` from PATH: the child is this same installation.
        argv = [sys.executable, "-m", "canopy", "_task", str(run_id)]
        pid = ctx.runner.spawn(argv, cwd=ctx.repo_root, log_path=log_path)
    except (OSError, prompts.PromptError, procs.ProcError) as e:
        note = json.dumps({"harness": f"could not start the task's worker: {e}"})
        tasks.close_run(ctx.conn, ctx.config, run_id, RunStatus.CRASHED, note, head=None)
        raise _NotStarted(str(e)) from e
    db.claim_run(ctx.conn, "task_runs", run_id, pid)
    return pid


def _give_back(pool: pools.Pool, lease: pools.Lease, log: logs.TickAdapter, fields: Mapping[str, object]) -> None:
    """Return a slot a start leased and cannot use. A return that fails is left to the next tick's reconcile."""
    with contextlib.suppress(pools.PoolError):
        outcome = pool.return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
        log.info("task's slot returned unused", extra={**fields, "slot": str(lease.path), "outcome": outcome.value})
