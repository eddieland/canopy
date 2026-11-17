"""`canopy notify`: send a test message to the notification sinks, and list the events they can take (DESIGN §20)."""

from __future__ import annotations

import json
from typing import Final

import click

from canopy.cli.common import CliError, open_context
from canopy.core import conversation, event_names, outbox
from canopy.notify import deliver

#: What `canopy notify events` says of the attention list, which is a diff of items, not a point event with fields.
_ATTENTION: Final = (
    "the attention list's items added and resolved since the sink last heard: the json format's `attention`"
)


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


@notify_group.command("events")
@click.pass_context
def cmd_notify_events(click_ctx: click.Context) -> int:
    """List every event name canopy can send, an example of its fields, and which configured sinks take it.

    A sink's `events` lists patterns over these names: `*` matches one segment, `**` any number, a bare group every
    event of it, and a leading `!` excludes. A sink that takes a name for some subjects alone, such as `runs.PROJ-1.*`,
    is listed under `for some`.
    """
    ctx = open_context(click_ctx)
    sinks = {name: sink.patterns() for name, sink in ctx.config.notify.all_sinks().items()}
    for spec in event_names.SPECS:
        taken = {name: event_names.taken(patterns, spec) for name, patterns in sinks.items()}
        every = [name for name, how in taken.items() if how == "all"]
        some = [name for name, how in taken.items() if how == "some"]
        click.echo(spec.template if spec.kind == outbox.ATTENTION else f"{spec.template}  ({spec.kind})")
        line = f"  taken by: {', '.join(every) or 'no sink'}"
        click.echo(f"{line}; for some {spec.subject}s: {', '.join(some)}" if some else line)
        example = outbox.EXAMPLES.get(spec.kind)
        click.echo(f"  {json.dumps(example)}" if example is not None else f"  {_ATTENTION}")
    return 0
