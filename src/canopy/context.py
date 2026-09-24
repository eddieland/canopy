"""What every command needs, passed explicitly instead of held in globals."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from canopy import db, lock, procs
from canopy.config import Config


@dataclass(frozen=True)
class Context:
    config: Config
    repo_root: Path
    conn: sqlite3.Connection
    runner: procs.Runner

    @property
    def state_dir(self) -> Path:
        return self.config.paths.state_dir

    @property
    def lock_path(self) -> Path:
        return self.state_dir / lock.LOCK_FILE_NAME

    @property
    def repo(self) -> str:
        """How the journal's `tickets.repo` names this repository."""
        return str(self.repo_root)


def db_path(config: Config) -> Path:
    return config.paths.state_dir / db.DB_FILE_NAME
