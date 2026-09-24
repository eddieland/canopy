"""`canopy tick`, and what the operator reads back: `canopy status` and `canopy decisions`."""

from __future__ import annotations

import click

from canopy.cli.common import CliError, open_context
from canopy.core import db
from canopy.loop import attention, tick


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

    items = attention.current(ctx.conn)
    click.echo(f"\nAttention ({len(items)}):")
    for group in sorted({i.reason for i in items}):
        click.echo(f"  {group}")
        for item in (i for i in items if i.reason == group):
            click.echo(f"    {item.ticket_key}  {attention.age(item.since)}  {item.detail}")
    if not items:
        click.echo("  nothing needs you")

    running = db.running_runs(ctx.conn)
    click.echo(f"\nRunning workers ({len(running)}/{ctx.config.capacity.max_workers}):")
    for r in running:
        click.echo(f"  {r['ticket_key']}  {r['kind']}  {attention.age(r['started_at'])}  {r['slot_path']}")
    if not running:
        click.echo("  none")
    return 0


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
    keys = [str(d["ticket_key"] or "-") for d in rows]
    key_width = max((len(k) for k in keys), default=0)
    action_width = max((len(str(d["action"])) for d in rows), default=0)
    for key, d in zip(keys, rows, strict=True):
        rationale = " ".join(str(d["rationale"]).split())
        click.echo(f"  {key:<{key_width}}  {d['action']:<{action_width}}  {rationale}")
    if not rows:
        click.echo("  none")
    return 0
