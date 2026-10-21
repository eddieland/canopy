"""`canopy _mcp`, the MCP server of canopy's tools (DESIGN §27), which the agent runtime starts for a run."""

from __future__ import annotations

import click

from canopy.cli.common import runner_of
from canopy.infra import procs
from canopy.loop import mcp


@click.command("_mcp", hidden=True)
@click.option("--chore", is_flag=True, help="Serve a chore's run its own history alone, not the overseer's verbs.")
@click.pass_context
def cmd_mcp(click_ctx: click.Context, *, chore: bool) -> int:
    """Serve the overseer's verbs as MCP tools over stdio, until stdin closes. Started by the runtime; not for people.

    With --chore, serve a chore's run the one tool that reads its own chore's history (DESIGN §19), and nothing else.

    A run a tool starts is spawned through an intermediate, so it is never the server's descendant: the runtime stops
    those when the overseer's run ends, and the run outlives the tick, as one `canopy dispatch` starts does.
    """
    runner = runner_of(click_ctx)
    # A test's fake runner is used as it is: it starts no process to reparent.
    if isinstance(runner, procs.SubprocessRunner):
        # Every run a tool starts is spawned by this runner, not the one `canopy dispatch` uses: what stage 2 removes
        # from those runs' environment, the server's own entry in the inline config (ROADMAP M48), goes in its
        # `unset` here too.
        runner = procs.SubprocessRunner(unset=runner.unset, reparent=True)
    return mcp.run_stdio(runner, chore=chore)
