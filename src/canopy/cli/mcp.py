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
from canopy.runtime import servers


@click.command("_mcp", hidden=True)
@click.option("--chore", is_flag=True, help="Serve a chore's run its own history alone, not the overseer's verbs.")
@click.option(
    "--reports",
    "serve_reports",
    is_flag=True,
    help="Serve canopy's read-only reports alone (health, spend, memory), not the overseer's verbs.",
)
@click.option(
    "--status",
    is_flag=True,
    help="Serve a worker's, planner's, or reviewer's run the one tool it posts progress with, which writes nothing.",
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
    status: bool,
    checkouts: tuple[tuple[str, Path], ...],
) -> int:
    """Serve the overseer's verbs as MCP tools over stdio, until stdin closes. Started by the runtime; not for people.

    With --chore, serve a chore's run the one tool that reads its own chore's history (DESIGN §19), and nothing else.
    With --reports, serve a chore's run canopy's read-only reports, what `canopy health`, `spend`, the memory listings,
    `config show`, and `agents` print with `--json`, and `canopy decisions` and `show` of a run or a chore print, and
    nothing else.
    With --git, serve a review's or a plan's run read-only git in the checkouts it names, and nothing else.
    With --status, serve a worker's, planner's, or reviewer's run the `status` tool, which validates an update and
    writes nothing: canopy records the update from the call in the events the agent prints (DESIGN §41).

    A run a tool asks for is recorded, and the tick starts it once the overseer's run has ended (DESIGN §40), so no run
    is the server's descendant.
    """
    if chore + serve_reports + status + bool(checkouts) > 1:
        raise click.UsageError("--chore, --reports, --status, and --git each name what the server serves: give one")
    if status:
        # It opens no workspace and starts no process.
        return mcp.run_stdio(runner_of(click_ctx), status=True)
    runner = runner_of(click_ctx)
    # A test's fake runner is used as it is.
    if isinstance(runner, procs.SubprocessRunner):
        if checkouts:
            # git reads no variable the runtime passed down, such as one naming another repository or config.
            return mcp.run_stdio(
                procs.SubprocessRunner(unset={*runner.unset, *git_tools.inherited(os.environ)}),
                checkouts=dict(checkouts),
            )
        if serve_reports:
            # The runtime `agents` starts to ask what it offers is asked as a run would be, without the servers this
            # process's run was given in its inline config.
            return mcp.run_stdio(procs.SubprocessRunner(unset={*runner.unset, *servers.VARIABLES}), serve_reports=True)
        # The runtime started the server with the agent's whole environment, which names this server: nothing the server
        # runs, such as the runtime asked for its models at a dispatch's ask, inherits it (DESIGN §27).
        runner = procs.SubprocessRunner(unset={*runner.unset, *servers.VARIABLES})
    return mcp.run_stdio(runner, chore=chore, checkouts=dict(checkouts))
