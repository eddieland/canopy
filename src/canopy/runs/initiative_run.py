"""`canopy _initiative <run_id>`: one plan run of an initiative, in the slots the tick leased for it (DESIGN §43).

Checks each slot out at its repository's base, detached, makes the run's desk of links to them, and runs the planner,
`runtime.plan_cmd`, with the initiative's prompt: the planner reads, and writes only its plan, `.canopy-new-plan.md` in
the desk. A copy of the initiative's current plan, when it has one, waits beside it as the plan it replaces. On `done`,
the plan is kept only when canopy can read its ids and its breakdown in the outline's shape (`initiative_outline`);
then its file is written to the state directory and its row recorded `proposed`, for the operator alone to approve.
Anything else records no plan. The desk is removed and the slots tidied and returned on every exit path this process
can see; a run whose process died is closed by reconcile (`initiative_runs.end`). The run writes nothing about any
ticket.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, TextIO

from pydantic import BaseModel, ConfigDict, StrictStr

from canopy.core import (
    agent_models,
    cards,
    contract,
    conversation,
    db,
    definitions,
    git_tools,
    hostgit,
    initiative_outline,
    initiatives,
    plans,
    run_models,
    sandboxing,
)
from canopy.core.config import render_command
from canopy.core.vocab import RunStatus
from canopy.core.workspace import DESKS_DIR
from canopy.infra import logs, procs, stopping
from canopy.runs import checkpoint, desks, initiative_runs, initiative_starts, tidy
from canopy.runs.checkpoint import SetupError
from canopy.runtime import project_config, servers, stdout

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy.core import records
    from canopy.core.context import Context

#: The most a plan run's summary or question holds, as a worker's does.
MAX_TEXT = 2000
#: The run's id as its agent's environment names it, so the operator's commands refuse inside it (DESIGN §22).
RUN_ID_PREFIX = "init-"

Text = Annotated[StrictStr, contract.bounded(MAX_TEXT)]


class InitiativeRunError(Exception):
    """`_initiative` cannot start this run at all: it does not exist or is not waiting to start."""


class InitiativePlanResult(BaseModel):
    """An initiative planner's result contract (DESIGN §43): the last line of its stdout. Untrusted, so bounded.

    The plan itself is the file the planner wrote in its desk, not a field.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    status: Literal["done", "blocked", "failed"]
    summary: Text = ""
    question: Text | None = None


@dataclass(frozen=True)
class Outcome:
    """How a plan run ended: its status, its validated result, the harness's note, and the plan it recorded."""

    status: RunStatus
    result: InitiativePlanResult | None
    note: str = ""
    #: The plan the run recorded; None when it recorded none.
    plan_id: int | None = None

    def result_json(self) -> str:
        """Return what `initiative_runs.result_json` stores: the validated result and the harness's note.

        Returns:
            The JSON, never the planner's output.
        """
        data: dict[str, object] = self.result.model_dump(mode="json") if self.result is not None else {}
        if self.note:
            data["harness"] = self.note
        return json.dumps(data)


def execute(ctx: Context, run_id: int, *, out: TextIO) -> Outcome:
    """Do plan run `run_id`, from claiming it to returning its slots and closing its row. Output goes to `out`.

    Returns:
        How the run ended, as its row was closed with. A setup failure, a signal, or an unexpected error is `crashed`,
        with why in its note.

    Raises:
        InitiativeRunError: the run does not exist or is not waiting to start, for example because another process
            has it.
    """
    run = initiative_runs.get_run(ctx.conn, run_id)
    if run is None:
        raise InitiativeRunError(f"no initiative plan run {run_id}")
    if not db.claim_run(ctx.conn, "initiative_runs", run_id, os.getpid()):
        msg = f"initiative plan run {run_id} is not waiting to start: it is {run.status} or another process has it"
        raise InitiativeRunError(msg)
    for slot in initiative_runs.slots_of(ctx.conn, run_id):
        # Before any git step: reconcile checks it for a process that dies before putting a changed link back.
        initiative_runs.set_git_link(ctx.conn, run_id, slot.repo, hostgit.read_link(Path(slot.slot_path)))
    log = logs.for_tick(run.tick_id)
    fields = {"initiative_run_id": run_id, "initiative": run.initiative_id}
    log.info("initiative plan run started", extra=fields)
    outcome = Outcome(RunStatus.CRASHED, None, "the plan run stopped before its planner finished")
    with stopping.StopOnSignal() as stop:
        try:
            tidy.make_objects(initiative_runs.objects_dir(Path(run.log_path)))
            outcome = _work(ctx, run, out, log)
        except stopping.Stopped as e:
            outcome = Outcome(RunStatus.CRASHED, None, str(e))
        except SetupError as e:
            outcome = Outcome(RunStatus.CRASHED, None, str(e))
            log.error("initiative plan run setup failed", extra={**fields, "error": str(e)})  # noqa: TRY400
        except Exception as e:
            outcome = Outcome(RunStatus.CRASHED, None, f"{type(e).__name__}: {e}")
            log.exception("initiative plan run failed", extra=fields)
        finally:
            # From here on a signal is ignored: returning the slots and closing the row must not be interrupted.
            stop.armed = False
            current = initiative_runs.get_run(ctx.conn, run_id) or run
            initiative_runs.release(ctx, current, log)
            if not initiative_runs.close_run(ctx.conn, run_id, outcome.status, outcome.result_json()):
                log.warning("initiative plan run was already closed; its outcome is not recorded", extra=fields)
            procs.drop_lifelock(Path(run.log_path))
            log.info("initiative plan run finished", extra={**fields, "status": outcome.status})
            run_models.read_ended(ctx, "initiative_runs", run_id, log)
    return outcome


def _work(ctx: Context, run: records.InitiativeRun, out: TextIO, log: logs.TickAdapter) -> Outcome:
    """Check each slot out at its base, run the planner in the desk, and keep the plan it wrote if canopy can read it.

    Returns:
        How the run ended.
    """
    slots = initiative_runs.slots_of(ctx.conn, run.id)
    trees = {slot.repo: Path(slot.slot_path) for slot in slots}
    for slot in slots:
        checkpoint.check_out(checkpoint.Git(ctx.runner, Path(slot.slot_path), slot.repo), slot.base_branch)
    result, text = _run_agent(ctx, run, trees, out, log)
    parsed = contract.last_line(InitiativePlanResult, text)
    if result.timed_out:
        return Outcome(RunStatus.TIMEOUT, parsed, "the planner ran out of time")
    if parsed is None:
        return Outcome(RunStatus.UNKNOWN, None, "the planner's result line could not be read")
    if parsed.status != "done":
        return Outcome(RunStatus(parsed.status), parsed)
    return _keep(ctx, run, parsed, frozenset(trees), log)


def _keep(
    ctx: Context,
    run: records.InitiativeRun,
    parsed: InitiativePlanResult,
    repos: frozenset[str],
    log: logs.TickAdapter,
) -> Outcome:
    """Keep the plan a `done` planner wrote, if canopy can read its ids and breakdown, as the initiative's newest.

    Returns:
        `done` with the plan recorded; `unknown` when there is no plan canopy can read; `crashed` when it could not be
        kept.
    """
    reading = plans.read(Path(run.desk_path) / plans.WRITTEN)
    if reading.text is None:
        return Outcome(RunStatus.UNKNOWN, parsed, f"its {plans.WRITTEN} is {reading.problem}; no plan was recorded")
    try:
        initiative_outline.read(reading.text, repos=repos)
    except initiative_outline.OutlineError as e:
        note = f"its plan's ids or breakdown cannot be read: {e.reason}; no plan was recorded"
        return Outcome(RunStatus.UNKNOWN, parsed, note)
    try:
        written = initiatives.write_plan(ctx.state_dir, run.initiative_id, run.id, reading.text)
    except (plans.PlanFileError, OSError) as e:
        return Outcome(RunStatus.CRASHED, parsed, f"its plan could not be kept: {e}")
    plan = initiatives.record_plan(ctx.conn, run.initiative_id, run.id, written)
    log.info("initiative plan recorded", extra={"initiative": run.initiative_id, "plan": plan.id, "size": plan.size})
    return Outcome(RunStatus.DONE, parsed, plan_id=plan.id)


def _desk_files(ctx: Context, run: records.InitiativeRun) -> dict[str, str]:
    """Return the files the desk starts with: the initiative's current plan, as the plan this run replaces.

    Read bounded and never through a link, as any plan is (DESIGN §25); one that is no longer a plan is left out.

    Returns:
        The files by name, empty when the initiative has no current plan.
    """
    current = initiatives.current_plan(ctx.conn, run.initiative_id)
    if current is None:
        return {}
    reading = plans.read(initiatives.plan_path(ctx.state_dir, run.initiative_id, current.run_id))
    return {plans.REPLACED: reading.text} if reading.text is not None else {}


def _run_agent(
    ctx: Context,
    run: records.InitiativeRun,
    trees: Mapping[str, Path],
    out: TextIO,
    log: logs.TickAdapter,
) -> tuple[procs.Result, str]:
    """Run the planner's command in the run's desk with the initiative's prompt, for the worker's timeout.

    A planner reads and writes only its plan, so the places it reads config from must name none of the tracker
    server's tools (DESIGN §25). It reads its worktrees' history through canopy's read-only git tools. The session,
    cost, and tool calls the runtime reported are recorded at once.

    Returns:
        The agent's process and the text its result line is read from.

    Raises:
        SetupError: a place the planner reads config from shadows canopy's definitions or names a tracker tool, or the
            desk cannot be made.
    """
    runtime = ctx.config.runtime
    tools = ctx.config.tracker.tools()
    # A planner in a desk starts in no repository, so the runtime may look above it: those directories are checked.
    places = [*trees.values(), ctx.workspace.root / DESKS_DIR, ctx.workspace.root]
    refused = project_config.refusal(
        places,
        version=runtime.version,
        tracker_server=tools.server if tools is not None else None,
    )
    if refused is not None:
        raise SetupError(refused)
    prompt = initiative_starts.prompt_file(Path(run.log_path)).read_text(encoding="utf-8")
    models = agent_models.of_run(ctx.config, runtime.plan_cmd, run.model)
    # The prompt's fixed instructions are its agent's body, in a snapshot every initiative's plan run shares (§13).
    bodies, message = definitions.run_prompt(prompt, runtime.plan_cmd)
    snapshot = definitions.ensure(ctx.state_dir, ctx.config, models, bodies)
    command = render_command(runtime.worker_template(runtime.plan_cmd), message, snapshot, f"init:{run.initiative_id}")
    argv = sandboxing.wrap(runtime, list(trees), "worker", command.argv, snapshot)
    try:
        desk = desks.make(ctx.workspace.root, initiative_runs.desk_key(run.initiative_id), trees.items())
        for name, text in _desk_files(ctx, run).items():
            logs.write_private(desk / name, text)
    except (desks.DeskError, OSError) as e:
        raise SetupError(str(e)) from e
    timeout_minutes = runtime.worker_timeout_minutes
    log.info(
        "running the initiative's planner",
        extra={"initiative_run_id": run.id, "cmd": argv[0], "cwd": str(desk), "timeout_minutes": timeout_minutes},
    )
    out.write("--- planner stdout ---\n")
    out.flush()
    env = {
        conversation.RUN_ID_ENV: f"{RUN_ID_PREFIX}{run.id}",
        tidy.OBJECTS_ENV: str(initiative_runs.objects_dir(Path(run.log_path))),
    }
    served = {cards.SERVER: cards.SERVER_COMMAND, git_tools.SERVER: git_tools.command(trees)}
    env |= servers.env(served, version=runtime.version, cwd=ctx.workspace.root.absolute())
    result = ctx.runner.run(
        argv,
        cwd=desk,
        env=env,
        stdin=command.stdin,
        timeout=timeout_minutes * 60,
        on_start=lambda pid: db.set_agent_pid(ctx.conn, "initiative_runs", run.id, pid),
        on_line=lambda line: _echo(out, line),
    )
    out.write(f"\n--- planner stderr ---\n{result.stderr}\n")
    out.write(f"--- planner exit {result.returncode}{' (timed out)' if result.timed_out else ''} ---\n")
    out.flush()
    output = stdout.read(result.stdout, version=runtime.version)
    if output.session_id is not None or output.usage is not None:
        db.set_run_report(
            ctx.conn,
            "initiative_runs",
            run.id,
            output.session_id,
            output.usage,
            digest=snapshot.name,
            tools=output.tools,
        )
    return result, output.text


def _echo(out: TextIO, line: str) -> None:
    """Write a line the planner printed to the run's log as it prints it."""
    out.write(f"{line}\n")
