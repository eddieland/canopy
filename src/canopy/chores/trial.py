"""`canopy chore try`: a run of a chore the operator starts by hand, in the foreground or from the web UI (DESIGN §19).

For writing a chore, and for running one now. A try is a chore run like the overseer's: it has a `chore_runs` row with
no tick, its findings reach the attention list and notifications, and the chore's next run is due counting from it. It
runs in this process, through `execute.execute`, as `_chore` would; the web UI's is recorded and runs in a `_chore`
of its own (`detach`). Unrecorded, it writes nothing to the journal, so a half-written prompt cannot clear real
findings. Either way it gets the prompt a run starting now would get, and only the `running` guard applies, to a
recorded try: the operator runs it by hand, as they could run the command, so it does not wait for `every_minutes` or
the chore's hours, and works with `max_chores` 0.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.chores import execute, history, start
from canopy.core import chore_runs, conversation, db, notice, outbox, prompts
from canopy.core import chore_view as view
from canopy.core.vocab import ChoreRunStatus
from canopy.infra import lock, logs, procs
from canopy.runtime import stdout

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.config import Chore, Rendered
    from canopy.core.context import Context


class TrialError(Exception):
    """The chore cannot be tried: it is not defined here, it is running, or something before its agent failed."""


class RunningError(TrialError):
    """A recorded try cannot start: a run of the chore is running. One that records nothing can."""


@dataclass(frozen=True)
class Recorded:
    """A recorded try: its chore run's id, and the fd that holds its lifelock while this process does the run."""

    run_id: int
    lifelock: int


@dataclass(frozen=True)
class Prepared:
    """A chore ready to try: its definition, its prompt as `start.read_body` gives it, where it runs, its command."""

    name: str
    chore: Chore
    body: str
    context: str | None
    cwd: Path
    command: Rendered


def prepare(ctx: Context, name: str, context: str | None) -> Prepared:
    """Render chore `name`'s prompt as a run starting now would get it, and the command that runs it.

    Returns:
        The chore's definition and prompt, the directory it runs in, and the command with the rendered prompt.

    Raises:
        TrialError: no such chore for this workspace, its prompt or the standing instructions to chores cannot be read,
            or its working directory is unusable.
    """
    chore = view.defined(ctx.config, ctx.workspace).get(name)
    if chore is None:
        raise TrialError(f"no chore named {name!r} is defined for this workspace")
    try:
        body = start.read_body(ctx.config, chore)
    except prompts.PromptError as e:
        raise TrialError(str(e)) from e
    state = view.state_of(ctx.conn, name, chore)
    prompt = start.render(
        body,
        state,
        None,
        context,
        conversation.chore_notes(ctx.conn, name),
        held=notice.for_prompt(ctx.conn),
    )
    try:
        cwd, command, _ = execute.prepare(ctx, name, chore, prompt)
    except execute.SetupError as e:
        raise TrialError(str(e)) from e
    return Prepared(name, chore, body, context, cwd, command)


def record(ctx: Context, prepared: Prepared) -> Recorded:
    """Record the prepared try as a chore run with no tick, held by this process, and write its prompt.

    Serialized with the overseer's chore runs by the dispatch lock, so a try and a run of the same chore never overlap.
    This process takes the run's lifelock, as `spawn` does for `_chore`, so reconcile sees the run alive until it ends.

    Returns:
        The new chore run's id and the fd holding its lifelock, for `run_recorded` to release.

    Raises:
        RunningError: a run of the chore is running.
        TrialError: the run's lifelock or prompt could not be written; the new run then ends `crashed`.
    """
    name = prepared.name
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        running = next((r for r in db.running_runs(ctx.conn, "chore_runs") if r["chore"] == name), None)
        if running is not None:
            raise RunningError(f"chore run {running['id']} of {name} is running")
        state = view.state_of(ctx.conn, name, prepared.chore)
        run_id = chore_runs.insert_chore_run(
            ctx.conn,
            tick_id=None,
            chore=name,
            logs_dir=start.runs_dir(ctx, name),
            model=start.asked_model(ctx.config, prepared.chore),
        )
        run = chore_runs.get_chore_run(ctx.conn, run_id)
        if run is None:
            raise TrialError(f"chore run {run_id} vanished")
        log_path = Path(run.log_path)
        try:
            held = lock.take(procs.lifelock(log_path))
        except (OSError, lock.LockBusyError) as e:
            raise TrialError(_crash(ctx, run, e)) from e
        try:
            db.claim_run(ctx.conn, "chore_runs", run_id, os.getpid())
            notes = conversation.chore_notes(ctx.conn, name)
            prompt = start.render(
                prepared.body,
                state,
                run_id,
                prepared.context,
                notes,
                held=notice.for_prompt(ctx.conn),
            )
            logs.write_private(start.prompt_file(log_path), prompt)
        except OSError as e:
            os.close(held)
            error = _crash(ctx, run, e)
            procs.drop_lifelock(log_path)
            raise TrialError(error) from e
    return Recorded(run_id, held)


def detach(ctx: Context, prepared: Prepared) -> start.Started:
    """Record the prepared try as a chore run with no tick, and spawn `canopy _chore` to do it, as the overseer's are.

    The web UI's try (DESIGN §22): a request cannot wait out the chore's timeout, so the run goes on in the background
    and the chore's page shows it. It is a recorded try in every other way, with the same `running` guard, serialized
    with the overseer's chore runs by the dispatch lock.

    Returns:
        The new chore run's id and the pid of its `canopy _chore`.

    Raises:
        RunningError: a run of the chore is running.
        TrialError: the run's prompt could not be written or its process started; the new run then ends `crashed`.
    """
    name = prepared.name
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        running = next((r for r in db.running_runs(ctx.conn, "chore_runs") if r["chore"] == name), None)
        if running is not None:
            raise RunningError(f"chore run {running['id']} of {name} is running")
        state = view.state_of(ctx.conn, name, prepared.chore)
        try:
            return start.launch(ctx, tick_id=None, state=state, body=prepared.body, context=prepared.context)
        except start.Refusal as e:
            raise TrialError(f"could not start the try: {e.reason}") from e


def run_recorded(ctx: Context, recorded: Recorded) -> execute.Outcome:
    """Do a recorded try as `_chore` would, from claiming it to closing its row, then let its lifelock go.

    Returns:
        How the run ended, recorded on its row. A failure after the claim is `crashed`.

    Raises:
        execute.ChoreError: the run is not this process's to do, for example because reconcile closed it.
    """
    try:
        run = chore_runs.get_chore_run(ctx.conn, recorded.run_id)
        if run is None:
            raise execute.ChoreError(f"no chore run {recorded.run_id}")
        # Opened as `spawn` opens a detached run's log: appended, readable only by the operator, never through a link.
        fd = os.open(Path(run.log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as out:
            return execute.execute(ctx, recorded.run_id, out=out)
    finally:
        os.close(recorded.lifelock)


def run_unrecorded(ctx: Context, prepared: Prepared) -> execute.Outcome:
    """Run the prepared chore to the end or its timeout, read its result as `_chore` would, and record nothing.

    Returns:
        The harness's outcome, `timeout` or `unknown` when there is no valid result, with what the agent printed.
    """
    done = ctx.runner.run(
        prepared.command.argv,
        cwd=prepared.cwd,
        stdin=prepared.command.stdin,
        # What its agent sees as CANOPY_RUN_ID, so the operator's commands refuse inside it (DESIGN §22), and names the
        # chore, whose history it reads with no run row to find it from. A recorded try's is `chore-<run id>`.
        env=history.run_env(ctx, f"{history.TRY_PREFIX}{prepared.name}"),
        timeout=prepared.chore.timeout_minutes * 60,
    )
    return execute.outcome_of(done, stdout.read(done.stdout, version=ctx.config.runtime.version), prepared.chore)


def _crash(ctx: Context, run: records.ChoreRun, e: Exception) -> str:
    """Close a recorded try that could not start as `crashed`, as `start` closes a run it could not spawn.

    Returns:
        What went wrong, for the error the caller raises.
    """
    note = json.dumps({"harness": f"could not start the try: {e}"})
    ended = outbox.chore_ended(ctx.config, run.chore, run.id, ChoreRunStatus.CRASHED, note)
    db.finish_run(ctx.conn, "chore_runs", run.id, ChoreRunStatus.CRASHED, note, event=ended)
    return f"chore run {run.id} could not start: {e}"
