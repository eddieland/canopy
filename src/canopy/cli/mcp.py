"""`canopy _mcp`, the MCP server of canopy's tools (DESIGN §27), which the agent runtime starts for a run."""

from __future__ import annotations

import os
from pathlib import Path

import click

from canopy.cli.common import runner_of
from canopy.cli.params import CheckoutType
from canopy.core import git_tools
from canopy.infra import procs
from canopy.loop import mcp


@click.command("_mcp", hidden=True)
@click.option("--chore", is_flag=True, help="Serve a chore's run its own history alone, not the overseer's verbs.")
@click.option(
    "--reports",
    "serve_reports",
    is_flag=True,
    help="Serve canopy's read-only reports alone (health, spend, memory), not the overseer's verbs.",
)
@click.option(
    "--git",
    "checkouts",
    type=CheckoutType(),
    multiple=True,
    help="Serve read-only git in the checkout PATH, named NAME, alone; repeat for each checkout the run reads.",
)
@click.pass_context
def cmd_mcp(
    click_ctx: click.Context,
    *,
    chore: bool,
    serve_reports: bool,
    checkouts: tuple[tuple[str, Path], ...],
) -> int:
    """Serve the overseer's verbs as MCP tools over stdio, until stdin closes. Started by the runtime; not for people.

    With --chore, serve a chore's run the one tool that reads its own chore's history (DESIGN §19), and nothing else.
    With --reports, serve a chore's run canopy's read-only reports, what `canopy health`, `spend`, and the memory
    listings print with `--json`, and nothing else.
    With --git, serve a review's or a plan's run read-only git in the checkouts it names, and nothing else.

    A run a tool starts is spawned through an intermediate, so it is never the server's descendant: the runtime stops
    those when the overseer's run ends, and the run outlives the tick, as one `canopy dispatch` starts does.
    """
    if chore + serve_reports + bool(checkouts) > 1:
        raise click.UsageError("--chore, --reports, and --git each name what the server serves: give one")
    runner = runner_of(click_ctx)
    # A test's fake runner is used as it is: it starts no process to reparent.
    if isinstance(runner, procs.SubprocessRunner):
        if checkouts:
            # git reads no variable the runtime passed down, such as one naming another repository or config.
            return mcp.run_stdio(
                procs.SubprocessRunner(unset={*runner.unset, *git_tools.inherited(os.environ)}),
                checkouts=dict(checkouts),
            )
        # Every run a tool starts is spawned by this runner, not the one `canopy dispatch` uses: what stage 2 removes
        # from those runs' environment, the server's own entry in the inline config (ROADMAP M48), goes in its
        # `unset` here too.
        runner = procs.SubprocessRunner(unset=runner.unset, reparent=True)
    return mcp.run_stdio(runner, chore=chore, serve_reports=serve_reports, checkouts=dict(checkouts))
