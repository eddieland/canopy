"""`canopy _task <run_id>`: one run of a one-off task, in the slot the tick leased for it (DESIGN §36).

Checks out the task's branch at a detached HEAD, or the base before one is pushed, runs `runtime.private_worker_cmd`
with the task's prompt, parses the result line, verifies the push of the task's branch as a worker's run does, never
with force whatever `trust.rebase` says (`unpushed` when it cannot), records the head the branch is at on origin, and
tidies and returns the slot. The slot is returned on every exit path this process can see; a run whose `_task` died is
closed by reconcile, and one the operator stops with `--now` by `canopy stop` (`end`).

The run writes nothing about any ticket: its row, its log, and its result name the task alone.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from canopy.core import contract, conversation, db, definitions, hostgit, pools, progress, run_models, tasks
from canopy.core.config import render_command
from canopy.core.vocab import RunStatus
from canopy.infra import logs, procs, stopping
from canopy.runs import checkpoint, tidy
from canopy.runs import tasks as starts
from canopy.runs.checkpoint import SetupError
from canopy.runtime import project_config, stdout

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

#: The most a task's summary or question holds, as a worker's does.
MAX_TEXT = 2000
#: The most PRs a task's result may name: its prompt asks for one at most.
MAX_PRS = 10
#: The run's id as its agent's environment names it, so the operator's commands refuse inside it (DESIGN §22).
RUN_ID_PREFIX = "task-"
#: How a run the operator stopped with `canopy stop task:N --now` ends.
STOP_NOTE = "the operator stopped the task with `canopy stop --now`"

Text = Annotated[StrictStr, contract.bounded(MAX_TEXT)]


class TaskRunError(Exception):
    """`_task` cannot start this run at all: it does not exist or is not waiting to start."""


class TaskResult(BaseModel):
    """A task's result contract (DESIGN §36): the last line of its worker's stdout. Untrusted, so bounded."""

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    status: Literal["done", "blocked", "failed"]
    summary: Text = ""
    question: Text | None = None
    #: The branch it pushed, as it says; canopy checks the branch it named itself.
    branch: Text | None = None
    #: The PR it opened, at most one by its prompt; shown when it is a plain URL.
    prs: Annotated[list[Text], Field(max_length=MAX_PRS)] = []


@dataclass(frozen=True)
class Outcome:
    """How a task's run ended: its status, its validated result, the harness's note, and the head it left on origin."""

    status: RunStatus
    result: TaskResult | None
    note: str = ""
    head: str | None = None

    def result_json(self) -> str:
        """Return what `task_runs.result_json` stores: the validated result and the harness's note, never output."""
        data: dict[str, object] = self.result.model_dump(mode="json") if self.result is not None else {}
        if self.note:
            data["harness"] = self.note
        return json.dumps(data)


def execute(ctx: Context, run_id: int, *, out: TextIO) -> Outcome:
    """Do task run `run_id`, from claiming it to returning its slot and closing its row. Output goes to `out`.

    Returns:
        How the run ended, as its row was closed with. A setup failure, a signal, or an unexpected error is `crashed`,
        with why in its note.

    Raises:
        TaskRunError: the run does not exist or is not waiting to start, for example because another `_task` has it.
    """
    run = tasks.get_run(ctx.conn, run_id)
    if run is None:
        raise TaskRunError(f"no task run {run_id}")
    if not db.claim_run(ctx.conn, "task_runs", run_id, os.getpid()):
        raise TaskRunError(f"task run {run_id} is not waiting to start: it is {run.status} or another process has it")
    slot = Path(run.slot_path)
    # Before any git step: reconcile checks it for a `_task` that dies before putting a changed link back.
    link = hostgit.read_link(slot)
    tasks.set_git_link(ctx.conn, run_id, link)
    log = logs.for_tick(run.tick_id)
    fields = {"task_run_id": run_id, "task": run.task_id, "slot": run.slot_path}
    log.info("task run started", extra={**fields, "branch": run.branch})
    outcome = Outcome(RunStatus.CRASHED, None, "the task's run stopped before its worker finished")
    with stopping.StopOnSignal() as stop:
        try:
            tidy.make_objects(starts.objects_dir(Path(run.log_path)))
            outcome = _work(ctx, run, link, out, log)
        except stopping.Stopped as e:
            outcome = Outcome(RunStatus.CRASHED, None, str(e))
        except SetupError as e:
            outcome = Outcome(RunStatus.CRASHED, None, str(e))
            log.error("task run setup failed", extra={**fields, "error": str(e)})  # noqa: TRY400  (no traceback)
        except Exception as e:
            outcome = Outcome(RunStatus.CRASHED, None, f"{type(e).__name__}: {e}")
            log.exception("task run failed", extra=fields)
        finally:
            # From here on a signal is ignored: returning the slot and closing the row must not be interrupted.
            stop.armed = False
            release(ctx, run, link, log)
            stored = outcome.result_json()
            if not tasks.close_run(ctx.conn, run_id, outcome.status, stored, head=outcome.head):
                log.warning("task run was already closed; its outcome is not recorded", extra=fields)
            procs.drop_lifelock(Path(run.log_path))
            log.info("task run finished", extra={**fields, "status": outcome.status, "head": outcome.head})
            run_models.read_ended(ctx, "task_runs", run_id, log)
    return outcome


def end(ctx: Context, run: records.TaskRun, status: RunStatus, note: str, log: logs.TickAdapter) -> set[str]:
    """Close a task run whose `_task` is gone, or was killed, as `status`: stop its worker, tidy and return its slot.

    Reconcile closes a crashed run this way, and `canopy stop task:N --now` a stopped one.

    Returns:
        The lease ids it dealt with, returned or kept, which reconcile then leaves alone; none when the run's own
        `_task` closed it first.
    """
    fields = {"task_run_id": run.id, "task": run.task_id, "pid": run.pid, "slot": run.slot_path}
    # `_task` is gone, but a worker it started may not be. Stop it before its slot goes back to its pool.
    if run.agent_pid is not None and procs.kill_group(run.agent_pid):
        log.warning("killed the agent a gone process left behind", extra={**fields, "agent_pid": run.agent_pid})
    if not tasks.close_run(ctx.conn, run.id, status, json.dumps({"harness": note}), head=None):
        # Its own `_task` closed it first, and returned its slot.
        return set()
    procs.drop_lifelock(Path(run.log_path))
    release(ctx, run, run.git_link, log)
    log.warning("task run closed without its `_task`", extra={**fields, "status": status, "note": note})
    return {run.lease_id}


def stop_now(ctx: Context, run: records.TaskRun, log: logs.TickAdapter) -> bool:
    """Kill task run `run`'s processes and close it `stopped`, its slot returned: `canopy stop task:N --now`.

    Returns:
        True once the run is closed, or False if it had already ended: nothing changes.
    """
    for pid in (run.pid, run.agent_pid):
        # Never this process's own group: a `_task` claimed in-process, as tests run it, has this pid.
        if pid is not None and pid not in (os.getpid(), os.getpgid(0)):
            procs.kill_group(pid)
    current = tasks.get_run(ctx.conn, run.id)
    if current is None or current.status is not RunStatus.RUNNING:
        return False
    return bool(end(ctx, current, RunStatus.STOPPED, STOP_NOTE, log))


def release(ctx: Context, run: records.TaskRun, link: bytes | None, log: logs.TickAdapter) -> None:
    """Tidy the run's slot as a worker run's is (DESIGN §8), return it, and remove the run's object directory.

    A slot that could not be tidied is not returned, and the object directory is kept, so its objects can be read.
    """
    fields = {"task_run_id": run.id, "slot": run.slot_path, "lease_id": run.lease_id, "repo": run.repo}
    slot = Path(run.slot_path)
    objects = starts.objects_dir(Path(run.log_path))
    if not tidy.tidy(ctx.runner, slot, link=link, base=run.base_branch, objects=objects, log=log, fields=fields):
        return
    tidy.remove_objects(objects, log)
    try:
        outcome = ctx.pool_of(run.pool, run.repo).return_slot(
            slot,
            lease_id=run.lease_id,
            lease_holder=run.lease_holder,
        )
    except pools.PoolError as e:
        # The next tick's reconcile returns a canopy lease no running run holds.
        log.error("task's slot not returned", extra={**fields, "error": str(e)})  # noqa: TRY400
        return
    if outcome is pools.ReturnOutcome.RETURNED:
        log.info("task's slot returned", extra=fields)
    else:
        log.warning("task's slot not returned", extra={**fields, "outcome": outcome.value})


def _work(ctx: Context, run: records.TaskRun, link: bytes | None, out: TextIO, log: logs.TickAdapter) -> Outcome:
    """Check the branch out, run the task's worker, and check what it pushed.

    Returns:
        The worker's status; `timeout`, `unknown` for a missing or invalid result line, `unpushed` for work not on
        origin, `crashed` for a worker that rewrote its slot's git, or `stopped` for a task stopped before it started.

    Raises:
        SetupError: a git step failed, or the runtime's config where it runs shadows canopy's definitions.
    """
    task = tasks.get(ctx.conn, run.task_id)
    if task is None or task.stopped_at is not None:
        note = "the operator stopped the task before its worker started"
        log.info("task run not started", extra={"task_run_id": run.id, "reason": note})
        return Outcome(RunStatus.STOPPED, None, note)
    slot = Path(run.slot_path)
    git = checkpoint.Git(ctx.runner, slot, run.repo)
    start = checkpoint.check_out(git, run.base_branch, run.branch)
    done, text = _run_agent(ctx, run, task, out, log)
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes
    parsed = contract.last_line(TaskResult, text)
    if done.timed_out:
        status, note = RunStatus.TIMEOUT, f"the worker timed out after {timeout_minutes} minutes"
    elif parsed is None:
        status, note = RunStatus.UNKNOWN, "the worker's last line was not a valid result"
    else:
        status, note = RunStatus(parsed.status), ""
    rewritten = _rewritten(slot, link)
    if rewritten is not None:
        # The slot's git directory may be one the worker made: canopy runs no git in it.
        return Outcome(RunStatus.CRASHED, parsed, f"the worker rewrote {rewritten}; nothing was checked or pushed")
    objects = starts.objects_dir(Path(run.log_path))
    if tidy.used(objects):
        # A sandboxed worker's commits are only in the run's object directory (DESIGN §8).
        try:
            git = checkpoint.Git(ctx.runner, slot, run.repo, tidy.reading(ctx.runner, slot, objects))
        except tidy.GitError as e:
            raise SetupError(str(e)) from e
    # Never with force: a task's branch has no base to keep up with, and a ticket may cite its commits (DESIGN §36).
    unpushed = checkpoint.ensure_pushed(git, run.branch, start, log, rebase=False)
    if unpushed:
        status, note = RunStatus.UNPUSHED, unpushed
    head = checkpoint.remote_head(git, run.branch) or None
    forced = _forced(git, run.branch, start, head)
    if forced:
        # Under `trust.rebase` the private worker's definition allows a push with a lease; a task's prompt forbids it.
        log.warning("task's branch rewritten on origin", extra={"task_run_id": run.id, "before": start.pushed})
        note = "; ".join(n for n in (note, forced) if n)
    return Outcome(status, parsed, note, head=head)


def _forced(git: checkpoint.Git, branch: str, start: checkpoint.Start, head: str | None) -> str:
    """Return a harness note when the commit the branch held before the run is no longer on it: it was forced.

    Returns:
        The note, or "" when the branch was not on origin before the run, or still holds what it held then.
    """
    if not start.pushed or head == start.pushed:
        return ""
    if head is not None:
        # --refmap=: no remote-tracking ref moves, only the slot's own FETCH_HEAD, which tidying drops.
        git.result("fetch", "--quiet", "--refmap=", "origin", f"refs/heads/{branch}")
        if git.ok("merge-base", "--is-ancestor", start.pushed, head):
            return ""
    return f"{branch} no longer holds {start.pushed[:12]}, its head when the run started: pushed with force, or deleted"


def _run_agent(
    ctx: Context,
    run: records.TaskRun,
    task: records.Task,
    out: TextIO,
    log: logs.TickAdapter,
) -> tuple[procs.Result, str]:
    """Run the private worker's command in the slot with the task's prompt, for the worker's timeout.

    The private worker's definition is the one that writes nothing to a ticket (DESIGN §22), so the slot's config must
    name none of the tracker server's tools either. The session, cost, and tool calls the runtime reported are recorded
    at once.

    Returns:
        The agent's process and the text its result line is read from.

    Raises:
        SetupError: the runtime's config in the slot shadows canopy's definitions or names a tracker tool.
    """
    slot = Path(run.slot_path)
    tools = ctx.config.tracker.tools()
    refused = project_config.refusal([slot], tracker_server=tools.server if tools is not None else None)
    if refused is not None:
        raise SetupError(refused)
    prompt = starts.prompt_file(Path(run.log_path)).read_text(encoding="utf-8")
    snapshot = definitions.ensure(ctx.state_dir, ctx.config)
    runtime = ctx.config.runtime
    argv = render_command(runtime.worker_template(runtime.private_worker_cmd), prompt, snapshot, f"task:{task.id}")
    timeout_minutes = runtime.worker_timeout_minutes
    log.info(
        "running the task's worker",
        extra={"task_run_id": run.id, "cmd": argv[0], "cwd": str(slot), "timeout_minutes": timeout_minutes},
    )
    out.write("--- worker stdout ---\n")
    out.flush()
    objects = starts.objects_dir(Path(run.log_path))
    env = {conversation.RUN_ID_ENV: f"{RUN_ID_PREFIX}{run.id}", tidy.OBJECTS_ENV: str(objects)}
    done = ctx.runner.run(
        argv,
        cwd=slot,
        env=env,
        timeout=timeout_minutes * 60,
        on_start=lambda pid: db.set_agent_pid(ctx.conn, "task_runs", run.id, pid),
        on_line=progress.Progress(
            ctx.conn,
            "task_runs",
            run.id,
            out,
            log,
            agent="task",
            fields={"task_run_id": run.id},
        ),
    )
    out.write(f"\n--- worker stderr ---\n{done.stderr}\n")
    out.write(f"--- worker exit {done.returncode}{' (timed out)' if done.timed_out else ''} ---\n")
    out.flush()
    # Also after a timeout: whatever it printed before the kill names its session and what it had spent.
    output = stdout.read(done.stdout)
    if output.session_id is not None or output.usage is not None:
        db.set_run_report(
            ctx.conn,
            "task_runs",
            run.id,
            output.session_id,
            output.usage,
            digest=snapshot.name,
            tools=output.tools,
        )
    return done, output.text


def _rewritten(slot: Path, link: bytes | None) -> Path | None:
    """Return the file that says where the slot's git is, if the worker changed it: `.git`, or `commondir`.

    Returns:
        The `.git` file if it no longer holds `link`, else `commondir` if it no longer names the common directory,
        else None. Always None when `.git` was not a file at the start.
    """
    if link is None:
        return None
    if hostgit.read_link(slot) != link:
        return slot / hostgit.LINK
    if hostgit.commondir_moved(slot, link):
        own = hostgit.own_git_dir(slot, link)
        return (own or slot) / hostgit.COMMONDIR
    return None
