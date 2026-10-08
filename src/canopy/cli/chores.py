"""`canopy chore run` and `wait` for the overseer, `try` for the operator, and the detached `_chore` (DESIGN §19)."""

from __future__ import annotations

import json
import os
import sys

import click

from canopy.chores import execute, start, trial, view
from canopy.cli.common import CliError, open_context, require_tick
from canopy.cli.params import CHORE, TextType, truncate
from canopy.core import conversation, db
from canopy.infra import logs, procs
from canopy.loop import attention, tick


@click.group("chore")
def chore_group() -> None:
    """Run or wait on the operator's chores (the overseer), or try one by hand (the operator)."""


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


@chore_group.command("try")
@click.argument("name", type=CHORE)
@click.option("--context", type=TextType(), help="What the chore should look at, as the overseer would say it.")
@click.pass_context
def cmd_chore_try(click_ctx: click.Context, name: str, context: str | None) -> int:
    """Run chore NAME now, in the foreground, and print its result. Records nothing; no guard applies.

    For writing a chore: the agent gets the prompt a run starting now would get, and its result line is checked as a
    real run's is. Works with `capacity.max_chores = 0`, so you can write one before the loop runs any. Exits 0 only
    when the chore reports `ok`.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"chore try refused ({r.guard}): {r.reason}") from None
    ctx = open_context(click_ctx)
    try:
        prepared = trial.prepare(ctx, name, context)
    except trial.TrialError as e:
        raise CliError(f"chore try refused: {e}") from None
    timeout = prepared.chore.timeout_minutes
    click.echo(f"trying chore {name} in {prepared.cwd} (timeout {timeout} minutes); nothing is recorded", err=True)
    try:
        tried = trial.run(ctx, prepared)
    except procs.ProcError as e:
        raise CliError(f"chore try: {e}") from None
    logs.for_tick(None).info("chore tried", extra={"chore": name, "status": tried.outcome.status})
    click.echo(f"--- agent text ---\n{tried.output.text.rstrip()}")
    if tried.stderr.strip():
        click.echo(f"--- agent stderr ---\n{tried.stderr.rstrip()}")
    usage = tried.output.usage
    click.echo(f"--- agent exit {tried.returncode}{f', cost {usage.describe()}' if usage is not None else ''} ---")
    outcome = tried.outcome
    if outcome.result is not None:
        click.echo(json.dumps(outcome.result.model_dump(exclude_none=True), indent=2))
    click.echo(f"chore try {name}: {outcome.status}{f' ({outcome.note})' if outcome.note else ''}")
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
