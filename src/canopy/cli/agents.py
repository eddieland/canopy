"""`canopy agents`: what each of canopy's agents is offered once the runtime merges the operator's config into canopy's.

An MCP server or a skill an agent is offered costs each of its model calls whether it is used or not (DESIGN §13), and
the operator's own runtime config can deny it more than canopy's definitions do. This asks the runtime, started as a
run starts it, with canopy's definitions, so what it prints is what a run would be offered.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.cli.render import report_json
from canopy.core import definitions
from canopy.runtime import definitions as runtime_definitions
from canopy.runtime import offerings

if TYPE_CHECKING:
    from canopy.runtime.agents import AgentOffer, Offerings


@click.command("agents")
@click.option("--json", "as_json", is_flag=True, help="Print what each agent is offered as one JSON object instead.")
@click.pass_context
def cmd_agents(click_ctx: click.Context, *, as_json: bool) -> int:
    """Print the MCP servers and skills each of canopy's agents is offered, after your own runtime config.

    A server's reach is `all` of its tools, `some`, with the rules that offer or deny the rest, or `none`. Deny what an
    agent never uses in your global runtime config, for that agent by name. Exits 1 when the runtime could not say.
    """
    ctx = open_context(click_ctx)
    try:
        snapshot = definitions.ensure(ctx.ws.state_dir, ctx.config)
    except definitions.DefinitionsError as e:
        raise CliError(f"agents: {e}") from None
    found = offerings.offerings(
        ctx.runner,
        cwd=ctx.ws.root,
        definitions_dir=snapshot,
        agents=runtime_definitions.agent_names(),
    )
    failed = found.error is not None or any(a.error is not None for a in found.agents)
    if as_json:
        click.echo(report_json(dataclasses.asdict(found)))
        return int(failed)
    for line in render(found):
        click.echo(line)
    return int(failed)


def render(found: Offerings) -> list[str]:
    """What each agent is offered, as `canopy agents` prints it.

    Returns:
        Its lines, without line ends.
    """
    if found.error is not None:
        return [f"The runtime could not say what it offers: {found.error}"]
    off = f" (off for every agent: {', '.join(found.disabled_servers)})" if found.disabled_servers else ""
    lines = [
        f"MCP servers: {', '.join(found.servers) or 'none'}{off}.",
        f"Skills: {', '.join(found.skills) or 'none'}.",
    ]
    for offer in found.agents:
        lines.extend(["", *_agent(offer)])
    return lines


def _agent(offer: AgentOffer) -> list[str]:
    if offer.error is not None:
        return [offer.agent, f"  could not say: {offer.error}"]
    lines = [offer.agent]
    for server in offer.servers:
        why = f": {'; '.join(server.exceptions)}" if server.exceptions else ""
        lines.append(f"  {server.server}: {server.reach}{why}")
    denied = f"; denied {', '.join(offer.denied_skills)}" if offer.denied_skills else ""
    lines.append(f"  skills: {', '.join(offer.skills) or 'none'}{denied}")
    return lines
