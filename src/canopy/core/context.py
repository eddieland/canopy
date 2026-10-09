"""What every command needs, passed explicitly instead of held in globals."""

from __future__ import annotations

import dataclasses
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import db, treehouse
from canopy.core.workspace import Workspace, of_one
from canopy.infra import lock, procs

# Held by every command that may start a detached run, so two cannot both pass a capacity check (DESIGN §8, §19).
DISPATCH_LOCK = "dispatch.lock"

if TYPE_CHECKING:
    from canopy.core.config import Config


@dataclass(frozen=True)
class Context:
    """Config, workspace, journal connection, and process runner for one command.

    `repo_root` is the workspace root: the directory the overseer runs in, and the repository itself in a workspace of
    one. `ws` is the workspace; left out, it is the workspace of one at `repo_root`.
    """

    config: Config
    repo_root: Path
    conn: sqlite3.Connection
    runner: procs.Runner
    ws: Workspace | None = None

    @property
    def workspace(self) -> Workspace:
        """The workspace this command runs in."""
        return self.ws if self.ws is not None else of_one(self.repo_root)

    def pool(self, repo: str | None) -> treehouse.Pool:
        """Where treehouse runs for repository `repo`'s pool, with the size `capacity` declares for it.

        Only a workspace's pools have a declared size: a workspace of one's pool is treehouse's own, which may be the
        operator's interactive pool as well (DESIGN §18). Every pool gets the operator's own `.worktreeinclude`, if
        `paths.worktree_include` names one (DESIGN §9).
        """
        pool = dataclasses.replace(self.workspace.pool(repo), include_file=self.config.paths.worktree_include)
        if self.workspace.single or repo is None:
            return pool
        return dataclasses.replace(pool, slots=self.config.capacity.slots_for(repo))

    @property
    def state_dir(self) -> Path:
        """Where the journal, lock, and logs live."""
        return self.config.paths.state_dir

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


def db_path(config: Config) -> Path:
    """Return the journal's path for `config`."""
    return config.paths.state_dir / db.DB_FILE_NAME
