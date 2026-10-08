"""The operator's verbs on a subject (DESIGN §22, D075): `canopy start`, `stop`, `reply`, `forget`, and `show`.

Each takes a reference whose shape names its kind: a ticket key, `REPO#N` or a PR's URL, `chore:NAME`, or `run:ID`. A
kind refuses a verb it does not take. `start`, `stop`, `reply`, and `forget` write through `canopy.core.conversation`,
which every channel shares, and refuse inside canopy's own ticks and runs.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from canopy.chores import view as chore_view
from canopy.cli.common import CliError, open_context
from canopy.cli.loop import chore_line, one_line, prs_of, result_of, spent
from canopy.core import conversation, db
from canopy.infra import logs
from canopy.loop import attention
from canopy.runs import halt, policy

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context
    from canopy.core.conversation import Ref

CLI = "cli"
# `canopy show` lists this many of a ticket's runs and messages.
SHOW_RUNS = 5
SHOW_MESSAGES = 100


def _ref(text: str, verb: str) -> Ref:
    try:
        ref = conversation.parse_ref(text)
        conversation.check_verb(ref, verb)
    except conversation.Refused as r:
        raise CliError(f"{verb} refused ({r.guard}): {r.reason}") from None
    return ref


def _operator(verb: str) -> None:
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"{verb} refused ({r.guard}): {r.reason}") from None


@click.command("start")
@click.argument("ref", metavar="REF")
@click.pass_context
def cmd_start(click_ctx: click.Context, ref: str) -> int:
    """Work a ticket privately: no queue label, and nothing canopy writes reaches the ticket.

    Its conversation, the workers' reports and questions and your replies, stays in canopy's journal: read it with
    `canopy show`, answer with `canopy reply`.
    """
    _operator("start")
    subject = _ref(ref, "start")
    ctx = open_context(click_ctx)
    try:
        started = conversation.start(ctx.conn, ctx.config, subject, repo=ctx.repo, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"start refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info("ticket started", extra={"ticket": subject.id, "already": started.already})
    state = "was already started" if started.already else "is started"
    click.echo(f"{subject} {state}, privately: workers read it and write nothing to it; their reports stay in canopy.")
    if started.running is not None:
        run = started.running
        kind = "private" if run["private"] else "public, dispatched before this start, so it may write to the ticket"
        click.echo(f"Run {run['id']} ({run['kind']}, {kind}) is still working it.")
    else:
        click.echo("The next tick picks it up. Follow it with `canopy show`; answer questions with `canopy reply`.")
    return 0


@click.command("stop")
@click.argument("ref", metavar="REF")
@click.option("--now", is_flag=True, help="Also end the run working it now, instead of letting it finish.")
@click.pass_context
def cmd_stop(click_ctx: click.Context, ref: str, *, now: bool) -> int:
    """Stop working a started ticket: nothing dispatches it again until `canopy start`.

    A running run finishes, unless --now ends it: its processes are killed, its slots returned, and it ends `stopped`.
    """
    _operator("stop")
    subject = _ref(ref, "stop")
    ctx = open_context(click_ctx)
    try:
        stopped = conversation.stop(ctx.conn, subject, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"stop refused ({r.guard}): {r.reason}") from None
    log = logs.for_tick(None)
    log.info("ticket stopped", extra={"ticket": subject.id, "now": now})
    click.echo(f"{subject} {'was already stopped' if stopped.already else 'is stopped'}; nothing dispatches it now.")
    run = stopped.running
    if run is None:
        return 0
    if not now:
        click.echo(f"Run {run['id']} ({run['kind']}) is still working it and will finish; --now ends it.")
        return 0
    if halt.end(ctx, run, log):
        click.echo(f"Run {run['id']} ({run['kind']}) was ended and its slots returned.")
    else:
        click.echo(f"Run {run['id']} ({run['kind']}) had already ended.")
    return 0


@click.command("reply")
@click.argument("ref", metavar="REF")
@click.argument("text", required=False)
@click.pass_context
def cmd_reply(click_ctx: click.Context, ref: str, text: str | None) -> int:
    """Answer a started ticket, with TEXT or, without it, stdin. The next tick reads it; a waiting loop wakes."""
    _operator("reply")
    subject = _ref(ref, "reply")
    body = text if text is not None else sys.stdin.read()
    ctx = open_context(click_ctx)
    try:
        replied = conversation.reply(ctx.conn, subject, body, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"reply refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info("operator replied", extra={"ticket": subject.id, "message_id": replied.message_id})
    answered = f", answering message {replied.answers}" if replied.answers is not None else ""
    if replied.new:
        click.echo(f"Recorded message {replied.message_id} on {subject}{answered}.")
    else:
        click.echo(f"Message {replied.message_id} on {subject} already says this{answered}; nothing new recorded.")
    return 0


@click.command("forget")
@click.argument("ref", metavar="REF")
@click.pass_context
def cmd_forget(click_ctx: click.Context, ref: str) -> int:
    """Forget a ticket's branch and PRs, so its next implement starts over on a new branch.

    Its runs and conversation stay in the journal for `canopy show`, and its runs still count toward the attempt limits.
    Close its PRs and delete its branch yourself: canopy never does.
    """
    _operator("forget")
    subject = _ref(ref, "forget")
    ctx = open_context(click_ctx)
    try:
        forgot = conversation.forget(ctx.conn, subject, dispatch_lock=ctx.dispatch_lock_path)
    except conversation.Refused as r:
        raise CliError(f"forget refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info(
        "ticket forgotten", extra={"ticket": subject.id, "branch": forgot.branch, "prs": forgot.prs}
    )
    click.echo(f"{subject} is forgotten: its next implement starts over on a new branch.")
    if forgot.branch is not None or forgot.prs:
        named = [*([f"branch {forgot.branch}"] if forgot.branch is not None else []), *forgot.prs]
        click.echo(f"canopy no longer tracks {', '.join(named)}.")
        click.echo(
            "Close its PRs and delete its branch on origin yourself: until you do, the overseer still finds them and "
            "the ticket cannot start over."
        )
    limit = ctx.config.policy.max_implement_attempts
    for (key, repo), counts in sorted(policy.attempts(ctx.conn, single=ctx.workspace.single).items(), key=str):
        if key == subject.id and counts["implement"] >= limit:
            where = "" if repo is None else f" in {repo}"
            click.echo(
                f"It has had {counts['implement']} implement runs{where}, and policy.max_implement_attempts is "
                f"{limit}: raise it in your config for another."
            )
    return 0


@click.command("show")
@click.argument("ref", metavar="REF")
@click.pass_context
def cmd_show(click_ctx: click.Context, ref: str) -> int:
    """Show a ticket's phase, PRs, recent runs, and conversation, a run (`run:ID`), or a chore (`chore:NAME`)."""
    subject = _ref(ref, "show")
    ctx = open_context(click_ctx)
    if subject.kind == conversation.RUN:
        _show_run(ctx, int(subject.id))
    elif subject.kind == conversation.CHORE:
        _show_chore(ctx, subject.id)
    else:
        _show_ticket(ctx, subject.id)
    return 0


def _show_ticket(ctx: Context, key: str) -> None:
    ticket = db.get_ticket(ctx.conn, key)
    record = conversation.start_of(ctx.conn, key)
    if ticket is None and record is None:
        raise CliError(f"canopy has no record of {key}")
    if record is None:
        how = "public: its queue label authorizes it; its conversation is on the ticket, and copied here"
    else:
        since = record["started_at"] if record["status"] == "started" else record["stopped_at"]
        how = f"private, {record['status']} {attention.age(str(since))} ago"
    click.echo(f"{key}: {how}")
    if ticket is not None:
        done = ", done" if ticket["done"] else ""
        click.echo(f"  phase {ticket['phase'] or 'unknown'}{done}; branch {ticket['branch'] or 'none yet'}")
        if ticket["forgotten_at"]:
            click.echo(
                f"  forgotten {attention.age(str(ticket['forgotten_at']))} ago: the runs and messages before then are "
                "history, and the loop reads only what came after"
            )
        for unit in db.units(ctx.conn, key):
            name = "" if ctx.workspace.single else f"{unit['repo']}  "
            click.echo(f"  {name}PR {unit['pr_url'] or 'none recorded'}  phase {unit['phase'] or 'unknown'}")
    _show_runs(ctx, key)
    _show_conversation(ctx, key, waits=conversation.is_started(record))


def _show_runs(ctx: Context, key: str) -> None:
    runs = db.runs_of(ctx.conn, key, SHOW_RUNS)
    click.echo(f"\nRecent runs ({len(runs)}):")
    for r in runs:
        when = f"started {attention.age(str(r['started_at']))} ago"
        if r["ended_at"]:
            when = f"ended {attention.age(str(r['ended_at']))} ago"
        click.echo(f"  run:{r['id']}  {r['kind']}  {r['status']}  {when}")
    if not runs:
        click.echo("  none")


def _show_conversation(ctx: Context, key: str, *, waits: bool) -> None:
    messages = db.messages_of(ctx.conn, conversation.TICKET, key, SHOW_MESSAGES)
    click.echo(f"\nConversation ({len(messages)}):")
    for m in messages:
        _echo_message(m)
    if not messages:
        click.echo("  none")
    waiting = conversation.latest_question(ctx.conn, key)
    if waiting is not None and waits:
        click.echo(f"\nMessage {waiting['id']} waits on your answer: canopy reply {key} 'your answer'")


def _echo_message(m: sqlite3.Row) -> None:
    click.echo(_message_head(m))
    for line in conversation.printable(str(m["body"])).splitlines():
        click.echo(f"    {line}")


def _message_head(m: sqlite3.Row) -> str:
    who = {"worker": "worker", "operator": "you", "tracker": "tracker"}.get(str(m["source"]), str(m["source"]))
    if m["comment_id"] is not None:
        # A tracker comment the overseer mirrored: a copy, which authorizes nothing (DESIGN §22).
        cut = ", truncated" if m["truncated"] else ""
        return (
            f"  #{m['id']}  {attention.age(str(m['at']))} ago  {who} comment {m['comment_id']} by {m['author']}, "
            f"written {m['commented_at']}{cut}"
        )
    about = f" (run:{m['run_id']})" if m["run_id"] else ""
    if m["answers"]:
        about += f" answering {m['answers']}"
    via = f" via {m['channel']}" if m["source"] == "operator" else ""
    return f"  #{m['id']}  {attention.age(str(m['at']))} ago  {who} {m['kind']}{about}{via}"


def _show_run(ctx: Context, run_id: int) -> None:
    run = db.get_run(ctx.conn, run_id)
    if run is None:
        raise CliError(f"no run {run_id}")
    private = ", private" if run["private"] else ""
    click.echo(f"run:{run_id}: {run['kind']} of {run['ticket_key']}{private}, {run['status']}")
    click.echo(f"  started {run['started_at']}" + (f", ended {run['ended_at']}" if run["ended_at"] else ""))
    if run["branch"]:
        click.echo(f"  branch {run['branch']}")
    for s in db.run_slots(ctx.conn, run_id):
        where = "" if ctx.workspace.single else f"{s['repo']}  "
        click.echo(f"  {where}slot {s['slot_path']}, from {s['base_branch']}")
    result = result_of(run)
    for pr in prs_of(result):
        click.echo(f"  PR {pr}")
    said = one_line(str(result.get("harness") or ""))
    if said:
        click.echo(f"  harness: {said}")
    session = f"session {run['session_id']}" if run["session_id"] else "no session reported"
    click.echo(f"  {session}{spent(run)}")
    click.echo(f"  log {run['log_path']}")
    messages = db.run_messages(ctx.conn, run_id)
    if messages:
        click.echo("\nMessages:")
    for m in messages:
        _echo_message(m)


def _show_chore(ctx: Context, name: str) -> None:
    found = [s for s in chore_view.states(ctx.conn, ctx.config, ctx.workspace) if s.name == name]
    if not found:
        raise CliError(f"no chore {name!r} is configured for this workspace")
    [state] = found
    click.echo(f"chore:{name}: {chore_line(state, datetime.now(UTC))}")
    latest = state.latest_ended
    if latest is not None:
        said = one_line(str(result_of(latest).get("harness") or result_of(latest).get("summary") or ""))
        click.echo(f"  latest run {latest['id']} {latest['status']}" + (f": {said}" if said else ""))
        click.echo(f"  log {latest['log_path']}")
    findings = state.findings()
    click.echo(f"\nOpen findings ({len(findings)}):")
    for f in findings:
        title = one_line(f.finding.title)
        click.echo(
            f"  {f.finding.id}  {attention.age(f.since)}  {title}" + (f"  {f.finding.link}" if f.finding.link else "")
        )
    if not findings:
        click.echo("  none")
