"""`canopy task` for the operator's one-off tasks, how `show` and `stop` read and end one, and the detached `_task`.

A task is work the operator hands canopy in their own words, about no ticket (DESIGN §36). `task submit` and `stop
task:N` write through `canopy.core.tasks`, and like every operator verb refuse inside canopy's own ticks and runs; so
do `task list` and `show task:N`, which print the operator's text, so that no agent reads a task through them.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, Group, leave_the_tick, open_context
from canopy.cli.params import REPO
from canopy.cli.render import result_of, spent
from canopy.core import contract, conversation, tasks
from canopy.core.items import age
from canopy.core.vocab import TaskRunStatus
from canopy.infra import logs
from canopy.infra.text import one_line
from canopy.runs import task_worker
from canopy.runs import tasks as task_runs

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

CLI = "cli"
#: How much of a task's text `task list` prints on its line.
LIST_TEXT = 70
#: How many of a task's messages `canopy show task:N` prints.
SHOW_MESSAGES = 100


@click.group("task", cls=Group)
def task_group() -> None:
    """Hand canopy one-off work in your own words, about no ticket, and list what you handed it."""


@task_group.command("submit")
@click.argument("text", metavar="TEXT")
@click.option("--repo", type=REPO, help="The repository it runs in. Needed when the workspace has several.")
@click.option(
    "--project",
    metavar="KEY",
    help="The tracker project the tickets it may file go in, as a key's prefix: PROJ. None by default.",
)
@click.pass_context
def cmd_task_submit(click_ctx: click.Context, text: str, repo: str | None, project: str | None) -> int:
    """Submit a one-off task: TEXT, or with `-`, stdin, is the instruction its worker follows.

    The next tick starts it, before the overseer runs, when the capacity allows; a waiting loop wakes for it. Its worker
    is the private worker, in a worktree of the repository, on a branch of its own, `<branch_prefix>task/N`; it writes
    nothing to any ticket, and opens a draft PR only when TEXT asks for one. Follow it with `canopy show task:N`, and
    end it with `canopy stop task:N`.
    """
    _operator("task submit")
    body = sys.stdin.read() if text == "-" else text
    ctx = open_context(click_ctx)
    try:
        task = tasks.submit(ctx.conn, ctx.config, ctx.workspace, body, repo=repo, project=project, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"task submit refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info("task submitted", extra={"task": task.id, "repo": task.repo, "project": task.project})
    branch = tasks.branch_name(ctx.config.trust.branch_prefix, task.id)
    click.echo(f"Submitted task:{task.id} in {task.repo}; its branch will be {branch}.")
    click.echo(f"The next tick starts it. Follow it with `canopy show task:{task.id}`.")
    return 0


@task_group.command("list")
@click.pass_context
def cmd_task_list(click_ctx: click.Context) -> int:
    """List your tasks, the newest first: each one's state, repository, and the start of its text."""
    _operator("task list")
    ctx = open_context(click_ctx)
    found = tasks.every(ctx.conn)
    if not found:
        click.echo("No tasks yet: `canopy task submit TEXT` hands canopy one.")
        return 0
    for task in found:
        text = one_line(task.text)
        cut = text if len(text) <= LIST_TEXT else f"{text[: LIST_TEXT - 3]}..."
        click.echo(f"task:{task.id}  {_state(ctx, task)}  {task.repo}  {age(task.submitted_at)} ago  {cut}")
    return 0


@click.command("_task", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_task_process(click_ctx: click.Context, run_id: int) -> int:
    """Do one task run. Started by a tick, detached; not for people or agents."""
    leave_the_tick()
    ctx = open_context(click_ctx)
    try:
        outcome = task_worker.execute(ctx, run_id, out=sys.stdout)
    except task_worker.TaskError as e:
        raise CliError(str(e)) from None
    click.echo(f"task run {run_id}: {outcome.status}")
    return 0


def show(ctx: Context, task_id: int) -> None:
    """Print task `task_id` as `canopy show task:N` does: its text, its runs with their branch and head, its messages.

    Raises:
        CliError: inside one of canopy's own ticks or runs, or there is no such task.
    """
    _operator("show")
    task = tasks.get(ctx.conn, task_id)
    if task is None:
        raise CliError(f"there is no task {task_id}")
    click.echo(f"task:{task.id}: {_state(ctx, task)}, in {task.repo}, submitted {age(task.submitted_at)} ago")
    if task.project is not None:
        click.echo(f"  project {task.project}")
    click.echo(f"  branch {tasks.branch_name(ctx.config.trust.branch_prefix, task.id)}")
    click.echo("\nText:")
    for line in conversation.printable(task.text).splitlines():
        click.echo(f"    {line}")
    runs = tasks.runs_of(ctx.conn, task.id)
    click.echo(f"\nRuns ({len(runs)}):")
    for run in runs:
        _echo_run(run)
    if not runs:
        click.echo("  none yet: the next tick starts it" if task.stopped_at is None else "  none: stopped first")
    messages = tasks.messages_of(ctx.conn, task.id, SHOW_MESSAGES)
    click.echo(f"\nConversation ({len(messages)}):")
    for m in messages:
        about = f" (task run {m.task_run_id})" if m.task_run_id is not None else ""
        click.echo(f"  #{m.id}  {age(m.at)} ago  {m.source} {m.kind}{about}")
        for line in conversation.printable(m.body).splitlines():
            click.echo(f"    {line}")
    if not messages:
        click.echo("  none")


def stop(ctx: Context, task_id: int, *, now: bool) -> None:
    """Stop task `task_id` as `canopy stop task:N` does, and with `now` end the run working it.

    Raises:
        CliError: inside one of canopy's own ticks or runs, or there is no such task.
    """
    try:
        stopped = tasks.stop(ctx.conn, task_id)
    except conversation.Refused as r:
        raise CliError(f"stop refused ({r.guard}): {r.reason}") from None
    log = logs.for_tick(None)
    log.info("task stopped", extra={"task": task_id, "now": now})
    if stopped.already:
        click.echo(f"task:{task_id} was already stopped; nothing starts it now.")
    elif stopped.dropped:
        click.echo(f"task:{task_id} is stopped before it ran; nothing starts it now.")
    else:
        click.echo(f"task:{task_id} is stopped; nothing starts it again.")
    run = stopped.running
    if run is None:
        return
    if not now:
        click.echo(f"Its task run {run.id} is still working and will finish; --now ends it.")
        return
    if task_runs.stop(ctx, run, log):
        click.echo(f"Its task run {run.id} was ended and its slot returned.")
    else:
        click.echo(f"Its task run {run.id} had already ended.")


def _echo_run(run: records.TaskRun) -> None:
    when = f"ended {age(run.ended_at)} ago" if run.ended_at else f"started {age(run.started_at)} ago"
    click.echo(f"  task run {run.id}  {run.status}  {when}{spent(run)}")
    pushed = f"pushed at {run.head}" if run.head else "nothing pushed"
    click.echo(f"    {run.branch}: {pushed}")
    result = result_of(run)
    prs = result.get("prs")
    for pr in prs if isinstance(prs, list) else []:
        if isinstance(pr, str) and contract.plain_url(pr, task_worker.MAX_PR_URL):
            click.echo(f"    PR {pr}")
    said = one_line(str(result.get("harness") or ""))
    if said:
        click.echo(f"    harness: {said}")
    click.echo(f"    log {run.log_path}")


def _state(ctx: Context, task: records.Task) -> str:
    """A task's state, as `task list` and `show` say it: queued, running, its last run's status, or stopped.

    Returns:
        The state, in a word or two.
    """
    runs = tasks.runs_of(ctx.conn, task.id)
    latest = runs[-1] if runs else None
    if latest is not None and latest.status is TaskRunStatus.RUNNING:
        return "running" if task.stopped_at is None else "stopped, its run finishing"
    if task.stopped_at is not None:
        return "stopped"
    return "queued" if latest is None else str(latest.status)


def _operator(verb: str) -> None:
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"{verb} refused ({r.guard}): {r.reason}") from None
