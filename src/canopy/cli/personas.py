"""`canopy personas`: each persona a run could get, where it comes from, and the agents it is the default for (§31)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from canopy.cli.common import open_context
from canopy.core import personas

if TYPE_CHECKING:
    from canopy.core.config import Config


@click.command("personas")
@click.pass_context
def cmd_personas(click_ctx: click.Context) -> int:
    """List each persona: canopy's own, and yours in paths.personas, which shadow canopy's of the same name.

    Each line says where the persona comes from and which agents [personas] names it for. A run whose persona has no
    file, or one canopy will not put in a prompt, is refused, never run in another voice. Exits 1 when an agent's
    persona is such a one.
    """
    ctx = open_context(click_ctx)
    lines, refused = render(ctx.config)
    for line in lines:
        click.echo(line)
    return int(refused)


def render(config: Config) -> tuple[list[str], bool]:
    """The personas as `canopy personas` prints them, and whether an agent's runs would refuse their persona.

    Returns:
        The lines, without line ends: a line per persona, then one per agent whose persona has no file; and True when
        an agent's persona has no file or a file canopy will not use.
    """
    found = personas.listed(config)
    lines = [f"Personas ({len(found)}):"]
    for p in found:
        where = f"yours, {p.path}" if p.yours else "canopy's"
        where += ", in place of canopy's" if p.shadows else ""
        default = f"; the default for {', '.join(p.defaults)}" if p.defaults else ""
        lines.append(f"  {p.name}  {where}{default}")
        if p.error is not None:
            lines.append(f"    refused ({personas.BAD}): {p.error}")
    listed = {p.name for p in found}
    missing = [a for a in personas.AGENTS if getattr(config.personas, a) not in listed]
    lines.extend(
        f"[personas] {agent} names {getattr(config.personas, agent)}, which has no file: its runs refuse "
        f"({personas.MISSING})."
        for agent in missing
    )
    refused = bool(missing) or any(p.error is not None and p.defaults for p in found)
    return lines, refused
