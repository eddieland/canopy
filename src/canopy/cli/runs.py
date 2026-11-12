"""The detached runs a tick starts: `canopy _run`, a worker's, `canopy _task`, a task's, and `canopy _epic`."""

from __future__ import annotations

import sys

import click

from canopy.cli.common import CliError, leave_the_tick, open_context
from canopy.core import run_spans
from canopy.runs import epic_run, policy, task_run, worker


@click.command("_run", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_run(click_ctx: click.Context, run_id: int) -> int:
    """Do one dispatched run. Started by a tick, detached; not for people or agents."""
    leave_the_tick()
    ctx = open_context(click_ctx)
    try:
        with run_spans.span(ctx, "runs", run_id, attempt=policy.attempt_of) as traced:
            outcome = worker.execute(ctx, run_id, out=sys.stdout)
            traced.ended(outcome.status)
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
        with run_spans.span(ctx, "task_runs", run_id) as traced:
            outcome = task_run.execute(ctx, run_id, out=sys.stdout)
            traced.ended(outcome.status)
    except task_run.TaskRunError as e:
        raise CliError(str(e)) from None
    click.echo(f"task run {run_id}: {outcome.status}")
    return 0


@click.command("_epic", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_epic(click_ctx: click.Context, run_id: int) -> int:
    """Do one plan run of an epic the operator submitted. Started by a tick, detached; not for people or agents.

    An epic's plan run (DESIGN §43).
    """
    leave_the_tick()
    ctx = open_context(click_ctx)
    try:
        with run_spans.span(ctx, "epic_runs", run_id) as traced:
            outcome = epic_run.execute(ctx, run_id, out=sys.stdout)
            traced.ended(outcome.status)
    except epic_run.EpicRunError as e:
        raise CliError(str(e)) from None
    click.echo(f"epic plan run {run_id}: {outcome.status}")
    return 0
