"""`canopy agents`: what each of canopy's agents is offered once the runtime merges the operator's config into canopy's.

An MCP server or a skill an agent is offered costs each of its model calls whether it is used or not (DESIGN §13), and
the operator's own runtime config can deny it more than canopy's definitions do. This asks the runtime, started as a
run starts it, with canopy's definitions, so what it prints is what a run would be offered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.core import reports

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from canopy.runtime.agents import AgentOffer, Offerings


@click.command("agents")
@click.option("--json", "as_json", is_flag=True, help="Print what each agent is offered as one JSON object instead.")
@click.pass_context
def cmd_agents(click_ctx: click.Context, *, as_json: bool) -> int:
    """Print the MCP servers, skills, and built-in tools each of canopy's agents is offered, after your runtime config.

    A server's reach is `all` of its tools, `some`, with the rules that offer or deny the rest, or `none`. Deny what an
    agent never uses in your global runtime config, for that agent by name. The commands `runtime.allow_bash` allows an
    agent beyond its own bash rules follow its tools. Exits 1 when the runtime could not say.
    """
    ctx = open_context(click_ctx)
    try:
        found, allows = reports.offered(ctx)
    except reports.Refused as e:
        raise CliError(str(e)) from None
    failed = found.error is not None or any(a.error is not None for a in found.agents)
    if as_json:
        click.echo(reports.agents_json(found, allows))
        return int(failed)
    for line in render(found, allows):
        click.echo(line)
    return int(failed)


def render(found: Offerings, allows: Mapping[str, Sequence[str]]) -> list[str]:
    """What each agent is offered, as `canopy agents` prints it, with the commands `allows` gives it by agent name.

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
        if allows.get(offer.agent):
            # A pattern holds no `;` (`canopy.core.bash_allows`), so it parts them unmistakably.
            lines.append(f"  bash allowed by runtime.allow_bash: {'; '.join(allows[offer.agent])}")
    return lines


def _agent(offer: AgentOffer) -> list[str]:
    if offer.error is not None:
        return [offer.agent, f"  could not say: {offer.error}"]
    lines = [offer.agent]
    for server in offer.servers:
        why = f": {'; '.join(server.exceptions)}" if server.exceptions else ""
        lines.append(f"  {server.server}: {server.reach}{why}")
    denied = f"; denied {', '.join(offer.denied_skills)}" if offer.denied_skills else ""
    lines.extend(
        [
            f"  skills: {', '.join(offer.skills) or 'none'}{denied}",
            f"  built-in tools: {', '.join(offer.tools) or 'none'}",
        ],
    )
    return lines
