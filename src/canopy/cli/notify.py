"""`canopy notify`: test the notification sinks, and read a mailbox sink's messages (DESIGN §20)."""

from __future__ import annotations

import json
import os

import click

from canopy.cli.common import CliError, open_context
from canopy.core import mailbox
from canopy.loop import tick
from canopy.notify import deliver


@click.group("notify")
def notify_group() -> None:
    """Notification sinks."""


@notify_group.command("test")
@click.argument("sink", required=False)
@click.pass_context
def cmd_notify_test(click_ctx: click.Context, sink: str | None) -> int:
    """Send a test message to every sink, or to SINK, now, and print each result. Changes nothing in the journal."""
    # The overseer must not be able to page the operator (DESIGN §20).
    if os.environ.get(tick.TICK_ID_ENV):
        raise CliError(f"canopy notify test is for the operator; it refuses inside a tick ({tick.TICK_ID_ENV} is set)")
    ctx = open_context(click_ctx)
    sinks = ctx.config.notify.all_sinks()
    if not sinks:
        raise CliError("no notification sinks are configured: set notify.cmd or add a [notify.sinks.<name>] table")
    if sink is not None and sink not in sinks:
        raise CliError(f"no sink named {sink!r}; configured: {', '.join(sinks)}")
    results = deliver.test(ctx, [sink] if sink is not None else list(sinks))
    for result in results:
        detail = f": {result.detail}" if result.detail else ""
        click.echo(f"{result.sink}: {result.outcome}{detail}")
    return 0 if all(r.outcome == "delivered" for r in results) else 1


@notify_group.command("read")
@click.argument("sink")
@click.option("--after", type=click.IntRange(min=0), help="Only messages after this id. Default: the newest one.")
@click.pass_context
def cmd_notify_read(click_ctx: click.Context, sink: str, after: int | None) -> int:
    """Print mailbox sink SINK's kept messages as one JSON object, oldest first.

    `canopy-notify-relay --ssh` runs this on the machine canopy runs on, and shows each message on its own. Changes
    nothing in the journal: the relay keeps its own place.
    """
    if os.environ.get(tick.TICK_ID_ENV):
        raise CliError(f"canopy notify read is for the operator; it refuses inside a tick ({tick.TICK_ID_ENV} is set)")
    ctx = open_context(click_ctx)
    found = ctx.config.notify.all_sinks().get(sink)
    if found is None or not found.mailbox:
        mailboxes = [name for name, s in ctx.config.notify.all_sinks().items() if s.mailbox]
        raise CliError(f"no mailbox sink named {sink!r}; configured: {', '.join(mailboxes) or 'none'}")
    messages = [m.as_json() for m in mailbox.after(ctx.conn, sink, after)]
    click.echo(json.dumps({"sink": sink, "messages": messages}))
    return 0
