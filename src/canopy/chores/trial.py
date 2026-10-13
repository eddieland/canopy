"""`canopy chore try`: a run of a chore the operator starts by hand, in the foreground (DESIGN §19).

For writing a chore, and for running one now. A try is a chore run like the overseer's: it has a `chore_runs` row with
no tick, its findings reach the attention list and notifications, and the chore's next run is due counting from it. It
runs in this process, through `execute.execute`, as `_chore` would. Unrecorded, it writes nothing to the journal, so a
half-written prompt cannot clear real findings. Either way it gets the prompt a run starting now would get, and only the
`running` guard applies, to a recorded try: the operator runs it by hand, as they could run the command, so it does not
wait for `every_minutes` or the chore's hours, and works with `max_chores` 0.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.chores import execute, start
from canopy.core import agent_output, conversation, db, outbox
from canopy.core import chore_view as view
from canopy.infra import lock, logs, procs

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.config import Chore
    from canopy.core.context import Context

# What an unrecorded try's agent sees as CANOPY_RUN_ID, so the operator's commands refuse inside it (DESIGN §22). A
# recorded one's is `chore-<run id>`, as any chore run's.
RUN_ID = "chore-try"


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
    """A chore ready to try: its definition and prompt file's text, where it runs, and an unrecorded try's command."""

    name: str
    chore: Chore
    body: str
    context: str | None
    cwd: Path
    argv: list[str]


def prepare(ctx: Context, name: str, context: str | None) -> Prepared:
    """Render chore `name`'s prompt as a run starting now would get it, and the command that runs it.

    Returns:
        The chore's definition and prompt, the directory it runs in, and the command with the rendered prompt.

    Raises:
        TrialError: no such chore for this workspace, its prompt cannot be read, or its working directory is unusable.
    """
    chore = view.defined(ctx.config, ctx.workspace).get(name)
    if chore is None:
        raise TrialError(f"no chore named {name!r} is defined for this workspace")
    try:
        body = chore.prompt.read_text(encoding="utf-8").rstrip("\n")
    except OSError as e:
        raise TrialError(f"cannot read {chore.prompt}: {e.strerror}") from e
    state = view.state_of(ctx.conn, name, chore)
    prompt = start.render(body, state, None, context, conversation.chore_notes(ctx.conn, name))
    try:
        cwd, argv = execute.prepare(ctx, name, chore, prompt)
    except execute.SetupError as e:
        raise TrialError(str(e)) from e
    return Prepared(name, chore, body, context, cwd, argv)


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
        running = next((r for r in db.running_chore_runs(ctx.conn) if r["chore"] == name), None)
        if running is not None:
            raise RunningError(f"chore run {running['id']} of {name} is running")
        state = view.state_of(ctx.conn, name, prepared.chore)
        run_id = db.insert_chore_run(ctx.conn, tick_id=None, chore=name, logs_dir=start.runs_dir(ctx, name))
        run = db.get_chore_run(ctx.conn, run_id)
        if run is None:
            raise TrialError(f"chore run {run_id} vanished")
        log_path = Path(run["log_path"])
        try:
            held = lock.take(procs.lifelock(log_path))
        except (OSError, lock.LockBusyError) as e:
            raise TrialError(_crash(ctx, run, e)) from e
        try:
            db.claim_chore_run(ctx.conn, run_id, os.getpid())
            notes = conversation.chore_notes(ctx.conn, name)
            prompt = start.render(prepared.body, state, run_id, prepared.context, notes)
            logs.write_private(start.prompt_file(log_path), prompt)
        except OSError as e:
            os.close(held)
            raise TrialError(_crash(ctx, run, e)) from e
    return Recorded(run_id, held)


def run_recorded(ctx: Context, recorded: Recorded) -> execute.Outcome:
    """Do a recorded try as `_chore` would, from claiming it to closing its row, then let its lifelock go.

    Returns:
        How the run ended, recorded on its row. A failure after the claim is `crashed`.

    Raises:
        execute.ChoreError: the run is not this process's to do, for example because reconcile closed it.
    """
    try:
        run = db.get_chore_run(ctx.conn, recorded.run_id)
        if run is None:
            raise execute.ChoreError(f"no chore run {recorded.run_id}")
        # Opened as `spawn` opens a detached run's log: appended, readable only by the operator, never through a link.
        fd = os.open(Path(run["log_path"]), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
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
        prepared.argv,
        cwd=prepared.cwd,
        env={conversation.RUN_ID_ENV: RUN_ID},
        timeout=prepared.chore.timeout_minutes * 60,
    )
    return execute.outcome_of(done, agent_output.read(done.stdout), prepared.chore)


def _crash(ctx: Context, run: sqlite3.Row, e: Exception) -> str:
    """Close a recorded try that could not start as `crashed`, as `start` closes a run it could not spawn.

    Returns:
        What went wrong, for the error the caller raises.
    """
    note = json.dumps({"harness": f"could not start the try: {e}"})
    ended = outbox.chore_ended(ctx.config, run, "crashed", note)
    db.finish_chore_run(ctx.conn, int(run["id"]), "crashed", note, event=ended)
    return f"chore run {run['id']} could not start: {e}"
