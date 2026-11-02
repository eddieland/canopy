"""The `canopy` command line, built with click (D025). Each command group lives in its own module here.

The root group imports a command's module only when that command is looked up, so one `canopy` call loads what it runs
and not every other command's implementation. The overseer and its workers run `canopy` many times a tick, and each of
those processes pays for whatever it imports.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence
from typing import override

import click

from canopy.cli.common import Obj
from canopy.core import config, db
from canopy.infra import procs

# Each top-level command's module under canopy.cli and the attribute that holds it. A new command goes here; a test
# fails on one defined in a command module but listed nowhere.
COMMANDS: dict[str, tuple[str, str]] = {
    "init": ("setup", "cmd_init"),
    "skill": ("setup", "cmd_skill"),
    "completion": ("setup", "cmd_completion"),
    "secret": ("setup", "cmd_secret"),
    "sandbox": ("setup", "sandbox_group"),
    "loop": ("loop", "cmd_loop"),
    "daemon": ("daemon", "daemon_group"),
    "tick": ("loop", "cmd_tick"),
    "status": ("loop", "cmd_status"),
    "decisions": ("loop", "cmd_decisions"),
    "agreement": ("agreement", "cmd_agreement"),
    "spend": ("spend", "cmd_spend"),
    "agents": ("agents", "cmd_agents"),
    "personas": ("personas", "cmd_personas"),
    "persona": ("personas", "cmd_persona"),
    "models": ("models", "cmd_models"),
    "model": ("models", "cmd_model"),
    "health": ("health", "cmd_health"),
    "checklist": ("checklist", "cmd_checklist"),
    "cards": ("cards", "cmd_cards"),
    "latency": ("latency", "cmd_latency"),
    "gc": ("gc", "cmd_gc"),
    "backfill": ("backfill", "cmd_backfill"),
    "pause": ("conversation", "cmd_pause"),
    "resume": ("conversation", "cmd_resume"),
    "notice": ("conversation", "cmd_notice"),
    "start": ("conversation", "cmd_start"),
    "stop": ("conversation", "cmd_stop"),
    "reply": ("conversation", "cmd_reply"),
    "attach": ("attachments", "cmd_attach"),
    "detach": ("attachments", "cmd_detach"),
    "forget": ("conversation", "cmd_forget"),
    "grant": ("conversation", "cmd_grant"),
    "dismiss": ("conversation", "cmd_dismiss"),
    "send": ("conversation", "cmd_send"),
    "show": ("conversation", "cmd_show"),
    "plan": ("plans", "cmd_plan"),
    "archive": ("plans", "cmd_archive"),
    "memory": ("memory", "memory_group"),
    "config": ("settings", "config_group"),
    "draft": ("drafts", "draft_group"),
    "_run": ("runs", "cmd_run"),
    "task": ("tasks", "task_group"),
    "_task": ("runs", "cmd_task"),
    "workspace": ("workspace", "workspace_group"),
    "chore": ("chores", "chore_group"),
    "_chore": ("chores", "cmd_chore_process"),
    "notify": ("notify", "notify_group"),
    "review": ("reviews", "review_group"),
    "_review": ("reviews", "cmd_review_process"),
    "_mcp": ("mcp", "cmd_mcp"),
}


class LazyGroup(click.Group):
    """The root group: it lists every command in COMMANDS and imports one's module when click first looks it up.

    `--help` and shell completion look up every command, so they import them all; running one imports only its own.
    """

    @override
    def list_commands(self, ctx: click.Context) -> list[str]:
        """List the commands added directly and those in COMMANDS, sorted as click sorts them.

        Returns:
            Every command name, without importing any command's module.
        """
        return sorted({*super().list_commands(ctx), *COMMANDS})

    @override
    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Return the command named `cmd_name`, importing its module the first time.

        Returns:
            The command, or None when no command has that name.

        Raises:
            TypeError: COMMANDS names an attribute that is not a click command.
        """
        if cmd_name in COMMANDS and cmd_name not in self.commands:
            module, attr = COMMANDS[cmd_name]
            command = getattr(importlib.import_module(f"canopy.cli.{module}"), attr)
            if not isinstance(command, click.Command):
                raise TypeError(f"canopy.cli.{module}.{attr} is not a click command")
            self.add_command(command, cmd_name)
        return super().get_command(ctx, cmd_name)


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


@click.group(cls=LazyGroup, invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="canopy", prog_name="canopy", message="%(prog)s %(version)s")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Unattended, local agent loop driven by your issue tracker."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
