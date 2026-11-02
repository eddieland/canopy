"""What every command needs, passed explicitly instead of held in globals."""

from __future__ import annotations

import dataclasses
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from canopy.core import chore_view, config, db, pools, treehouse, workspace
from canopy.core.pool import CanopyPool
from canopy.core.vocab import PoolKind
from canopy.core.workspace import REPOS_DIR
from canopy.infra import lock, logs, procs, resources, tracing

# Held by every command that may start a detached run, so two cannot both pass a capacity check (DESIGN §8, §19).
DISPATCH_LOCK = "dispatch.lock"

if TYPE_CHECKING:
    from canopy.core.config import Config
    from canopy.core.workspace import Workspace


def open_at(start: Path, runner: procs.Runner, *, migrate: bool = True) -> Context:
    """Load the config of the workspace `start` is in and open its journal, as every command and tool call does.

    The caller closes the context's connection.

    Returns:
        The context, its journal migrated unless `migrate` is false.
    """
    ws = workspace.find(start)
    cfg = config.load(ws.root, runner=runner)
    # Logs and overseer output live here; they are for the operator only (TRUST_MODEL T2).
    workspace.ensure_state_dir(ws.state_dir)
    logs.configure(ws.state_dir)
    tracing.configure(ws.state_dir, cfg.telemetry.traces)
    conn = db.connect(db_path(ws))
    if migrate:
        # The tick migrates under its lock; everything else migrates on open, which is a no-op inside a tick.
        try:
            db.migrate(conn, resources.migrations_dir())
        except BaseException:
            conn.close()
            raise
    return Context(config=cfg, conn=conn, runner=runner, ws=ws)


@dataclass(frozen=True)
class Context:
    """Config, workspace, journal connection, and process runner for one command.

    `ws` is the workspace the command runs in. `finding_starts` remembers when chores' findings started, from one
    read of them to the next: the web UI's server hands every Context it opens its own (DESIGN §22).
    """

    config: Config
    conn: sqlite3.Connection
    runner: procs.Runner
    ws: Workspace
    finding_starts: chore_view.FindingStarts = field(
        default_factory=chore_view.FindingStarts,
        compare=False,
        repr=False,
    )

    @property
    def workspace(self) -> Workspace:
        """The workspace this command runs in."""
        return self.ws

    @property
    def repo_root(self) -> Path:
        """The workspace root: the directory the overseer runs in."""
        return self.ws.root

    def pool(self, repo: str) -> pools.Pool:
        """Repository `repo`'s pool, made by the backend `pools.backend` names (DESIGN §18).

        Returns:
            The pool, sized from `capacity` and seeding from the operator's own `.worktreeinclude`, if
            `paths.worktree_include` names one (DESIGN §9).
        """
        return self.pool_of(self.config.pools.backend, repo)

    def pool_of(self, kind: PoolKind, repo: str | None) -> pools.Pool:
        """Repository `repo`'s pool as backend `kind` makes it: the pool a lease it made goes back to.

        A repository whose clone is gone still has a pool that can return a slot: treehouse finds it from the slot's
        own path, and canopy's from its row.

        Returns:
            The pool, sized and seeding as `pool` says.
        """
        slots = self.config.capacity.slots_for(repo) if repo is not None else None
        include = self.config.paths.worktree_include
        match kind:
            case PoolKind.TREEHOUSE:
                where = dataclasses.replace(self.workspace.treehouse_pool(repo), slots=slots, include_file=include)
                return treehouse.TreehousePool(self.runner, where)
            case PoolKind.CANOPY:
                return self.canopy_pool(repo or "")
            case _:
                assert_never(kind)

    def canopy_pool(self, repo: str) -> CanopyPool:
        """Repository `repo`'s pool as canopy's own pool makes it, whatever `pools.backend` names (DESIGN §18).

        Returns:
            The pool, sized and seeding as `pool` says. A repository the map does not list has its clone where sync
            would have made it, `repos/<name>`.
        """
        found = self.workspace.repo(repo)
        clone = found.path if found is not None else self.workspace.root / REPOS_DIR / repo
        return CanopyPool(
            self.runner,
            self.conn,
            repo,
            self.workspace.root,
            clone,
            slots=self.config.capacity.slots_for(repo),
            include_file=self.config.paths.worktree_include,
        )

    @property
    def state_dir(self) -> Path:
        """Where the journal, lock, and logs live."""
        return self.ws.state_dir

    @property
    def lock_path(self) -> Path:
        """The tick lock file."""
        return self.state_dir / lock.LOCK_FILE_NAME

    @property
    def dispatch_lock_path(self) -> Path:
        """The lock that serializes dispatches and chore runs."""
        return self.state_dir / DISPATCH_LOCK

    @property
    def repo(self) -> str:
        """How the journal's `tickets.repo` names this workspace: its root."""
        return str(self.repo_root)


def db_path(ws: Workspace) -> Path:
    """Return the journal's path in workspace `ws`."""
    return ws.state_dir / db.DB_FILE_NAME
