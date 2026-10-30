"""What every command shares: the object `main` passes down, refusals, opening the journal, and waiting for a tick."""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click

from canopy.core import config, context, conversation, workspace
from canopy.infra import lock
from canopy.runtime import servers

if TYPE_CHECKING:
    from collections.abc import Iterator

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


def require_workspace() -> Path:
    """Find the workspace the current directory is in.

    Returns:
        Its root.

    Raises:
        CliError: No workspace file is here or above.
    """
    root = workspace.find_root(Path.cwd())
    if root is None:
        raise CliError(f"no {config.WORKSPACE_FILE_NAME} here or above; run `canopy init` first")
    return root


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


@contextlib.contextmanager
def between_ticks(ctx: Context, doing: str, *, dispatches: bool = False) -> Iterator[None]:
    """Hold the tick lock while the block changes the pools, waiting for a running tick to end, and saying so.

    A tick leases slots and reads the pools, so what changes them by hand happens only between ticks. With
    `dispatches`, the dispatch lock is held too, so no review or task is leasing a slot it has not recorded yet.

    Yields:
        Once the locks are held, until the block ends.
    """
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(lock.hold(ctx.lock_path))
        except lock.LockBusyError:
            click.echo(f"A tick is running; {doing} starts when it ends.")
            stack.enter_context(lock.hold(ctx.lock_path, wait=True))
        if dispatches:
            stack.enter_context(lock.hold(ctx.dispatch_lock_path, wait=True))
        yield
