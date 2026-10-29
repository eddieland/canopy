"""What every command shares: the object `main` passes down, refusals, and opening the journal."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click

from canopy.core import context, conversation
from canopy.runtime import servers

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.infra import procs


class CliError(click.ClickException):
    """A refusal or failure, reported on stderr, exit 1. Misuse is a click.UsageError instead, exit 2."""


@dataclass(frozen=True)
class Obj:
    """What `main` hands every command through click's context."""

    runner: procs.Runner


def leave_the_tick() -> None:
    """Drop from this process's environment what a run must not inherit, for a detached run.

    The run must not act as the overseer of the tick that started it (D020), nor pass on to its agent a server of
    canopy's that the process tree it was started from was given (DESIGN §27): its agent gets its own, if any.
    """
    for name in (conversation.TICK_ID_ENV, *servers.VARIABLES):
        os.environ.pop(name, None)


def open_context(click_ctx: click.Context, *, migrate: bool = True, start: Path | None = None) -> Context:
    """Load config and open the journal. The connection closes when the command finishes.

    Returns:
        The context for the workspace `start` is in, the current directory by default, its journal migrated unless
        `migrate` is false.

    Raises:
        RuntimeError: The command was not run through `canopy.cli.main`, so there is no `Obj` to read.
    """
    ctx = context.open_at(start or Path.cwd(), runner_of(click_ctx), migrate=migrate)
    click_ctx.call_on_close(ctx.conn.close)
    return ctx


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
