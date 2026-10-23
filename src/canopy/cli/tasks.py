"""`canopy task`: the operator's one-off tasks (DESIGN §36), and how `show`, `reply`, and `stop` treat `task:N`.

A submission writes through `canopy.core.tasks`, and a reply through `canopy.core.conversation`, each refusing inside
canopy's own ticks and runs (`inside_run`): only the operator hands canopy a task, or its next word. The next tick
starts a run, before the overseer, which never sees it; `canopy _task` (`cli/runs.py`) is its run.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from canopy.cli import attachments as attachments_cli
from canopy.cli.common import CliError, Group, open_context
from canopy.cli.params import REPO
from canopy.core import conversation, plans, task_tickets, tasks
from canopy.core.items import age
from canopy.core.vocab import RunStatus
from canopy.infra import logs
from canopy.infra.text import one_line, printable
from canopy.loop.render import result_of, spent
from canopy.runs import task_run

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

CLI = "cli"
#: How much of a task's text `canopy task list` shows on its line.
LIST_TEXT = 80
#: How much of a commit `canopy show task:N` shows.
SHORT_SHA = 12


@click.group("task", cls=Group)
def task_group() -> None:
    """Hand canopy one-off work in your own words, about no ticket, and list what you handed it (DESIGN §36)."""


@task_group.command("submit")
@click.argument("text", metavar="TEXT")
@click.option("--repo", type=REPO, help="The repository it runs in. Required when the workspace has several.")
@click.option(
    "--project",
    metavar="KEY",
    help="The tracker project its tickets may go in. None by default: it files no tickets.",
)
@click.pass_context
def cmd_task_submit(click_ctx: click.Context, text: str, repo: str | None, project: str | None) -> int:
    """Submit TEXT as a task, or read it from stdin when TEXT is `-`.

    The next tick starts it, before the overseer, in a slot of its repository, as capacity allows: at most
    capacity.max_tasks at once, within capacity.max_workers. Its worker works on the branch <branch_prefix>task/N,
    which it pushes only if it changes something; it opens a PR, as a draft, only when your text asks for one, and
    writes nothing to any existing ticket. With --project it may file unlabeled tickets in that project, and none
    elsewhere. `canopy show task:N` shows how each run went, its tickets, and its latest report.
    """
    try:
        # Before stdin is read: inside a run, it would wait on whatever the agent left open.
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"task submit refused ({r.guard}): {r.reason}") from None
    body = sys.stdin.read() if text == "-" else text
    ctx = open_context(click_ctx)
    try:
        task = tasks.submit(ctx.conn, ctx.workspace, body, repo=repo, project=project, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"task submit refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info("task submitted", extra={"task": task.id, "repo": task.repo, "channel": CLI})
    branch = tasks.branch(ctx.config.trust.branch_prefix, task.id)
    click.echo(f"Submitted task:{task.id}, to run in {task.repo} on {branch}; the next tick starts it.")
    if ctx.config.capacity.max_tasks == 0:
        click.echo("capacity.max_tasks is 0, so no tick starts a task until you raise it.")
    return 0


@task_group.command("list")
@click.pass_context
def cmd_task_list(click_ctx: click.Context) -> int:
    """List your tasks, the newest first, each with where it stands: queued, its latest run's status, or stopped."""
    ctx = open_context(click_ctx)
    found = tasks.every(ctx.conn)
    latest = tasks.latest_runs(ctx.conn)
    waiting = {t.id for t in tasks.queued(ctx.conn)}
    for task in found:
        text = one_line(task.text)
        cut = f"{text[:LIST_TEXT]}..." if len(text) > LIST_TEXT else text
        said = tasks.standing(task, latest.get(task.id), queued=task.id in waiting)
        click.echo(f"task:{task.id}  {said}  {task.repo}  {age(task.submitted_at)}  {cut}")
    if not found:
        click.echo("No tasks yet: `canopy task submit TEXT` hands canopy one.")
    return 0


def show(ctx: Context, task_id: int) -> None:
    """Print task `task_id`: where it stands, its text, each run, its tickets, its conversation, and its report.

    Each run is shown with its branch and the head it left on origin; the newest report as its file stands (§36).

    Raises:
        CliError: canopy has no such task.
    """
    task = tasks.get(ctx.conn, task_id)
    if task is None:
        raise CliError(f"canopy has no task:{task_id}")
    runs = tasks.runs_of(ctx.conn, task_id)
    waiting = any(t.id == task_id for t in tasks.queued(ctx.conn))
    said = tasks.standing(task, runs[-1] if runs else None, queued=waiting)
    click.echo(f"task:{task.id}: {said}, in {task.repo}, submitted {age(task.submitted_at)} ago via {task.channel}")
    if task.stopped_at is not None:
        click.echo(f"  stopped {age(task.stopped_at)} ago")
    click.echo(f"  project {task.project}" if task.project else "  no project: it files no tickets")
    click.echo(f"  branch {tasks.branch(ctx.config.trust.branch_prefix, task.id)}")
    click.echo("\nText:")
    for line in printable(task.text).splitlines():
        click.echo(f"    {line}")
    click.echo(f"\nRuns ({len(runs)}):")
    for run in runs:
        _show_run(ctx, run)
    if not runs:
        click.echo("  none yet: the next tick starts it" if task.stopped_at is None else "  none")
    _show_tickets(ctx, task)
    attachments_cli.listed(ctx, conversation.Ref(conversation.TASK, str(task_id)))
    messages = tasks.messages_of(ctx.conn, task_id)
    if messages:
        click.echo(f"\nConversation ({len(messages)}):")
    for message in messages:
        _show_message(message)
    reported = [r for r in runs if r.report_sha256 is not None]
    if reported:
        _show_report(ctx, reported[-1])
    question = conversation.task_question(ctx.conn, task_id)
    if question is not None and task.stopped_at is None:
        click.echo(f"\nMessage {question.id} waits on your answer: `canopy reply task:{task_id} TEXT`.")


def replied(ctx: Context, task_id: int) -> None:
    """Say what a reply to task `task_id` starts: its next run, at the next tick or once its running run ends."""
    running = next((r for r in tasks.runs_of(ctx.conn, task_id) if r.status is RunStatus.RUNNING), None)
    if running is not None:
        click.echo(f"Its run {running.id} is still working; the first tick after it ends starts the next run.")
    else:
        click.echo("The next tick starts its next run, on its branch.")


def stop(ctx: Context, task_id: int, *, now: bool) -> int:
    """Stop task `task_id`: no tick starts it again, a queued one is dropped, and `now` ends its running run.

    Returns:
        0, once it has said what it did.

    Raises:
        CliError: the stop was refused.
    """
    try:
        stopped = tasks.stop(ctx.conn, task_id)
    except conversation.Refused as r:
        raise CliError(f"stop refused ({r.guard}): {r.reason}") from None
    log = logs.for_tick(None)
    log.info("task stopped", extra={"task": task_id, "now": now})
    if stopped.already:
        click.echo(f"task:{task_id} was already stopped.")
    elif stopped.dropped:
        click.echo(f"task:{task_id} is stopped; it had not started, and nothing starts it now.")
    else:
        click.echo(f"task:{task_id} is stopped; nothing starts it again.")
    run = stopped.running
    if run is None:
        return 0
    if not now:
        click.echo(f"Its run {run.id} is still working and will finish; --now ends it.")
        return 0
    if task_run.stop_now(ctx, run, log):
        click.echo(f"Its run {run.id} was ended and its slot returned.")
    else:
        click.echo(f"Its run {run.id} had already ended.")
    return 0


def _show_run(ctx: Context, run: records.TaskRun) -> None:
    when = f"started {age(run.started_at)} ago"
    if run.ended_at:
        when = f"ended {age(run.ended_at)} ago"
    head = f"  head {run.head[:SHORT_SHA]}" if run.head else "  nothing pushed"
    click.echo(f"  run {run.id}  {run.status}  {when}  {run.branch}{head}{spent(run)}")
    result = result_of(run)
    # Its summary and question are messages, in the conversation below.
    for pr in tasks.prs(result):
        click.echo(f"    PR {pr}")
    note = one_line(str(result.get("harness") or ""))
    if note:
        click.echo(f"    harness: {note}")
    if run.report_sha256 is not None:
        path = tasks.report_path(ctx.state_dir, run.task_id, run.id)
        click.echo(f"    report {path}{_report_state(run, plans.read(path))}")
    session = f"session {run.session_id}" if run.session_id else "no session reported"
    click.echo(f"    {session}, log {run.log_path}")


def _show_tickets(ctx: Context, task: records.Task) -> None:
    # A task with no project files none, as its header says; what a run reported anyway is in its note.
    filed = task_tickets.of_task(ctx.conn, task.id)
    if task.project is None and not filed:
        return
    click.echo(f"\nTickets ({len(filed)}), unlabeled, each worked only once you label or start it:")
    for ticket in filed:
        click.echo(f"  {ticket.key}  reported by run {ticket.task_run_id}")
    if not filed:
        click.echo("  none")


def _show_report(ctx: Context, run: records.TaskRun) -> None:
    path = tasks.report_path(ctx.state_dir, run.task_id, run.id)
    reading = plans.read(path)
    click.echo(f"\nReport, as run {run.id} left it: {path}{_report_state(run, reading)}")
    if reading.text is not None:
        click.echo("")
        for line in printable(reading.text).splitlines():
            click.echo(f"    {line}")


def _report_state(run: records.TaskRun, reading: plans.Reading) -> str:
    # How a kept report's file stands: as its run left it, edited since, or no longer a report, and why.
    if reading.problem is not None:
        return f": its file is {reading.problem}"
    if reading.sha256 != run.report_sha256:
        return ": edited since its run left it"
    return ""


def _show_message(message: records.Message) -> None:
    if message.source == "operator":
        what = "your reply" + (f" to message {message.answers}" if message.answers else "") + f" via {message.channel}"
    else:
        what = f"run {message.task_run_id}'s {message.kind}" if message.task_run_id else message.kind
    click.echo(f"  message {message.id}, {what}, {age(message.at)} ago:")
    for line in printable(message.body).splitlines() or [""]:
        click.echo(f"    {line}")
