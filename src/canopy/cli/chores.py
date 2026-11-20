"""`canopy chore` for the operator and a chore's own runs, and the detached `_chore` (DESIGN §19).

The overseer runs and waits on chores through its tools (`loop.chore_tools`, DESIGN §27).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from canopy.chores import drift, execute, history, install, start, trial
from canopy.cli.common import CliError, leave_the_tick, open_context, runner_of
from canopy.cli.params import CHORE, EXAMPLE_CHORE, TextType, validated
from canopy.core import conversation, run_models, run_spans, workspace
from canopy.core.config import ConfigError
from canopy.infra import logs, procs


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
    chore's next run is due counting from it. It names the model canopy asks for, and once a recorded run ends, the
    models its session says served it. With --no-record nothing is written, so a prompt being drafted cannot
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
    # The model canopy asks for, as a run records it; none for the runtime's default, or an agent of the operator's own.
    asked = start.asked_model(ctx.config, prepared.chore)
    model = f", model {asked}" if asked is not None else ""
    click.echo(f"trying chore {name} in {prepared.cwd} (timeout {timeout} minutes{model}); {where}", err=True)
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
        cost = f", cost {usage.describe()}" if usage is not None else ""
        # A recorded try's session was read as it closed, for the models that served it; one unrecorded is never read.
        served = run_models.served_of(run_models.of_run(ctx.conn, "chore_runs", run_id)) if run_id is not None else ""
        click.echo(f"--- agent exit {printed.returncode}{cost}{served} ---")
    if outcome.result is not None:
        click.echo(json.dumps(outcome.result.model_dump(exclude_none=True), indent=2))
    note = f" ({outcome.note})" if outcome.note else ""
    where = "; nothing recorded" if run_id is None else f"; run {run_id}, see `canopy show chore:{name}`"
    click.echo(f"chore try {name}: {outcome.status}{note}{where}")
    return 0 if outcome.status == "ok" else 1


@chore_group.command("install")
@click.argument("name", type=EXAMPLE_CHORE, required=False)
@click.option(
    "--merge",
    is_flag=True,
    help="Merge what canopy changed since NAME was installed into your copies, keeping your edits; write nothing on a "
    "conflict.",
)
@click.pass_context
def cmd_chore_install(click_ctx: click.Context, name: str | None, *, merge: bool) -> int:
    """Set up example chore NAME, one canopy ships, in this workspace; with no NAME, list them.

    The prompt goes in the workspace's .canopy/chore-prompts/, the agent the example comes with, if any, in
    .canopy/chore-agents/NAME/, and the [chores.NAME] table in its private config. They stay as installed when canopy
    is upgraded. The command owns them: running it again replaces them with the shipped ones, and an edit to any is
    lost; `canopy chore diff NAME` shows the edits to carry over, and --merge carries them: it merges what canopy
    changed in the prompt and the agent since the install into your copies, leaves the table as it is, and writes
    nothing where a change conflicts with yours. Answer a chore with `canopy reply chore:NAME` instead, which survives
    it. The list marks each example installed here, and says when canopy ships a newer one.
    """
    if name is None:
        if merge:
            raise click.UsageError("--merge needs the NAME of an installed chore")
        _list_examples()
        return 0
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"chore install refused ({r.guard}): {r.reason}") from None
    if merge:
        return _merge(click_ctx, name)
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


def _merge(click_ctx: click.Context, name: str) -> int:
    """Merge what canopy changed in installed example chore `name` into the copies, and say what it did.

    Returns:
        0 once merged, or when there was nothing to merge; 1 on a conflict, with nothing written.

    Raises:
        CliError: it cannot be merged.
    """
    try:
        merged = drift.merge(workspace.find(Path.cwd()), name, runner_of(click_ctx))
    except (drift.MergeError, ConfigError, OSError) as e:
        raise CliError(f"chore install --merge: {e}") from None
    if merged.conflicts:
        each = ", ".join(f"{file} ({count})" for file, count in merged.conflicts.items())
        click.echo(
            f"chore install --merge: canopy's change conflicts with yours in {each}, so nothing was written; "
            f"`canopy chore diff {name}` shows both sides",
            err=True,
        )
        return 1
    if not merged.written:
        said = (
            "your copies already hold canopy's change" if merged.advanced else "canopy ships what it was installed from"
        )
        click.echo(f"chore {name}: {said}; nothing to merge")
        return 0
    for path in merged.written:
        click.echo(f"merged canopy's change into {path}")
    click.echo(f"[chores.{name}] is left as it was; `canopy chore diff {name}` shows what you changed")
    return 0


@chore_group.command("diff")
@click.argument("name", type=EXAMPLE_CHORE)
def cmd_chore_diff(name: str) -> int:
    """Show how example chore NAME, as installed here, and the one canopy ships have moved apart.

    Two unified diffs of its prompt and agent: what canopy changed since it was installed, and what you changed in
    the copies; the two sides of a merge by hand, before `canopy chore install NAME` puts the shipped one back, or
    of the merge `canopy chore install NAME --merge` makes. For a
    chore installed before canopy kept what it installed it from, only your copies against what canopy ships now. It
    writes nothing.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"chore diff refused ({r.guard}): {r.reason}") from None
    try:
        found = drift.of(workspace.find(Path.cwd()), name)
    except (ConfigError, OSError) as e:
        raise CliError(f"chore diff: {e}") from None
    if found is None:
        raise CliError(f"chore diff: chore {name} is not installed here; `canopy chore install` lists the examples")
    click.echo(drift.diff(found), nl=False)
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
        with run_spans.span(ctx, "chore_runs", run_id) as traced:
            outcome = execute.execute(ctx, run_id, out=sys.stdout)
            traced.ended(outcome.status)
    except execute.ChoreError as e:
        raise CliError(str(e)) from None
    click.echo(f"chore run {run_id}: {outcome.status}")
    return 0


def _list_examples() -> None:
    """Print each example chore canopy ships, and how it stands when it is installed in the workspace here.

    Raises:
        CliError: an installed chore's copies cannot be read.
    """
    examples = install.available()
    # Outside a workspace, the examples are all there is to say; in one whose map does not load, that is the answer.
    try:
        ws = workspace.find(Path.cwd()) if workspace.find_root(Path.cwd()) is not None else None
    except ConfigError as e:
        raise CliError(f"chore install: {e}") from None
    width = max((len(example) for example in examples), default=0)
    for example in examples:
        try:
            found = drift.of(ws, example) if ws is not None else None
        except OSError as e:
            raise CliError(f"chore install: {e}") from None
        standing = f"  {drift.describe(found.standing, example)}" if found is not None else ""
        click.echo(f"{example:<{width}}{standing}".rstrip())
