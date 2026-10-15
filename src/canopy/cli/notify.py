"""`canopy notify test`: send a test message to the notification sinks, outside any tick (DESIGN §20)."""

from __future__ import annotations

import click

from canopy.cli.common import CliError, open_context
from canopy.core import conversation
from canopy.notify import deliver


@click.group("notify")
def notify_group() -> None:
    """Notification sinks."""


@notify_group.command("test")
@click.argument("sink", required=False)
@click.pass_context
def cmd_notify_test(click_ctx: click.Context, sink: str | None) -> int:
    """Send a test message to every sink, or to SINK, now, and print each result. Changes nothing in the journal."""
    # Neither the overseer nor a run it started may page the operator (DESIGN §20).
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"notify test refused ({r.guard}): {r.reason}") from None
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
