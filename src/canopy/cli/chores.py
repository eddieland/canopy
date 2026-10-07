"""`canopy chore run` and `canopy chore wait` for the overseer, and the detached `canopy _chore` (DESIGN §19)."""

from __future__ import annotations

import os
import sys

import click

from canopy.chores import execute, start, view
from canopy.cli.common import CliError, open_context, require_tick
from canopy.cli.params import CHORE, TextType, truncate
from canopy.core import db
from canopy.infra import logs
from canopy.loop import attention, tick


@click.group("chore")
def chore_group() -> None:
    """Run or wait on the operator's chores (overseer only)."""


@chore_group.command("run")
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


@chore_group.command("wait")
@click.argument("name", type=CHORE)
@click.option("--rationale", required=True, type=TextType())
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
