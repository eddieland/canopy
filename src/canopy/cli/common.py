"""What every command shares: the object `main` passes down, refusals, opening the journal, and the running tick."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import click

from canopy.core import config, db, workspace
from canopy.core.context import Context, db_path
from canopy.infra import logs, procs, resources
from canopy.loop import tick


class CliError(click.ClickException):
    """A refusal or failure, reported on stderr, exit 1. Misuse is a click.UsageError instead, exit 2."""


@dataclass(frozen=True)
class Obj:
    """What `main` hands every command through click's context."""

    runner: procs.Runner


def open_context(click_ctx: click.Context, *, migrate: bool = True) -> Context:
    """Load config and open the journal. The connection closes when the command finishes."""
    obj = click_ctx.find_object(Obj)
    if obj is None:
        raise RuntimeError("canopy commands run through canopy.cli.main")
    ws = workspace.find(Path.cwd())
    cfg = config.load(ws.root)
    # Logs and overseer output live here; they are for the operator only (TRUST_MODEL T2).
    workspace.ensure_state_dir(ws, cfg.paths.state_dir)
    logs.configure(cfg.paths.state_dir)
    conn = db.connect(db_path(cfg))
    click_ctx.call_on_close(conn.close)
    if migrate:
        # The tick migrates under its lock; everything else migrates on open, which is a no-op inside a tick.
        db.migrate(conn, resources.migrations_dir())
    return Context(config=cfg, repo_root=ws.root, conn=conn, runner=obj.runner, ws=ws)


def optional_tick(ctx: Context) -> sqlite3.Row | None:
    """Return the tick this command runs inside, named by CANOPY_TICK_ID, or None outside a tick."""
    raw = os.environ.get(tick.TICK_ID_ENV)
    if not raw:
        return None
    row = db.get_tick(ctx.conn, int(raw)) if raw.isdigit() else None
    if row is None or row["status"] != "running":
        raise CliError(f"{tick.TICK_ID_ENV}={raw} does not name a running tick")
    return row


def require_tick(ctx: Context) -> sqlite3.Row:
    """Return the tick this command runs inside; refuse outside a tick."""
    row = optional_tick(ctx)
    if row is None:
        raise CliError(f"no tick is running ({tick.TICK_ID_ENV} is not set); this command runs inside a tick")
    return row
