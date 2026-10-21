"""`canopy _mcp`, the MCP server of canopy's tools (DESIGN §27), which the agent runtime starts for a run."""

from __future__ import annotations

import os

import click

from canopy.cli.common import runner_of
from canopy.core import git_reads
from canopy.infra import procs
from canopy.loop import mcp


@click.command("_mcp", hidden=True)
@click.option("--chore", is_flag=True, help="Serve a chore's run its own history alone, not the overseer's verbs.")
@click.option("--git", is_flag=True, help="Serve a review's or a plan's run read-only git alone, in its checkouts.")
@click.pass_context
def cmd_mcp(click_ctx: click.Context, *, chore: bool, git: bool) -> int:
    """Serve the overseer's verbs as MCP tools over stdio, until stdin closes. Started by the runtime; not for people.

    With --chore, serve a chore's run the one tool that reads its own chore's history (DESIGN §19), and nothing else.
    With --git, serve a review's or a plan's run the tools that read its checkouts' history, and nothing else.

    A run a tool starts is spawned through an intermediate, so it is never the server's descendant: the runtime stops
    those when the overseer's run ends, and the run outlives the tick, as one `canopy dispatch` starts does.

    Raises:
        click.UsageError: Both --chore and --git were given.
    """
    if chore and git:
        raise click.UsageError("--chore and --git each serve one kind of run: give one")
    runner = runner_of(click_ctx)
    # A test's fake runner is used as it is: it starts no process to reparent.
    if isinstance(runner, procs.SubprocessRunner):
        if git:
            # git inherits none of the variables that would choose its repository, a program, or config for it.
            unset = {*runner.unset, *git_reads.inherited(os.environ)}
            return mcp.run_stdio(procs.SubprocessRunner(unset=unset), git=True)
        # Every run a tool starts is spawned by this runner, not the one `canopy dispatch` uses: what stage 2 removes
        # from those runs' environment, the server's own entry in the inline config (ROADMAP M48), goes in its
        # `unset` here too.
        runner = procs.SubprocessRunner(unset=runner.unset, reparent=True)
    return mcp.run_stdio(runner, chore=chore, git=git)
