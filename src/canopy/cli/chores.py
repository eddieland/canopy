"""`canopy chore run` and `wait` for the overseer, `try` for the operator, and the detached `_chore` (DESIGN §19)."""

from __future__ import annotations

import json
import os
import sys

import click

from canopy.chores import execute, start, trial
from canopy.cli.common import CliError, Group, OverseerCommand, open_context, require_tick
from canopy.cli.params import CHORE, TextType, truncate
from canopy.core import chore_view as view
from canopy.core import conversation, db
from canopy.infra import logs, procs
from canopy.loop import attention, tick


@click.group("chore", cls=Group)
def chore_group() -> None:
    """Run or wait on the operator's chores (the overseer), or run one now by hand (the operator)."""


@chore_group.command("run", cls=OverseerCommand)
@click.argument("name", type=CHORE)
@click.option(
    "--context",
    type=TextType(),
    help="What the chore should look at: a PR, a job name, a build number. Never quoted text.",
)
@click.pass_context
def cmd_chore_run(click_ctx: click.Context, name: str, context: str | None) -> int:
    """Start a run of chore NAME, if its guards allow one now."""
    ctx = open_context(click_ctx)
    current = require_tick(ctx)
    tick_id = int(current["id"])
    log = logs.for_tick(tick_id)
    try:
        if current["dry_run"]:
            start.check(ctx, tick_id=tick_id, name=name)
            started = None
        else:
            started = start.start(ctx, tick_id=tick_id, name=name, context=context)
    except start.Refusal as r:
        db.record_decision(ctx.conn, tick_id, None, f"refused:{r.guard}", r.reason, chore=name)
        log.info("chore run refused", extra={"chore": name, "guard": r.guard, "reason": r.reason})
        raise CliError(f"chore run refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    on_context = f"; context={context}" if context else ""
    if started is None:
        rationale = truncate(f"dry run: not dispatched{on_context}")
        db.record_decision(ctx.conn, tick_id, None, start.DISPATCH_ACTION, rationale, chore=name)
        click.echo(f"dry run: recorded chore run {name}; nothing was started")
        return 0
    rationale = truncate(f"chore run {started.run_id}{on_context}")
    db.record_decision(ctx.conn, tick_id, None, start.DISPATCH_ACTION, rationale, chore=name)
    log.info("chore run started", extra={"chore": name, "chore_run_id": started.run_id, "pid": started.pid})
    click.echo(f"started chore {name}: run {started.run_id}")
    return 0


@chore_group.command("wait", cls=OverseerCommand)
@click.argument("name", type=CHORE)
@click.option("--rationale", required=True, type=TextType(), help="Why it should not run now, in your own words.")
@click.pass_context
def cmd_chore_wait(click_ctx: click.Context, name: str, rationale: str) -> int:
    """Record that chore NAME is due but should not run now, and why."""
    ctx = open_context(click_ctx)
    current = require_tick(ctx)
    if name not in view.configured(ctx.config, ctx.workspace):
        raise CliError(f"no chore named {name!r} is configured for this workspace")
    db.record_decision(ctx.conn, int(current["id"]), None, "wait", rationale, chore=name)
    click.echo(f"recorded wait for {attention.CHORE_PREFIX}{name}")
    return 0


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
            f"--- agent exit {printed.returncode}{f', cost {usage.describe()}' if usage is not None else ''} ---"
        )
    if outcome.result is not None:
        click.echo(json.dumps(outcome.result.model_dump(exclude_none=True), indent=2))
    note = f" ({outcome.note})" if outcome.note else ""
    where = "; nothing recorded" if run_id is None else f"; run {run_id}, see `canopy show chore:{name}`"
    click.echo(f"chore try {name}: {outcome.status}{note}{where}")
    return 0 if outcome.status == "ok" else 1


@click.command("_chore", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_chore_process(click_ctx: click.Context, run_id: int) -> int:
    """Do one chore run. Started by `canopy chore run`, detached; not for people or agents."""
    # The chore must not be able to act as the overseer of the tick that started it (D020).
    os.environ.pop(tick.TICK_ID_ENV, None)
    ctx = open_context(click_ctx)
    try:
        outcome = execute.execute(ctx, run_id, out=sys.stdout)
    except execute.ChoreError as e:
        raise CliError(str(e)) from None
    click.echo(f"chore run {run_id}: {outcome.status}")
    return 0
