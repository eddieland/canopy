"""`canopy loop` and `canopy tick`, and what the operator reads back: `canopy status` and `canopy decisions`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click
from rich.console import Console

from canopy.chores import view as chore_view
from canopy.cli.common import CliError, open_context
from canopy.core import db
from canopy.infra import lock
from canopy.loop import attention, repeat, tick

if TYPE_CHECKING:
    from canopy.core.context import Context


@click.command("loop")
@click.option("--dry-run", is_flag=True, help="Every tick is a dry run: the overseer plans, nothing is dispatched.")
@click.option(
    "--every",
    type=click.IntRange(min=1),
    metavar="MINUTES",
    help="Minutes to wait after each tick ends. Default: loop.interval_minutes.",
)
@click.option("--ticks", "max_ticks", type=click.IntRange(min=1), metavar="N", help="Stop after N ticks.")
@click.pass_context
def cmd_loop(click_ctx: click.Context, *, dry_run: bool, every: int | None, max_ticks: int | None) -> int:
    """Run ticks in the foreground, waiting between them, until stopped."""
    ctx = open_context(click_ctx, migrate=False)  # the loop migrates under its own lock
    stop = repeat.Stop()
    with repeat.signals(stop):
        try:
            repeat.run(
                ctx,
                dry_run=dry_run,
                interval_minutes=every or ctx.config.loop.interval_minutes,
                max_ticks=max_ticks,
                console=Console(highlight=False),
                stop=stop,
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
    click.echo(f"{label}: {outcome.status}: {outcome.summary}")
    return 0 if outcome.status in ("ok", "lock_busy") else 1


@click.command("status")
@click.pass_context
def cmd_status(click_ctx: click.Context) -> int:
    """Print the attention list and running workers."""
    ctx = open_context(click_ctx)
    last = db.last_tick(ctx.conn)
    if last is None:
        click.echo("No ticks yet.")
    else:
        dry = " (dry run)" if last["dry_run"] else ""
        click.echo(f"Last tick: {last['id']} {last['status']}{dry}, started {attention.age(last['started_at'])} ago")
        if last["summary"]:
            click.echo(f"  {last['summary']}")

    _print_attention(attention.listed(ctx))
    _print_workers(ctx)
    _print_chores(ctx)
    return 0


def _print_attention(items: list[attention.Item]) -> None:
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


def _print_workers(ctx: Context) -> None:
    running = db.running_runs(ctx.conn)
    slots = db.all_run_slots(ctx.conn, [int(r["id"]) for r in running])
    click.echo(f"\nRunning workers ({len(running)}/{ctx.config.capacity.max_workers}):")
    for r in running:
        # A joint run holds a slot in each of its repositories; a workspace of one's needs no name.
        where = ", ".join(
            str(s["slot_path"]) if ctx.workspace.single else f"{s['repo']} {s['slot_path']}"
            for s in slots[int(r["id"])]
        )
        click.echo(f"  {r['ticket_key']}  {r['kind']}  {attention.age(r['started_at'])}  {where}")
    if not running:
        click.echo("  none")


def _print_chores(ctx: Context) -> None:
    """A line per configured chore; nothing at all when there are none (DESIGN §19)."""
    states = chore_view.states(ctx.conn, ctx.config, ctx.workspace)
    if not states:
        return
    click.echo(f"\nChores ({len(db.running_chore_runs(ctx.conn))}/{ctx.config.capacity.max_chores} running):")
    now = datetime.now(UTC)
    for state in states:
        click.echo(f"  {state.name}  {_chore_line(state, now)}")


def _chore_line(state: chore_view.ChoreState, now: datetime) -> str:
    if state.running is not None:
        return f"running for {attention.age(str(state.running['started_at']), now)}"
    latest = state.latest
    last = (
        "never run"
        if latest is None
        else f"last {latest['status']} {attention.age(str(latest['started_at']), now)} ago"
    )
    due = state.due_at()
    when = "due now" if due is None or due <= now else f"due in {attention.age(db.format_time(now), due)}"
    return f"{last}, {when}"


@click.command("decisions")
@click.argument("tick_id", required=False, type=click.IntRange(min=1))
@click.pass_context
def cmd_decisions(click_ctx: click.Context, tick_id: int | None) -> int:
    """Print a tick's decisions: what the overseer did, or in a dry run would have done. Default: the latest tick."""
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
    output = ctx.state_dir / "ticks" / f"{row['id']}.log"
    if output.exists():
        click.echo(f"  overseer output: {output}")
    rows = db.decisions_for_tick(ctx.conn, int(row["id"]))
    click.echo(f"\nDecisions ({len(rows)}):")
    keys = [attention.decided_about(d) for d in rows]
    key_width = max((len(k) for k in keys), default=0)
    action_width = max((len(str(d["action"])) for d in rows), default=0)
    for key, d in zip(keys, rows, strict=True):
        rationale = " ".join(str(d["rationale"]).split())
        click.echo(f"  {key:<{key_width}}  {d['action']:<{action_width}}  {rationale}")
    if not rows:
        click.echo("  none")
    return 0
