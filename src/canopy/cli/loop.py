"""`canopy loop` and `canopy tick`, and what the operator reads back: `canopy status` and `canopy decisions`."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click
from rich.console import Console

from canopy.cli.common import CliError, open_context
from canopy.cli.params import TICKET_KEY
from canopy.cli.render import chore_line, named, one_line, phase_of, prs_of, result_of, spent
from canopy.core import chore_view, contract, conversation, db, notice, pause, review_requests
from canopy.infra import hangup, keys, lock
from canopy.loop import attention, repeat, reread, tick
from canopy.notify import deliver

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context

# `canopy status` lists this many runs that ended.
RECENT_RUNS = 10


@click.command("loop")
@click.option("--dry-run", is_flag=True, help="Every tick is a dry run: the overseer plans, nothing is dispatched.")
@click.option(
    "--every",
    type=click.IntRange(min=1),
    metavar="MINUTES",
    help=(
        "Minutes to wait after each tick ends, kept on a reload; never less than loop.min_gap_minutes from the tick's"
        " start. Default: loop.interval_minutes."
    ),
)
@click.option("--ticks", "max_ticks", type=click.IntRange(min=1), metavar="N", help="Stop after N ticks.")
@click.option(
    "--defer",
    type=click.IntRange(min=1),
    metavar="MINUTES",
    help="Wait MINUTES before the first tick. Press t during the wait to tick sooner.",
)
@click.option("--no-serve", is_flag=True, help="Do not serve the web UI, whatever serve.enabled says.")
@click.pass_context
def cmd_loop(
    click_ctx: click.Context,
    *,
    dry_run: bool,
    every: int | None,
    max_ticks: int | None,
    defer: int | None,
    no_serve: bool,
) -> int:
    """Run ticks in the foreground, waiting between them, until stopped. Serves the web UI unless told not to.

    SIGHUP reads the config again, once the running tick ends.
    """
    ctx = open_context(click_ctx, migrate=False)  # the loop migrates under its own lock
    stop = repeat.Stop()
    reload = reread.Reload()
    console = Console(highlight=False)
    # Keys only when the countdown is drawn: with output to a file, there is no one at the terminal to tell about them.
    with (
        hangup.watch() as hung_up,
        repeat.signals(stop, reload, hung_up=hung_up),
        keys.listen(sys.stdin if console.is_terminal else None) as pressed,
    ):
        try:
            repeat.run(
                ctx,
                dry_run=dry_run,
                interval_minutes=every,
                max_ticks=max_ticks,
                console=console,
                stop=stop,
                reload=reload,
                serve=ctx.config.serve.enabled and not no_serve,
                keys=pressed,
                defer_minutes=defer,
            )
        except lock.LockBusyError:
            raise CliError(f"another canopy loop is running on {ctx.state_dir}; stop it first") from None
    return 0


@click.command("tick")
@click.option("--dry-run", is_flag=True, help="Run the overseer, but dispatch nothing.")
@click.pass_context
def cmd_tick(click_ctx: click.Context, *, dry_run: bool) -> int:
    """Run one tick of the loop."""
    ctx = open_context(click_ctx, migrate=False)
    outcome = tick.run(ctx, dry_run=dry_run)
    label = f"tick {outcome.tick_id}" if outcome.tick_id is not None else "tick"
    cost = f" (cost {outcome.usage.describe()})" if outcome.usage is not None else ""
    click.echo(f"{label}: {outcome.status}: {outcome.summary}{cost}")
    return 0 if outcome.status in ("ok", "lock_busy") else 1


@click.command("status")
@click.pass_context
def cmd_status(click_ctx: click.Context) -> int:
    """Print the attention list, started tickets, running workers, and recent runs."""
    ctx = open_context(click_ctx)
    last = db.last_tick(ctx.conn)
    if last is None:
        click.echo("No ticks yet.")
    else:
        dry = " (dry run)" if last["dry_run"] else ""
        started = f"started {attention.age(last['started_at'])} ago"
        click.echo(f"Last tick: {last['id']} {last['status']}{dry}, {started}{spent(last)}")
        if last["summary"]:
            click.echo(f"  {last['summary']}")
    held = pause.paused(ctx.conn)
    if held is not None:
        click.echo(f"Loop paused {attention.age(held.since)} ago ({held.channel}): no tick until `canopy resume`.")
    told = notice.current(ctx.conn)
    if told is not None:
        click.echo(notice.describe(told, datetime.now(UTC)))

    _print_attention(attention.listed(ctx))
    _print_started(ctx)
    _print_review_requests(ctx)
    _print_workers(ctx)
    _print_recent_runs(ctx)
    _print_chores(ctx)
    _print_sinks(ctx)
    return 0


def _print_sinks(ctx: Context) -> None:
    """A line per notification sink: its last delivery, failures in a row and the last error, events waiting."""
    sinks = deliver.status(ctx)
    if not sinks:
        return
    click.echo(f"\nNotification sinks ({len(sinks)}):")
    for s in sinks:
        last = f"last delivered {attention.age(s.last_delivery_at)} ago" if s.last_delivery_at else "never delivered"
        failing = f"; {s.failures} failed in a row: {s.last_error}" if s.failures else ""
        click.echo(f"  {s.name}  {last}; {s.waiting} events waiting{failing}")


def _print_attention(items: Sequence[attention.Item]) -> None:
    click.echo(f"\nAttention ({len(items)}):")
    reasons = [i for i in items if not i.finding]
    for group in sorted({i.reason for i in reasons}):
        click.echo(f"  {group}")
        for item in (i for i in reasons if i.reason == group):
            click.echo(f"    {item.subject}  {attention.age(item.since)}  {item.detail}")
    findings = [i for i in items if i.finding]
    for chore in sorted({i.subject for i in findings}):
        click.echo(f"  {chore} findings")
        for item in (i for i in findings if i.subject == chore):
            click.echo(f"    {item.reason}  {attention.age(item.since)}  {item.detail}")
    if not items:
        click.echo("  nothing needs you")


def _print_started(ctx: Context) -> None:
    """A line per ticket the operator started (DESIGN §22): its state, its phase, and whether it waits on a reply."""
    records = [r for r in db.starts(ctx.conn) if r.subject_kind == conversation.TICKET]
    if not records:
        return
    click.echo(f"\nStarted ({len(records)}):")
    for r in records:
        key = r.subject_id
        ticket = db.get_ticket(ctx.conn, key)
        phase = phase_of(ctx.conn, ticket) if ticket is not None else "not seen by a tick yet"
        done = ", done" if ticket is not None and ticket.done else ""
        waiting = conversation.latest_question(ctx.conn, key) if conversation.is_started(r) else None
        note = f"  awaiting your reply to message {waiting['id']}" if waiting is not None else ""
        title = ticket.title if ticket is not None else None
        since = attention.age(r.stopped_at or r.started_at)
        click.echo(f"  {named(key, title)}  {r.status} {since} ago  phase {phase}{done}{note}")


def _print_review_requests(ctx: Context) -> None:
    """A line per PR the operator asked canopy to review (DESIGN §21): when, and its latest review."""
    requests = review_requests.open_requests(ctx.conn)
    if not requests:
        return
    click.echo(f"\nReview requests ({len(requests)}):")
    for r in requests:
        runs = db.review_runs_of(ctx.conn, r.pr_url)
        latest = f"latest review:{runs[0].id} {runs[0].status}" if runs else "not reviewed yet"
        click.echo(f"  {r.pr_url}  {attention.age(r.created_at)} ago  {latest}")


def _print_workers(ctx: Context) -> None:
    running = db.running_runs(ctx.conn, "runs")
    slots = db.all_run_slots(ctx.conn, [int(r["id"]) for r in running])
    busy = len(running) + len(db.running_runs(ctx.conn, "review_runs"))
    click.echo(f"\nRunning workers ({busy}/{ctx.config.capacity.max_workers}):")
    for r in running:
        # A joint run holds a slot in each of its repositories.
        where = ", ".join(f"{s['repo']} {s['slot_path']}" for s in slots[int(r["id"])])
        click.echo(
            f"  {named(r['ticket_key'], r['ticket_title'])}  {r['kind']}  {attention.age(r['started_at'])}  {where}"
        )
        # What its worker reported so far (DESIGN §8): nothing until its first event, or ever without `--format json`.
        if r["session_id"]:
            click.echo(f"    session {r['session_id']}{spent(r)}{_doing(r)}")
    # A review holds a slot and counts toward max_workers (DESIGN §21).
    for r in db.running_runs(ctx.conn, "review_runs"):
        click.echo(f"  review  {r['pr_url']}  {attention.age(r['started_at'])}  {r['slot_path'] or ''}".rstrip())
    if not running and not db.running_runs(ctx.conn, "review_runs"):
        click.echo("  none")


def _doing(run: sqlite3.Row) -> str:
    """A running run's latest tool call, as `  last bash: make check 12s ago`, or empty before its first.

    Returns:
        The tool, what it did, and how long ago, fit for the end of a line; empty when no call is recorded.
    """
    if run["activity_tool"] is None or run["activity_at"] is None:
        return ""
    did = f"{run['activity_tool']}: {run['activity']}" if run["activity"] else str(run["activity_tool"])
    return f"  last {one_line(did)} {attention.age(str(run['activity_at']))} ago"


def _print_recent_runs(ctx: Context) -> None:
    """Three lines per run that ended, the last to end first: what it was and its PRs, what it said, where to look."""
    runs = db.recent_runs(ctx.conn, RECENT_RUNS)
    click.echo(f"\nRecent runs ({len(runs)}):")
    for r in runs:
        result = result_of(r)
        ended = f"{attention.age(str(r['ended_at']))} ago"
        prs = "".join(f"  {pr}" for pr in prs_of(result))
        click.echo(f"  {named(r['ticket_key'], r['ticket_title'])}  {r['kind']}  {r['status']}  {ended}{prs}")
        said = one_line(contract.stored_note(result))
        if said:
            click.echo(f"    {said}")
        session = f"session {r['session_id']}" if r["session_id"] else "no session reported"
        click.echo(f"    {session}{spent(r)}  log {r['log_path']}")
    if not runs:
        click.echo("  none")


def _print_chores(ctx: Context) -> None:
    """A line per configured chore, with how many findings the operator dismissed; nothing when there are none (§19)."""
    states = chore_view.states(ctx.conn, ctx.config, ctx.workspace)
    if not states:
        return
    chores = len(db.running_runs(ctx.conn, "chore_runs"))
    click.echo(f"\nChores ({chores}/{ctx.config.capacity.max_chores} running):")
    now = datetime.now(UTC)
    for state in states:
        dismissed = sum(f.dismissed for f in state.findings())
        note = f"; {dismissed} finding{'s' if dismissed != 1 else ''} dismissed" if dismissed else ""
        click.echo(f"  {state.name}  {chore_line(state, now)}{note}")


@click.command("decisions")
@click.argument("tick_id", required=False, type=click.IntRange(min=1))
@click.option("--ticket", "ticket_key", type=TICKET_KEY, help="Show decisions for this ticket key only.")
@click.pass_context
def cmd_decisions(click_ctx: click.Context, tick_id: int | None, ticket_key: str | None) -> int:
    """Print a tick's decisions, optionally filtered by ticket. Default: the latest tick."""
    ctx = open_context(click_ctx)
    row = db.last_tick(ctx.conn) if tick_id is None else db.get_tick(ctx.conn, tick_id)
    if row is None:
        if tick_id is not None:
            raise CliError(f"no tick {tick_id}")
        click.echo("No ticks yet.")
        return 0
    dry = " (dry run)" if row["dry_run"] else ""
    started = f"started {row['started_at']} ({attention.age(row['started_at'])} ago)"
    click.echo(f"Tick {row['id']}: {row['status']}{dry}, {started}")
    if row["summary"]:
        click.echo(f"  {row['summary']}")
    if row["session_id"] or row["cost_usd"] is not None:
        session = f"session {row['session_id']}" if row["session_id"] else "no session reported"
        click.echo(f"  overseer {session}{spent(row)}")
    output = ctx.state_dir / "ticks" / f"{row['id']}.log"
    if output.exists():
        click.echo(f"  overseer output: {output}")
    rows = db.decisions_for_tick(ctx.conn, int(row["id"]))
    if ticket_key is not None:
        rows = [decision for decision in rows if decision.ticket_key == ticket_key]
    click.echo(f"\nDecisions ({len(rows)}):")
    keys = [attention.decided_about(d) for d in rows]
    key_width = max((len(k) for k in keys), default=0)
    action_width = max((len(d.action) for d in rows), default=0)
    for key, d in zip(keys, rows, strict=True):
        rationale = " ".join(d.rationale.split())
        click.echo(f"  {key:<{key_width}}  {d.action:<{action_width}}  {rationale}")
    if not rows:
        click.echo(f"  none for ticket {ticket_key}" if ticket_key is not None else "  none")
    return 0
