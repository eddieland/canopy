"""The detached runs a tick starts: `canopy _run`, a worker's, `canopy _task`, a task's, and `canopy _initiative`."""

from __future__ import annotations

import sys

import click

from canopy.cli.common import CliError, leave_the_tick, open_context
from canopy.infra import tracing
from canopy.runs import initiative_run, task_run, worker


@click.command("_run", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_run(click_ctx: click.Context, run_id: int) -> int:
    """Do one dispatched run. Started by a tick, detached; not for people or agents."""
    leave_the_tick()
    ctx = open_context(click_ctx)
    try:
        with tracing.span("run", new_trace=True, run_id=run_id) as traced:
            outcome = worker.execute(ctx, run_id, out=sys.stdout)
            traced.set(status=outcome.status)
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
        with tracing.span("task", new_trace=True, task_run_id=run_id) as traced:
            outcome = task_run.execute(ctx, run_id, out=sys.stdout)
            traced.set(status=outcome.status)
    except task_run.TaskRunError as e:
        raise CliError(str(e)) from None
    click.echo(f"task run {run_id}: {outcome.status}")
    return 0


@click.command("_initiative", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_initiative(click_ctx: click.Context, run_id: int) -> int:
    """Do one plan run of an initiative the operator submitted. Started by a tick, detached; not for people or agents.

    An initiative's plan run (DESIGN §43).
    """
    leave_the_tick()
    ctx = open_context(click_ctx)
    try:
        with tracing.span("initiative", new_trace=True, initiative_run_id=run_id) as traced:
            outcome = initiative_run.execute(ctx, run_id, out=sys.stdout)
            traced.set(status=outcome.status)
    except initiative_run.InitiativeRunError as e:
        raise CliError(str(e)) from None
    click.echo(f"initiative plan run {run_id}: {outcome.status}")
    return 0
