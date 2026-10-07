"""`canopy _chore <run_id>`: one chore run (DESIGN §19).

Claims the run, runs the chore's command in its working directory with its timeout, parses the result line, and closes
the `chore_runs` row. There is no lease, branch, or push, so there is nothing to return or verify. The row is closed on
every exit path this process can see; SIGKILL cannot be caught, and reconcile finds that run's dead pid next tick.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, TextIO

from canopy.chores import result, start, view
from canopy.core import db, definitions, outbox
from canopy.core.config import render_command
from canopy.infra import logs, stopping

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from canopy.core.config import Chore
    from canopy.core.context import Context


class ChoreError(Exception):
    """`_chore` cannot start this run at all: it does not exist or is not waiting to start."""


class _SetupError(Exception):
    """Something before the agent ran failed."""


@dataclass(frozen=True)
class Outcome:
    """How a chore run ended: its status and the validated result, with a note when the harness decided the status."""

    status: str
    result: result.ChoreResult | None
    note: str = ""

    def result_json(self) -> str:
        """Return what `chore_runs.result_json` stores: the validated result and the harness's note, never output."""
        data: dict[str, object] = self.result.model_dump() if self.result is not None else {}
        if self.note:
            data["harness"] = self.note
        return json.dumps(data)


def execute(ctx: Context, run_id: int, *, out: TextIO) -> Outcome:
    """Do chore run `run_id` from claiming it to closing its row. The agent's output is written to `out`, the run log.

    Raises:
        ChoreError: the run does not exist or is not waiting to start, for example because another `_chore` has it.
    """
    run = db.get_chore_run(ctx.conn, run_id)
    if run is None:
        raise ChoreError(f"no chore run {run_id}")
    if not db.claim_chore_run(ctx.conn, run_id, os.getpid()):
        raise ChoreError(f"chore run {run_id} is not waiting to start: it is {run['status']} or another process has it")
    log = logs.for_tick(int(run["tick_id"]))
    fields = {"chore_run_id": run_id, "chore": run["chore"]}
    log.info("chore run started", extra=fields)
    outcome = Outcome("crashed", None, "the chore run stopped before its agent finished")
    with stopping.StopOnSignal() as stop:
        try:
            outcome = _work(ctx, run, out, log)
        except stopping.Stopped as e:
            outcome = Outcome("crashed", None, str(e))
        except _SetupError as e:
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
            log.info("chore run finished", extra={**fields, "status": outcome.status})
    return outcome


def _work(ctx: Context, run: sqlite3.Row, out: TextIO, log: logs.TickAdapter) -> Outcome:
    name = str(run["chore"])
    # Read the config this process loaded: a chore deleted since `chore run` started it does not run.
    chore = view.configured(ctx.config, ctx.workspace).get(name)
    if chore is None:
        raise _SetupError(f"chore {name} is no longer configured for this workspace")
    cwd = _cwd(ctx, name, chore)
    # The shipped `canopy-chore` is merged with whatever OpenCode config its working directory has (D044).
    shadowing = definitions.shadowing(cwd)
    if shadowing:
        raise _SetupError(definitions.shadowing_message(shadowing))
    prompt = start.prompt_file(ctx, int(run["id"])).read_text(encoding="utf-8")
    template = chore.cmd if chore.cmd is not None else ctx.config.runtime.chore_cmd
    argv = render_command(template, prompt, definitions.ensure(ctx.state_dir))
    log.info(
        "running chore",
        extra={"chore_run_id": run["id"], "cmd": argv[0], "cwd": str(cwd), "timeout_minutes": chore.timeout_minutes},
    )
    run_id = int(run["id"])
    done = ctx.runner.run(
        argv,
        cwd=cwd,
        timeout=chore.timeout_minutes * 60,
        on_start=lambda pid: db.set_chore_agent_pid(ctx.conn, run_id, pid),
    )
    out.write(f"--- chore stdout ---\n{done.stdout}\n--- chore stderr ---\n{done.stderr}\n")
    out.write(f"--- chore exit {done.returncode}{' (timed out)' if done.timed_out else ''} ---\n")
    out.flush()
    if done.timed_out:
        return Outcome("timeout", None, f"the chore timed out after {chore.timeout_minutes} minutes")
    parsed = result.parse(done.stdout)
    if parsed is None:
        return Outcome("unknown", None, "the chore's last line was not a valid result; its findings are not recorded")
    return Outcome(parsed.status, parsed)


def _cwd(ctx: Context, name: str, chore: Chore) -> Path:
    """The chore's working directory: its `cwd`, or a directory of its own that only the operator can read."""
    if chore.cwd is not None:
        if not chore.cwd.is_dir():
            raise _SetupError(f"chore {name}'s cwd {chore.cwd} is not a directory")
        return chore.cwd
    cwd = start.default_cwd(ctx, name)
    cwd.mkdir(mode=0o700, exist_ok=True)
    return cwd
