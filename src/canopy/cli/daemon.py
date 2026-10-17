"""`canopy daemon start`, `stop`, and `status`: `canopy loop` detached from the terminal (DESIGN §6, D042).

`start` and `stop` refuse inside canopy's own ticks and runs, as `pause` does: an overseer that could stop the loop
could end every tick after its own.
"""

from __future__ import annotations

from pathlib import Path

import click

from canopy.cli.common import CliError, Group, open_context
from canopy.core import conversation, items, workspace
from canopy.loop import daemon


@click.group("daemon", cls=Group)
def daemon_group() -> None:
    """Run `canopy loop` in the background. Nothing is installed: it does not restart itself or start at login."""


@daemon_group.command("start", context_settings={"ignore_unknown_options": True})
@click.argument("loop_args", nargs=-1, type=click.UNPROCESSED, metavar="[LOOP OPTIONS]...")
@click.pass_context
def cmd_start(click_ctx: click.Context, loop_args: tuple[str, ...]) -> int:
    """Start `canopy loop`, with LOOP OPTIONS such as --dry-run or --no-serve, detached from this terminal.

    Its output is appended to .canopy/daemon.log. It runs until `canopy daemon stop`; SIGHUP reloads its config, as it
    does for a loop in the foreground.
    """
    _check_operator("start")
    ctx = open_context(click_ctx, migrate=False)  # the loop migrates under its own lock
    try:
        pid = daemon.start(ctx.runner, ctx.ws.root, ctx.ws.state_dir, loop_args)
    except daemon.DaemonError as e:
        raise CliError(str(e)) from None
    click.echo(f"canopy daemon started, pid {pid}; output in {ctx.ws.state_dir / daemon.LOG_FILE_NAME}")
    return 0


@daemon_group.command("stop")
def cmd_stop() -> int:
    """Stop the daemon: at once during its wait, or once its running tick ends. Dispatched workers keep running."""
    _check_operator("stop")
    stopped = daemon.stop(workspace.find(Path.cwd()).state_dir, waiting=_say_waiting)
    click.echo("canopy daemon is not running" if stopped is None else f"canopy daemon stopped, pid {stopped}")
    return 0


def _say_waiting(pid: int) -> None:
    click.echo(f"canopy daemon (pid {pid}) stops once its running tick ends; waiting")


@daemon_group.command("status")
def cmd_status() -> int:
    """Say whether the daemon runs, and where its output is. Exits 0 while it runs, 1 otherwise."""
    current = daemon.state(workspace.find(Path.cwd()).state_dir)
    if current.pid is not None and current.since is not None:
        started = items.age(current.since)
        click.echo(f"canopy daemon: running, pid {current.pid}, started {started} ago; output in {current.log_path}")
        return 0
    if current.foreground:
        click.echo("canopy daemon: not running; a canopy loop not started by it is running")
    elif current.exited:
        click.echo(f"canopy daemon: not running; it exited without `canopy daemon stop`, see {current.log_path}")
    else:
        click.echo("canopy daemon: not running")
    return 1


def _check_operator(verb: str) -> None:
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"daemon {verb} refused ({r.guard}): {r.reason}") from None
