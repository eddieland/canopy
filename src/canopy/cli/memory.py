"""`canopy memory`: what workers recorded of what they learn, and the operator's lessons (DESIGN §28)."""

from __future__ import annotations

import click

from canopy.cli.common import Group, open_context
from canopy.core import memory


@click.group("memory", cls=Group)
def memory_group() -> None:
    """Read and manage agent memory: ticket notes, proposals, and lessons, while `[memory]` turns them on."""


@memory_group.command("list")
@click.pass_context
def cmd_list(click_ctx: click.Context) -> int:
    """List the ticket notes workers recorded, after each tier's mode in words."""
    ctx = open_context(click_ctx)
    readout = memory.readout(ctx.config.memory)
    if readout is None:
        click.echo(
            "Memory is off: memory.ticket_notes and memory.proposals are both off, so no worker writes memory and no "
            "run reads it."
        )
        return 0
    click.echo(f"{readout} ({memory.tiers(ctx.config.memory)})")
    return 0
