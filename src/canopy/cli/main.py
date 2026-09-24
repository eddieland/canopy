"""The `canopy` command line, built with click (D025). Each command group lives in its own module here."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import click

from canopy.cli import journal, loop, runs, setup
from canopy.cli.common import Obj
from canopy.core import config, db
from canopy.infra import procs


def main(argv: Sequence[str] | None = None, runner: procs.Runner | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name. Defaults to `sys.argv[1:]`.
        runner: Runs external processes. Tests may pass a fake; defaults to the real one.

    Returns:
        The process exit code.
    """
    obj = Obj(runner or procs.SubprocessRunner())
    args = list(argv) if argv is not None else sys.argv[1:]
    try:
        result = cli.main(args=args, prog_name="canopy", standalone_mode=False, obj=obj)
    except click.ClickException as e:
        e.show()
        return e.exit_code
    except click.Abort:
        click.echo("Aborted!", err=True)
        return 1
    except (config.ConfigError, db.MigrationError) as e:
        click.echo(f"canopy: {e}", err=True)
        return 2
    return result if isinstance(result, int) else 0


@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="canopy", prog_name="canopy", message="%(prog)s %(version)s")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Unattended, local agent loop driven by your issue tracker."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


for command in (
    setup.cmd_init,
    loop.cmd_loop,
    loop.cmd_tick,
    loop.cmd_status,
    loop.cmd_decisions,
    runs.cmd_dispatch,
    runs.cmd_run,
    journal.cmd_decide,
    journal.cmd_attention,
    journal.ticket_group,
):
    cli.add_command(command)
