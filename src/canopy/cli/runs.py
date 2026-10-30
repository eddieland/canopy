"""The detached `canopy _run`, a worker's run a tick starts; and `canopy _task`, a task's run a tick starts."""

from __future__ import annotations

import sys

import click

from canopy.cli.common import CliError, leave_the_tick, open_context
from canopy.runs import task_run, worker


@click.command("_run", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_run(click_ctx: click.Context, run_id: int) -> int:
    """Do one dispatched run. Started by a tick, detached; not for people or agents."""
    leave_the_tick()
    ctx = open_context(click_ctx)
    try:
        outcome = worker.execute(ctx, run_id, out=sys.stdout)
    except worker.WorkerError as e:
        raise CliError(str(e)) from None
    click.echo(f"run {run_id}: {outcome.status}")
    return 0


@click.command("_task", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_task(click_ctx: click.Context, run_id: int) -> int:
    """Do one run of a task the operator submitted. Started by a tick, detached; not for people or agents."""
    leave_the_tick()
    ctx = open_context(click_ctx)
    try:
        outcome = task_run.execute(ctx, run_id, out=sys.stdout)
    except task_run.TaskRunError as e:
        raise CliError(str(e)) from None
    click.echo(f"task run {run_id}: {outcome.status}")
    return 0
