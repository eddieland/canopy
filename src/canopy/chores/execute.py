"""`canopy _chore <run_id>`, and `canopy chore try` in the foreground: one chore run (DESIGN §19).

Claims the run, runs the chore's command in its working directory with its timeout, parses the result line, and closes
the `chore_runs` row. There is no lease, branch, or push, so there is nothing to return or verify. The row is closed on
every exit path this process can see; SIGKILL cannot be caught, and reconcile finds that run's dead pid next tick.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from canopy.chores import start
from canopy.core import agent_output, conversation, db, definitions, outbox
from canopy.core import chore_result as result
from canopy.core import chore_view as view
from canopy.core.config import render_command
from canopy.infra import logs, procs, stopping

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.config import Chore
    from canopy.core.context import Context


class ChoreError(Exception):
    """`_chore` cannot start this run at all: it does not exist or is not waiting to start."""


class SetupError(Exception):
    """Something before the agent ran failed."""


@dataclass(frozen=True)
class Printed:
    """What a chore's agent printed: its output as read, its stderr, and its exit code."""

    output: agent_output.AgentOutput
    stderr: str
    returncode: int


@dataclass(frozen=True)
class Outcome:
    """How a chore run ended: its status and the validated result, with a note when the harness decided the status.

    `printed` is what the agent printed, None when the run ended before its agent did.
    """

    status: str
    result: result.ChoreResult | None
    note: str = ""
    printed: Printed | None = None

    def result_json(self) -> str:
        """Return what `chore_runs.result_json` stores: the validated result and the harness's note, never output."""
        data: dict[str, object] = self.result.model_dump() if self.result is not None else {}
        if self.note:
            data["harness"] = self.note
        return json.dumps(data)


def execute(ctx: Context, run_id: int, *, out: TextIO) -> Outcome:
    """Do chore run `run_id` from claiming it to closing its row. The agent's output is written to `out`, the run log.

    Returns:
        How the run ended, recorded on its row unless it was already closed. A failure after the claim is `crashed`.

    Raises:
        ChoreError: the run does not exist or is not waiting to start, for example because another `_chore` has it.
    """
    run = db.get_chore_run(ctx.conn, run_id)
    if run is None:
        raise ChoreError(f"no chore run {run_id}")
    if not db.claim_chore_run(ctx.conn, run_id, os.getpid()):
        raise ChoreError(f"chore run {run_id} is not waiting to start: it is {run['status']} or another process has it")
    log = logs.for_tick(int(run["tick_id"]) if run["tick_id"] is not None else None)
    fields = {"chore_run_id": run_id, "chore": run["chore"]}
    log.info("chore run started", extra=fields)
    outcome = Outcome("crashed", None, "the chore run stopped before its agent finished")
    with stopping.StopOnSignal() as stop:
        try:
            outcome = _work(ctx, run, out, log)
        except stopping.Stopped as e:
            outcome = Outcome("crashed", None, str(e))
        except SetupError as e:
            outcome = Outcome("crashed", None, str(e))
            log.error("chore run not started", extra={**fields, "error": str(e)})  # noqa: TRY400
        except Exception as e:
            outcome = Outcome("crashed", None, f"{type(e).__name__}: {e}")
            log.exception("chore run failed", extra=fields)
        finally:
            stop.armed = False
            stored = outcome.result_json()
            ended = outbox.chore_ended(ctx.config, run, outcome.status, stored)
            if not db.finish_chore_run(ctx.conn, run_id, outcome.status, stored, event=ended):
                log.warning("chore run was already closed; its outcome is not recorded", extra=fields)
            procs.drop_lifelock(Path(run["log_path"]))
            log.info("chore run finished", extra={**fields, "status": outcome.status})
    return outcome


def prepare(ctx: Context, name: str, chore: Chore, prompt: str) -> tuple[Path, list[str]]:
    """Return where chore `name` runs and the command that runs it with `prompt`.

    Raises:
        SetupError: its `cwd` is not a directory, or OpenCode config there or above shadows one of canopy's agents.
    """
    cwd = _cwd(ctx, name, chore)
    # The shipped `canopy-chore` is merged with whatever OpenCode config its working directory has (D044), and OpenCode
    # reads project config from the directories above it too.
    here = cwd.resolve()
    shadowing = [found for d in (here, *here.parents) for found in definitions.shadowing(d)]
    if shadowing:
        raise SetupError(definitions.shadowing_message(shadowing))
    template = chore.cmd if chore.cmd is not None else ctx.config.runtime.chore_cmd
    return cwd, render_command(template, prompt, definitions.ensure(ctx.state_dir, ctx.config), f"chore:{name}")


def outcome_of(done: procs.Result, output: agent_output.AgentOutput, chore: Chore) -> Outcome:
    """Return how a chore's agent ended: timed out, its validated result from `output`, or `unknown` without one."""
    printed = Printed(output, done.stderr, done.returncode)
    if done.timed_out:
        return Outcome("timeout", None, f"the chore timed out after {chore.timeout_minutes} minutes", printed)
    parsed = result.parse(output.text)
    if parsed is None:
        note = "the chore's last line was not a valid result; its findings are not recorded"
        return Outcome("unknown", None, note, printed)
    return Outcome(parsed.status, parsed, printed=printed)


def _work(ctx: Context, run: sqlite3.Row, out: TextIO, log: logs.TickAdapter) -> Outcome:
    name = str(run["chore"])
    # Read the config this process loaded: a chore deleted since its run started does not run. The overseer's run
    # needs it configured; the operator's try, with no tick, only defined, as `canopy chore try` checked.
    chores = view.configured if run["tick_id"] is not None else view.defined
    chore = chores(ctx.config, ctx.workspace).get(name)
    if chore is None:
        raise SetupError(f"chore {name} is no longer configured for this workspace")
    run_id = int(run["id"])
    # Beside the row's log, so a run started before an upgrade moved the directory still finds its prompt.
    prompt = start.prompt_file(Path(run["log_path"])).read_text(encoding="utf-8")
    cwd, argv = prepare(ctx, name, chore, prompt)
    log.info(
        "running chore",
        extra={"chore_run_id": run_id, "cmd": argv[0], "cwd": str(cwd), "timeout_minutes": chore.timeout_minutes},
    )
    done = ctx.runner.run(
        argv,
        cwd=cwd,
        # The operator's commands refuse inside canopy's own runs (DESIGN §22).
        env={conversation.RUN_ID_ENV: f"chore-{run_id}"},
        timeout=chore.timeout_minutes * 60,
        on_start=lambda pid: db.set_chore_agent_pid(ctx.conn, run_id, pid),
    )
    out.write(f"--- chore stdout ---\n{done.stdout}\n--- chore stderr ---\n{done.stderr}\n")
    out.write(f"--- chore exit {done.returncode}{' (timed out)' if done.timed_out else ''} ---\n")
    out.flush()
    output = agent_output.read(done.stdout)
    if output.session_id is not None or output.usage is not None:
        db.set_chore_run_report(ctx.conn, run_id, output.session_id, output.usage)
        spent = {"cost_usd": output.usage.cost_usd, "tokens": output.usage.tokens} if output.usage else {}
        log.info("chore reported", extra={"chore_run_id": run_id, "session_id": output.session_id, **spent})
    return outcome_of(done, output, chore)


def _cwd(ctx: Context, name: str, chore: Chore) -> Path:
    """The chore's working directory: its `cwd`, or a directory of its own that only the operator can read.

    Returns:
        The chore's `cwd` when it sets one, else its own directory, made if it is missing.

    Raises:
        SetupError: its `cwd` is not a directory.
    """
    if chore.cwd is not None:
        if not chore.cwd.is_dir():
            raise SetupError(f"chore {name}'s cwd {chore.cwd} is not a directory")
        return chore.cwd
    cwd = start.default_cwd(ctx, name)
    cwd.mkdir(mode=0o700, exist_ok=True)
    return cwd
