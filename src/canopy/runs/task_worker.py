"""`canopy _task <run_id>`: one run of a one-off task (DESIGN §36), in the slot the tick leased for it.

Checks the slot out at the task's branch as origin has it, or at its base before one is pushed, detached; runs the
operator's `setup_cmd`; runs `runtime.private_worker_cmd` with the task's prompt; parses the result line; verifies the
push of `<branch_prefix>task/<N>` as a worker run's is (`checkpoint.ensure_pushed`), never with force, whatever
`trust.rebase` says; records the commit the branch then holds on origin; returns the slot; and closes the run with its
report and question as messages in the task's conversation. A run that commits nothing pushes nothing, and that is not
a failure. The slot is returned on every exit path this process can see, as `_run` returns a worker's.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from canopy.core import contract, conversation, db, definitions, progress, tasks
from canopy.core.config import render_command
from canopy.core.vocab import TaskRunStatus
from canopy.infra import logs, procs, stopping
from canopy.runs import checkpoint, tidy
from canopy.runs import tasks as task_runs
from canopy.runtime import project_config, stdout

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

MAX_TEXT = 2000
MAX_PR_URL = tasks.MAX_PR_URL
#: A task opens one PR at most; a result naming more than this many is no result.
MAX_PRS = 5

Text = Annotated[StrictStr, contract.bounded(MAX_TEXT)]
PrUrl = Annotated[StrictStr, contract.bounded(MAX_PR_URL)]


class TaskError(Exception):
    """`_task` cannot start this run at all: it does not exist or is not waiting to start. Nothing was changed."""


class TaskResult(BaseModel):
    """A task run's result contract (DESIGN §36): the last line of its worker's text. Untrusted, so bounded.

    `branch` is what the worker says it pushed; canopy checks only its own name for the task's branch. The tickets a
    task files, `created`, are read once tasks may file them; until then a result that names them is read without them.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    status: Literal["done", "blocked", "failed"]
    summary: Text = ""
    question: Text | None = None
    branch: Text | None = None
    prs: Annotated[list[PrUrl], Field(max_length=MAX_PRS)] = []


@dataclass(frozen=True)
class Outcome:
    """How a task run ended: its status, its validated result, the harness's note, and the commit it left pushed."""

    status: TaskRunStatus
    result: TaskResult | None
    note: str = ""
    #: The commit the task's branch holds on origin after the run; None when origin has no such branch.
    head: str | None = None

    def result_json(self) -> str:
        """Return what `task_runs.result_json` stores: the validated result and the harness's note. Never raw output."""
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
        TaskError: the run does not exist or is not waiting to start, for example because another `_task` has it.
    """
    run = tasks.get_run(ctx.conn, run_id)
    if run is None:
        raise TaskError(f"no task run {run_id}")
    if not db.claim_run(ctx.conn, "task_runs", run_id, os.getpid()):
        raise TaskError(f"task run {run_id} is not waiting to start: it is {run.status} or another process has it")
    slot = checkpoint.Slot.at(
        ctx,
        repo=run.repo,
        path=Path(run.slot_path),
        lease_id=run.lease_id,
        lease_holder=run.lease_holder,
        base=run.base_branch,
        pool=run.pool,
    )
    # Before any git step: reconcile checks it for a `_task` that dies before putting a changed link back.
    tasks.set_link(ctx.conn, run_id, slot.link)
    log = logs.for_tick(run.tick_id)
    fields = {"task_run_id": run_id, "task": run.task_id}
    objects = task_runs.objects_dir(ctx, run_id)
    log.info("task run started", extra={**fields, "slot": run.slot_path, "repo": run.repo, "branch": run.branch})
    outcome = Outcome(TaskRunStatus.CRASHED, None, "the task run stopped before its worker finished")
    with stopping.StopOnSignal() as stop:
        try:
            tidy.make_objects(objects)
            outcome = _work(ctx, run, slot, objects=objects, out=out, log=log)
        except stopping.Stopped as e:
            outcome = Outcome(TaskRunStatus.CRASHED, None, str(e))
        except checkpoint.SetupError as e:
            outcome = Outcome(TaskRunStatus.CRASHED, None, str(e))
            log.error("task run setup failed", extra={**fields, "error": str(e)})  # noqa: TRY400
        except Exception as e:
            outcome = Outcome(TaskRunStatus.CRASHED, None, f"{type(e).__name__}: {e}")
            log.exception("task run failed", extra=fields)
        finally:
            # From here on a signal is ignored: returning the slot and closing the row must not be interrupted.
            stop.armed = False
            checkpoint.release(ctx, [slot], objects=objects, log=log, fields=fields)
            if not tasks.close_run(ctx.conn, run, outcome.status, outcome.result_json(), head=outcome.head):
                log.warning("task run was already closed; its outcome is not recorded", extra=fields)
            procs.drop_lifelock(Path(run.log_path))
            log.info("task run finished", extra={**fields, "status": outcome.status, "head": outcome.head})
    return outcome


def _work(
    ctx: Context,
    run: records.TaskRun,
    slot: checkpoint.Slot,
    *,
    objects: Path,
    out: TextIO,
    log: logs.TickAdapter,
) -> Outcome:
    """Check the slot out, run the task's worker, and verify its push.

    Returns:
        The worker's status; `stopped` for a task the operator stopped before its worker started; `timeout`, `unknown`
        for a missing or invalid result line, `unpushed` for commits the harness could not find on origin and could not
        push, or `crashed` for a worker that rewrote its slot's git.

    Raises:
        checkpoint.SetupError: the task is gone, no tracker tools are known for its worker, or a place the worker reads
            config from shadows canopy's definitions or names one of the tracker server's tools.
    """
    fields = {"task_run_id": run.id, "task": run.task_id}
    task = tasks.get(ctx.conn, run.task_id)
    if task is None:
        raise checkpoint.SetupError(f"task {run.task_id} is gone")
    if task.stopped_at is not None:
        log.info("task run not started", extra={**fields, "reason": "stopped"})
        return Outcome(TaskRunStatus.STOPPED, None, "the operator stopped the task before its worker started")
    start = checkpoint.check_out(slot, run.branch)
    run_env = f"{task_runs.RUN_ID_PREFIX}{run.id}"
    checkpoint.run_setup(ctx, slot, out, log, run_id=run_env, branch=run.branch, objects=objects, fields=fields)
    result, text = _run_agent(ctx, run, task, slot, objects=objects, out=out, log=log)
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes
    parsed = contract.last_line(TaskResult, text)
    if result.timed_out:
        status, note = TaskRunStatus.TIMEOUT, f"the worker timed out after {timeout_minutes} minutes"
    elif parsed is None:
        status, note = TaskRunStatus.UNKNOWN, "the worker's last line was not a valid result"
    else:
        status, note = TaskRunStatus(parsed.status), ""
    rewritten = slot.rewritten()
    if rewritten is not None:
        # The slot's git directory may be one the worker made: canopy runs no git in it.
        return Outcome(TaskRunStatus.CRASHED, parsed, f"the worker rewrote {rewritten}; nothing was checked or pushed")
    if tidy.used(objects):
        # A sandboxed worker's commits are only in the run's object directory (DESIGN §8).
        slot = slot.reading(ctx, objects)
    # Never with force: the branch has no base to keep up with, and a ticket may already cite its commits.
    unpushed = checkpoint.ensure_pushed(slot, run.branch, start, log, rebase=False)
    if unpushed:
        status, note = TaskRunStatus.UNPUSHED, unpushed
    head = checkpoint.remote_head(slot.git, run.branch) or None
    return Outcome(status, parsed, note, head=head)


def _run_agent(
    ctx: Context,
    run: records.TaskRun,
    task: records.Task,
    slot: checkpoint.Slot,
    *,
    objects: Path,
    out: TextIO,
    log: logs.TickAdapter,
) -> tuple[procs.Result, str]:
    """Run the private worker in the slot with the task's prompt, for the worker's timeout.

    The session and cost the runtime reported are recorded on the run at once, so a git step after the agent that
    fails does not lose them (DESIGN §13).

    Returns:
        The agent's process and the text its result line is read from.

    Raises:
        checkpoint.SetupError: no tracker tools are known for the private worker, or the slot's config shadows
            canopy's definitions or names one of the tracker server's tools.
    """
    tools = ctx.config.tracker.tools()
    if tools is None:
        raise checkpoint.SetupError("no tracker tools are known for the private worker; it did not start")
    # The runtime reads the worktree's config too (D044), and a private worker may call only the tracker's read tools.
    refused = project_config.refusal([slot.path], tracker_server=tools.server)
    if refused is not None:
        raise checkpoint.SetupError(refused)
    prompt = task_runs.prompt_file(ctx, run.id).read_text(encoding="utf-8")
    snapshot = definitions.ensure(ctx.state_dir, ctx.config)
    runtime = ctx.config.runtime
    argv = render_command(
        runtime.worker_template(runtime.private_worker_cmd),
        prompt,
        snapshot,
        task_runs.session_title(task),
    )
    timeout_minutes = runtime.worker_timeout_minutes
    fields = {"task_run_id": run.id, "task": run.task_id}
    log.info("running task worker", extra={**fields, "cmd": argv[0], "timeout_minutes": timeout_minutes})
    out.write("--- worker stdout ---\n")
    out.flush()
    # The operator's commands refuse inside canopy's own runs (DESIGN §22). A sandbox wrapper points git at the object
    # directory; an unsandboxed worker ignores it (DESIGN §8).
    env = {conversation.RUN_ID_ENV: f"{task_runs.RUN_ID_PREFIX}{run.id}", tidy.OBJECTS_ENV: str(objects)}
    watch = progress.Progress(ctx.conn, "task_runs", run.id, out, log, agent="task worker", fields=fields)
    result = ctx.runner.run(
        argv,
        cwd=slot.path,
        env=env,
        timeout=timeout_minutes * 60,
        on_start=lambda pid: db.set_agent_pid(ctx.conn, "task_runs", run.id, pid),
        on_line=watch,
    )
    out.write(f"\n--- worker stderr ---\n{result.stderr}\n")
    out.write(f"--- worker exit {result.returncode}{' (timed out)' if result.timed_out else ''} ---\n")
    out.flush()
    # Also after a timeout: whatever it printed before the kill names its session and what it had spent.
    output = stdout.read(result.stdout)
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
    return result, output.text
