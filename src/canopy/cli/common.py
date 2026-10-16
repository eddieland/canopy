"""What every command shares: the object `main` passes down, refusals, opening the journal, and the running tick."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, override

import click

from canopy.core import config, conversation, db, workspace
from canopy.core.context import Context, db_path
from canopy.core.vocab import TickStatus
from canopy.infra import logs, procs, resources

if TYPE_CHECKING:
    from click.shell_completion import CompletionItem

    from canopy.core import records


class CliError(click.ClickException):
    """A refusal or failure, reported on stderr, exit 1. Misuse is a click.UsageError instead, exit 2."""


class OverseerCommand(click.Command):
    """A command only the overseer runs, inside a tick: `--help` lists it, but Tab does not offer it (DESIGN §13)."""


class Group(click.Group):
    """A command group whose shell completion offers the operator's subcommands, and leaves out the overseer's.

    A group counts as the overseer's when every subcommand in it is, so `canopy ticket` goes with `ticket set`.
    """

    @override
    def shell_complete(self, ctx: click.Context, incomplete: str) -> list[CompletionItem]:
        """Complete as click does, without the overseer's subcommands.

        Returns:
            The completions click offers, less each subcommand only the overseer runs.
        """
        return [
            item
            for item in super().shell_complete(ctx, incomplete)
            if not _overseers(self.get_command(ctx, item.value))
        ]


def _overseers(command: click.Command | None) -> bool:
    if isinstance(command, click.Group):
        return bool(command.commands) and all(_overseers(sub) for sub in command.commands.values())
    return isinstance(command, OverseerCommand)


@dataclass(frozen=True)
class Obj:
    """What `main` hands every command through click's context."""

    runner: procs.Runner


def open_context(click_ctx: click.Context, *, migrate: bool = True) -> Context:
    """Load config and open the journal. The connection closes when the command finishes.

    Returns:
        The context for the workspace the current directory is in, its journal migrated unless `migrate` is false.

    Raises:
        RuntimeError: The command was not run through `canopy.cli.main`, so there is no `Obj` to read.
    """
    runner = runner_of(click_ctx)
    ws = workspace.find(Path.cwd())
    cfg = config.load(ws.root, runner=runner)
    # Logs and overseer output live here; they are for the operator only (TRUST_MODEL T2).
    workspace.ensure_state_dir(ws.state_dir)
    logs.configure(ws.state_dir)
    conn = db.connect(db_path(ws))
    click_ctx.call_on_close(conn.close)
    if migrate:
        # The tick migrates under its lock; everything else migrates on open, which is a no-op inside a tick.
        db.migrate(conn, resources.migrations_dir())
    return Context(config=cfg, conn=conn, runner=runner, ws=ws)


def runner_of(click_ctx: click.Context) -> procs.Runner:
    """Return the runner `main` handed the command, for one that needs no workspace.

    Returns:
        The runner every external process goes through.

    Raises:
        RuntimeError: The command was not run through `canopy.cli.main`, so there is no `Obj` to read.
    """
    obj = click_ctx.find_object(Obj)
    if obj is None:
        raise RuntimeError("canopy commands run through canopy.cli.main")
    return obj.runner


def optional_tick(ctx: Context) -> records.Tick | None:
    """Return the tick this command runs inside, named by CANOPY_TICK_ID, or None outside a tick.

    Raises:
        CliError: CANOPY_TICK_ID is set but does not name a running tick.
    """
    raw = os.environ.get(conversation.TICK_ID_ENV)
    if not raw:
        return None
    row = db.get_tick(ctx.conn, int(raw)) if raw.isdigit() else None
    if row is None or row.status != TickStatus.RUNNING:
        raise CliError(f"{conversation.TICK_ID_ENV}={raw} does not name a running tick")
    return row


def require_tick(ctx: Context) -> records.Tick:
    """Return the tick this command runs inside; refuse outside a tick.

    Raises:
        CliError: CANOPY_TICK_ID is not set, or does not name a running tick.
    """
    row = optional_tick(ctx)
    if row is None:
        raise CliError(f"no tick is running ({conversation.TICK_ID_ENV} is not set); this command runs inside a tick")
    return row
