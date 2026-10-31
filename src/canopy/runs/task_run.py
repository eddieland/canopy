"""`canopy _task <run_id>`: one run of a one-off task, in the slot the tick leased for it (DESIGN §36).

Checks out the task's branch at a detached HEAD, or the base before one is pushed, runs `runtime.private_worker_cmd`
with the task's prompt, parses the result line, verifies the push of the task's branch as a worker's run does, never
with force whatever `trust.rebase` says (`unpushed` when it cannot), records the head the branch is at on origin, and
tidies and returns the slot. The slot is returned on every exit path this process can see; a run whose `_task` died is
closed by reconcile, and one the operator stops with `--now` by `canopy stop` (`end`).

What the run leaves besides its branch: its report, `.canopy-task-report.md` at the slot's root, which git there
ignores, is kept in the state directory before the slot is returned, and the next run starts with a copy of the
latest; and the tickets its result's `created` names are checked on their text and recorded against the task
(`task_tickets`). The run writes nothing about any ticket: its row, its log, and its result name the task alone.

A run in a repository with a checklist is given it as a worker's run is (DESIGN §42): written to the run's answers
directory, beside its log, where canopy's `pre-push` reads it to hold the worker's push, and its result's `checklist`
held to it, a row recorded for every item however the run ended, `unanswered` for one its result left out.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from canopy.core import (
    agent_models,
    cards,
    checklist_answers,
    checklists,
    commit_hooks,
    contract,
    conversation,
    db,
    definitions,
    hostgit,
    plans,
    pools,
    progress,
    run_models,
    sandboxing,
)
from canopy.core.config import render_command
from canopy.core.vocab import RunStatus
from canopy.infra import logs, procs, stopping
from canopy.runs import attachments, checkpoint, follow_ups, task_tickets, tasks, tidy
from canopy.runs import task_starts as starts
from canopy.runs.checkpoint import SetupError
from canopy.runtime import project_config, servers, stdout

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
    # `created` is read apart, by `follow_ups.parse`, so a list of any shape refuses its entries, never the result.


@dataclass(frozen=True)
class Outcome:
    """How a task's run ended: its status, its validated result, the harness's note, and the head it left on origin."""

    status: RunStatus
    result: TaskResult | None
    note: str = ""
    head: str | None = None
    #: Its result's `created`, checked: the keys its close records against the task, and the entries refused.
    tickets: task_tickets.Checked = field(default_factory=task_tickets.Checked)
    #: What the worker answered of each item of its repository's list, checked (DESIGN §42); None when it got none.
    checklist: checklist_answers.Checked | None = None

    def result_json(self) -> str:
        """Return what `task_runs.result_json` stores: the validated result, the harness's note, and the refusals.

        Returns:
            The JSON, never the worker's output.
        """
        data: dict[str, object] = self.result.model_dump(mode="json") if self.result is not None else {}
        if self.note:
            data["harness"] = self.note
        data.update(self.tickets.stored())
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
            # Before the slot goes back, which removes the report from it (DESIGN §36).
            kept = keep_report(ctx, run, log)
            if kept:
                outcome = replace(outcome, note="; ".join(n for n in (outcome.note, kept) if n))
            release(ctx, run, link, log)
            stored = outcome.result_json()
            closed = tasks.close_run(
                ctx.conn,
                ctx.config,
                run_id,
                outcome.status,
                stored,
                head=outcome.head,
                tickets=outcome.tickets.recorded,
                checklist=outcome.checklist,
            )
            if not closed:
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
    if not tasks.close_run(ctx.conn, ctx.config, run.id, status, json.dumps({"harness": note}), head=None):
        # Its own `_task` closed it first, and returned its slot.
        return set()
    procs.drop_lifelock(Path(run.log_path))
    # A report the worker wrote is kept however its run ended; why one was not is in the log alone.
    keep_report(ctx, run, log)
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


def keep_report(ctx: Context, run: records.TaskRun, log: logs.TickAdapter) -> str:
    """Keep the report the run's worker left at its slot's root, `<state_dir>/tasks/<task>/<run>.md` (DESIGN §36).

    The report is read bounded and never through a link, as a plan is (§25), and its hash recorded on the run. It is
    kept as the worker left it, also when that is the copy it started with. Never raises: the slot is returned after.

    Returns:
        A harness note when there was a file that could not be kept, else "": none was left, or it was kept.
    """
    reading = plans.read(Path(run.slot_path) / tasks.REPORT)
    fields = {"task_run_id": run.id, "task": run.task_id}
    if reading.problem in {"missing", "empty"}:
        return ""
    if reading.text is None:
        log.warning("task's report not kept", extra={**fields, "problem": reading.problem})
        return f"its {tasks.REPORT} is {reading.problem}, so it was not kept"
    try:
        written = tasks.keep_report(ctx.state_dir, run.task_id, run.id, reading.text)
    except (plans.PlanFileError, OSError) as e:
        log.error("task's report not kept", extra={**fields, "error": str(e)})  # noqa: TRY400  (no traceback)
        return f"its {tasks.REPORT} was not kept: {e}"
    tasks.set_report(ctx.conn, run.id, written.sha256)
    log.info("task's report kept", extra={**fields, "size": written.size})
    return ""


def release(ctx: Context, run: records.TaskRun, link: bytes | None, log: logs.TickAdapter) -> None:
    """Remove the report from the run's slot, tidy it as a worker run's is (DESIGN §8), and return it.

    The run's answers directory, which holds its checklist (§42), is removed first, and its object directory last. A
    slot that could not be tidied is not returned, and the object directory is kept, so its objects can be read.
    """
    fields = {"task_run_id": run.id, "slot": run.slot_path, "lease_id": run.lease_id, "repo": run.repo}
    slot = Path(run.slot_path)
    try:
        # Never followed: a link in its place is removed, not what it names.
        (slot / tasks.REPORT).unlink(missing_ok=True)
    except OSError as e:
        # A directory a worker made in its place: it is no report canopy wrote, and the next copy refuses it.
        log.warning("task's report not removed from its slot", extra={**fields, "error": str(e)})
    cards.remove_answers(starts.answers_dir(Path(run.log_path)))
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
        SetupError: a git step failed, the runtime's config where it runs shadows canopy's definitions, or the
            repository's checklist can no longer be used or written.
    """
    task = tasks.get(ctx.conn, run.task_id)
    if task is None or task.stopped_at is not None:
        note = "the operator stopped the task before its worker started"
        log.info("task run not started", extra={"task_run_id": run.id, "reason": note})
        return Outcome(RunStatus.STOPPED, None, note)
    _write_checklist(ctx, run)
    slot = Path(run.slot_path)
    git = checkpoint.Git(ctx.runner, slot, run.repo)
    start = checkpoint.check_out(git, run.base_branch, run.branch)
    _place_report(ctx, git, run, log)
    _place_attachments(ctx, git, run, log)
    marks = _marks(ctx)
    done, text = _run_agent(ctx, run, task, out, log, marks=marks)
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes
    parsed = contract.last_line(TaskResult, text)
    # Read only from a valid result line, and recorded however the run ends: an item it was given and did not answer is
    # counted unanswered (DESIGN §42).
    listed = _check_checklist(run, text if parsed is not None else "")
    if done.timed_out:
        status, note = RunStatus.TIMEOUT, f"the worker timed out after {timeout_minutes} minutes"
    elif parsed is None:
        status, note = RunStatus.UNKNOWN, "the worker's last line was not a valid result"
    else:
        status, note = RunStatus(parsed.status), ""
    # Each entry checked alone, on its text (D003), whatever the rest of the result says.
    tickets = task_tickets.check(
        follow_ups.parse(text),
        project=task.project,
        limit=ctx.config.policy.max_follow_ups,
    )
    note = "; ".join(n for n in (note, tickets.note()) if n)
    rewritten = _rewritten(slot, link)
    if rewritten is not None:
        # The slot's git directory may be one the worker made: canopy runs no git in it.
        crashed = f"the worker rewrote {rewritten}; nothing was checked or pushed"
        noted = "; ".join(n for n in (crashed, tickets.note()) if n)
        return Outcome(RunStatus.CRASHED, parsed, noted, tickets=tickets, checklist=listed)
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
    note = "; ".join(n for n in (note, *checkpoint.unmarked(git, run.branch, start, run.base_branch, marks)) if n)
    if listed is not None:
        note = "; ".join(n for n in (note, listed.note()) if n)
    return Outcome(status, parsed, note, head=head, tickets=tickets, checklist=listed)


def _write_checklist(ctx: Context, run: records.TaskRun) -> None:
    """Write the list of the run's repository, if it has one, to the run's answers directory, for canopy's hook (§42).

    A run in a repository without a list gets no directory, and is never held.

    Raises:
        SetupError: the list cannot be used or written: the tick read it to render the prompt, so it changed since, and
            the run never runs without it.
    """
    try:
        lists = checklists.for_repos(ctx.config, [run.repo])
        if lists:
            answers = starts.answers_dir(Path(run.log_path))
            cards.make_answers(answers)
            checklists.write(answers, lists)
    except (checklists.ChecklistError, OSError) as e:
        raise SetupError(str(e)) from e


def _check_checklist(run: records.TaskRun, text: str) -> checklist_answers.Checked | None:
    """Check what the worker answered of the list it was given, read back from the run's answers directory (§42).

    `text` is its output, or "" when its last line was no valid result, whose fields are not read.

    Returns:
        An answer for every item of the list; None for a run given none.
    """
    lists = checklists.given(starts.answers_dir(Path(run.log_path)), [run.repo])
    if not lists:
        return None
    return checklist_answers.check(lists, checklist_answers.parse(text) if text else None)


def _marks(ctx: Context) -> commit_hooks.Marks:
    # As the prompt names them: the private worker's chosen model, which canopy writes into its definition, and no
    # ticket's key, since a task has none (§36).
    model = agent_models.of_template(ctx.config.runtime.models, ctx.config.runtime.private_worker_cmd)
    return commit_hooks.marks(ctx.config, key=None, model=model.name if model is not None else None)


def _place_report(ctx: Context, git: checkpoint.Git, run: records.TaskRun, log: logs.TickAdapter) -> None:
    """Have git ignore the slot's report, and put a copy of the task's latest report there, if it has one (§36).

    Raises:
        SetupError: the exclude file or the copy could not be written.
    """
    checkpoint.ignore(git, tasks.REPORT)
    latest = tasks.latest_report(ctx.conn, ctx.state_dir, run.task_id)
    if latest is None:
        return
    earlier, text = latest
    try:
        logs.write_private(Path(run.slot_path) / tasks.REPORT, text)
    except OSError as e:
        raise SetupError(f"{git.where}could not write the copy of the task's report: {e}") from e
    log.info("task's latest report copied in", extra={"task_run_id": run.id, "from_run": earlier.id})


def _place_attachments(ctx: Context, git: checkpoint.Git, run: records.TaskRun, log: logs.TickAdapter) -> None:
    """Copy the attachments the run's prompt names, and the task still holds, into the slot, which git ignores (§22).

    Raises:
        SetupError: an attachment's file is gone or changed since it was attached, so the worker gets none of them; or
            the exclude file or a copy could not be written.
    """
    ref = conversation.Ref(conversation.TASK, str(run.task_id))
    try:
        found = attachments.copies(ctx.conn, ctx.state_dir, ref, run.started_at)
    except attachments.AttachmentFileError as e:
        raise SetupError(f"{e}; the worker did not start") from e
    if not found:
        return
    checkpoint.ignore(git, attachments.RUN_DIR)
    try:
        attachments.place(Path(run.slot_path) / attachments.RUN_DIR, found)
    except OSError as e:
        raise SetupError(f"{git.where}could not write the attachments' copies: {e}") from e
    log.info("task's attachments copied in", extra={"task_run_id": run.id, "attachments": len(found)})


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
    *,
    marks: commit_hooks.Marks,
) -> tuple[procs.Result, str]:
    """Run the private worker's command in the slot with the task's prompt, for the worker's timeout.

    The private worker's definition is the one that writes nothing to a ticket (DESIGN §22), so the slot's config must
    name none of the tracker server's tools either. The session, cost, and tool calls the runtime reported are recorded
    at once. canopy's git hooks put `marks` on every commit the worker makes (`commit_hooks`), and hold its push for
    its repository's checklist, when the run has one (DESIGN §42).

    Returns:
        The agent's process and the text its result line is read from.

    Raises:
        SetupError: the runtime's config in the slot shadows canopy's definitions or names a tracker tool.
    """
    slot = Path(run.slot_path)
    tools = ctx.config.tracker.tools()
    refused = project_config.refusal(
        [slot],
        version=ctx.config.runtime.version,
        tracker_server=tools.server if tools is not None else None,
    )
    if refused is not None:
        raise SetupError(refused)
    prompt = starts.prompt_file(Path(run.log_path)).read_text(encoding="utf-8")
    runtime = ctx.config.runtime
    # The prompt's fixed instructions are its agent's body, in a snapshot every task's run shares (DESIGN §13).
    bodies, message = definitions.run_prompt(prompt, runtime.private_worker_cmd)
    snapshot = definitions.ensure(ctx.state_dir, ctx.config, bodies=bodies)
    command = render_command(runtime.worker_template(runtime.private_worker_cmd), message, snapshot, f"task:{task.id}")
    argv = sandboxing.wrap(runtime, [run.repo], "worker", command.argv, snapshot)
    timeout_minutes = runtime.worker_timeout_minutes
    log.info(
        "running the task's worker",
        extra={"task_run_id": run.id, "cmd": argv[0], "cwd": str(slot), "timeout_minutes": timeout_minutes},
    )
    out.write("--- worker stdout ---\n")
    out.flush()
    objects = starts.objects_dir(Path(run.log_path))
    env = {conversation.RUN_ID_ENV: f"{RUN_ID_PREFIX}{run.id}", tidy.OBJECTS_ENV: str(objects)}
    # It says where its work stands through canopy's `status` tool, which writes nothing, and asks no question there:
    # its question is its final line's, which a reply to the task answers (DESIGN §36, §41).
    served = {cards.SERVER: cards.SERVER_COMMAND}
    env |= servers.env(served, version=ctx.config.runtime.version, cwd=ctx.workspace.root.absolute())
    answers = starts.answers_dir(Path(run.log_path))
    listed = checklists.file_of(answers, run.repo)
    held = {slot: listed} if listed.is_file() else {}
    if held:
        # Where canopy's `pre-push` reads the list, which a sandboxed run may read and not write (DESIGN §24, §42).
        env[cards.ANSWERS_ENV] = str(answers)
    env |= commit_hooks.env(snapshot, marks, os.environ, held)
    done = ctx.runner.run(
        argv,
        cwd=slot,
        env=env,
        stdin=command.stdin,
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
            version=ctx.config.runtime.version,
        ),
    )
    out.write(f"\n--- worker stderr ---\n{done.stderr}\n")
    out.write(f"--- worker exit {done.returncode}{' (timed out)' if done.timed_out else ''} ---\n")
    out.flush()
    # Also after a timeout: whatever it printed before the kill names its session and what it had spent.
    output = stdout.read(done.stdout, version=ctx.config.runtime.version)
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
