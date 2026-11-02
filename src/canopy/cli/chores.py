"""`canopy chore` for the operator and a chore's own runs, and the detached `_chore` (DESIGN §19).

The overseer runs and waits on chores through its tools (`loop.chore_tools`, DESIGN §27).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from canopy.chores import execute, history, install, trial
from canopy.cli.common import CliError, leave_the_tick, open_context
from canopy.cli.params import CHORE, EXAMPLE_CHORE, TextType, validated
from canopy.core import conversation, workspace
from canopy.core.config import ConfigError
from canopy.infra import logs, procs, tracing


@click.group("chore")
def chore_group() -> None:
    """Try, install, or read the history of the operator's chores."""


@chore_group.command("try")
@click.argument("name", type=CHORE)
@click.option("--context", type=TextType(), help="What the chore should look at, as the overseer would say it.")
@click.option("--no-record", is_flag=True, help="Record nothing: no run, findings, or notification. For drafting.")
@click.pass_context
def cmd_chore_try(click_ctx: click.Context, name: str, context: str | None, *, no_record: bool) -> int:
    """Run chore NAME now, in the foreground, and print its result. No guard applies.

    The run is recorded like one the loop started: its findings go on the attention list and `canopy show`, and the
    chore's next run is due counting from it. With --no-record nothing is written, so a prompt being drafted cannot
    clear real findings. Works with `capacity.max_chores = 0`, so you can write a chore before the loop runs any. Exits
    0 only when the chore reports `ok`.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"chore try refused ({r.guard}): {r.reason}") from None
    ctx = open_context(click_ctx)
    try:
        prepared = trial.prepare(ctx, name, context)
        recorded = None if no_record else trial.record(ctx, prepared)
    except trial.TrialError as e:
        hint = "; --no-record runs it anyway, recording nothing" if isinstance(e, trial.RunningError) else ""
        raise CliError(f"chore try refused: {e}{hint}") from None
    run_id = recorded.run_id if recorded is not None else None
    where = "nothing is recorded" if run_id is None else f"recorded as chore run {run_id}"
    timeout = prepared.chore.timeout_minutes
    click.echo(f"trying chore {name} in {prepared.cwd} (timeout {timeout} minutes); {where}", err=True)
    try:
        outcome = trial.run_unrecorded(ctx, prepared) if recorded is None else trial.run_recorded(ctx, recorded)
    except (procs.ProcError, execute.ChoreError) as e:
        raise CliError(f"chore try: {e}") from None
    logs.for_tick(None).info("chore tried", extra={"chore": name, "chore_run_id": run_id, "status": outcome.status})
    printed = outcome.printed
    if printed is not None:
        click.echo(f"--- agent text ---\n{printed.output.text.rstrip()}")
        if printed.stderr.strip():
            click.echo(f"--- agent stderr ---\n{printed.stderr.rstrip()}")
        usage = printed.output.usage
        click.echo(
            f"--- agent exit {printed.returncode}{f', cost {usage.describe()}' if usage is not None else ''} ---",
        )
    if outcome.result is not None:
        click.echo(json.dumps(outcome.result.model_dump(exclude_none=True), indent=2))
    note = f" ({outcome.note})" if outcome.note else ""
    where = "; nothing recorded" if run_id is None else f"; run {run_id}, see `canopy show chore:{name}`"
    click.echo(f"chore try {name}: {outcome.status}{note}{where}")
    return 0 if outcome.status == "ok" else 1


@chore_group.command("install")
@click.argument("name", type=EXAMPLE_CHORE, required=False)
def cmd_chore_install(name: str | None) -> int:
    """Set up example chore NAME, one canopy ships, in this workspace; with no NAME, list them.

    The prompt goes in the workspace's .canopy/chore-prompts/, the agent the example comes with, if any, in
    .canopy/chore-agents/NAME/, and the [chores.NAME] table in its private config. They stay as installed when canopy
    is upgraded. The command owns them: running it again replaces them with the shipped ones, and an edit to any is
    lost. Answer a chore with `canopy reply chore:NAME` instead, which survives it.
    """
    if name is None:
        for example in install.available():
            click.echo(example)
        return 0
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"chore install refused ({r.guard}): {r.reason}") from None
    try:
        installed = install.install(workspace.find(Path.cwd()), name)
    except (install.InstallError, ConfigError) as e:
        raise CliError(f"chore install: {e}") from None
    except OSError as e:
        raise CliError(f"chore install: {e}") from None
    verb = "replaced" if installed.replaced else "wrote"
    agent = f", its agent {installed.agent}," if installed.agent is not None else ""
    click.echo(f"{verb} {installed.prompt}{agent} and [chores.{name}] in {installed.config_file}")
    for step in installed.next_steps:
        click.echo(step)
    click.echo(
        f"Then run `canopy chore try {name}` until its findings are the ones you want; the loop runs it once "
        "capacity.max_chores is above 0.",
    )
    return 0


@chore_group.command("history")
@click.argument("name", type=CHORE)
@click.option("--run", "run_id", type=click.IntRange(min=1), help="Print this run's summary and findings in full.")
@click.option("--before", type=click.IntRange(min=1), help="List only the runs before this run id: the next page.")
@click.option(
    "--limit",
    type=click.IntRange(1, history.MAX_LIMIT),
    default=history.DEFAULT_LIMIT,
    show_default=True,
    help="List at most this many runs.",
)
@click.pass_context
def cmd_chore_history(click_ctx: click.Context, name: str, run_id: int | None, before: int | None, limit: int) -> int:
    """List chore NAME's runs, newest first, with what each reported, or with --run one run's findings in full.

    The operator reads any chore's; a run of chore NAME reads it through its `canopy_chore_history` tool, which says
    the same. The overseer may not, since its state block carries each chore's latest run and findings. It records
    nothing.
    """
    request = validated(click_ctx, history.History, name=name, run=run_id, before=before, limit=limit)
    # A chore's agent may run in a `cwd` outside the workspace; its run names the workspace it belongs to.
    root = os.environ.get(history.WORKSPACE_ENV)
    ctx = open_context(click_ctx, start=Path(root) if root else None)
    try:
        said = history.read(ctx, request)
    except history.Refused as r:
        raise CliError(str(r)) from None
    click.echo(said)
    return 0


@click.command("_chore", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_chore_process(click_ctx: click.Context, run_id: int) -> int:
    """Do one chore run. Started by a tick, detached; not for people or agents."""
    leave_the_tick()
    ctx = open_context(click_ctx)
    try:
        with tracing.span("chore", chore_run_id=run_id) as traced:
            outcome = execute.execute(ctx, run_id, out=sys.stdout)
            traced.set(status=outcome.status)
    except execute.ChoreError as e:
        raise CliError(str(e)) from None
    click.echo(f"chore run {run_id}: {outcome.status}")
    return 0
