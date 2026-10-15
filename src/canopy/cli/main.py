"""The `canopy` command line, built with click (D025). Each command group lives in its own module here."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import click

from canopy.cli import chores, conversation, journal, loop, notify, reviews, runs, setup, spend, workspace
from canopy.cli.common import Group, Obj
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
    except click.exceptions.NoArgsIsHelpError as e:
        # A group named without a command prints its help, as a bare `canopy` does: asking is not misuse.
        click.echo(e.ctx.get_help())
        return 0
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


@click.group(cls=Group, invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="canopy", prog_name="canopy", message="%(prog)s %(version)s")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Unattended, local agent loop driven by your issue tracker."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


for command in (
    setup.cmd_init,
    setup.cmd_skill,
    setup.cmd_completion,
    setup.cmd_secret,
    setup.sandbox_group,
    loop.cmd_loop,
    loop.cmd_tick,
    loop.cmd_status,
    loop.cmd_decisions,
    spend.cmd_spend,
    conversation.cmd_pause,
    conversation.cmd_resume,
    conversation.cmd_notice,
    conversation.cmd_start,
    conversation.cmd_stop,
    conversation.cmd_reply,
    conversation.cmd_forget,
    conversation.cmd_grant,
    conversation.cmd_dismiss,
    conversation.cmd_send,
    conversation.cmd_show,
    runs.cmd_dispatch,
    runs.cmd_run,
    journal.cmd_decide,
    journal.cmd_attention,
    journal.cmd_mirror,
    journal.ticket_group,
    workspace.workspace_group,
    chores.chore_group,
    chores.cmd_chore_process,
    notify.notify_group,
    reviews.review_group,
    reviews.cmd_review_process,
):
    cli.add_command(command)
