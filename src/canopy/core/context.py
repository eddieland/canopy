"""What every command needs, passed explicitly instead of held in globals."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.infra import lock, procs

if TYPE_CHECKING:
    from canopy.core.config import Config


@dataclass(frozen=True)
class Context:
    """Config, repository root, journal connection, and process runner for one command."""

    config: Config
    repo_root: Path
    conn: sqlite3.Connection
    runner: procs.Runner

    @property
    def state_dir(self) -> Path:
        """Where the journal, lock, and logs live."""
        return self.config.paths.state_dir

    @property
    def lock_path(self) -> Path:
        """The tick lock file."""
        return self.state_dir / lock.LOCK_FILE_NAME

    @property
    def repo(self) -> str:
        """How the journal's `tickets.repo` names this repository."""
        return str(self.repo_root)


def db_path(config: Config) -> Path:
    """Return the journal's path for `config`."""
    return config.paths.state_dir / db.DB_FILE_NAME
