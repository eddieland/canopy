"""`canopy _mcp`, the MCP server of the overseer's tools (DESIGN §27), which the agent runtime starts for it."""

from __future__ import annotations

import click

from canopy.infra import procs
from canopy.loop import mcp


@click.command("_mcp", hidden=True)
def cmd_mcp() -> int:
    """Serve the overseer's verbs as MCP tools over stdio, until stdin closes. Started by the runtime; not for people.

    A run a tool starts is spawned through an intermediate, so it is never the server's descendant: the runtime stops
    those when the overseer's run ends, and the run outlives the tick, as one `canopy dispatch` starts does.
    """
    return mcp.run_stdio(procs.SubprocessRunner(reparent=True))
