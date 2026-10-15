"""Fixtures for tests of workspaces of several repositories (DESIGN §18), and a pool of worktrees."""

import contextlib
import json
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import config, db
from tests.conftest import HERMETIC_GIT, CanopyEnv, GitPool, Journals, git, pool_state


def map_text(*repos: tuple[str, str], extra: str = "") -> str:
    tables = "".join(f'\n[repos.{name}]\nurl = "{url}"\nsummary = "The {name} repository."\n' for name, url in repos)
    return f"""\
[workspace]
name = "acme"
{tables}
[tracker]
provider = "github"
query = "is:issue is:open"
{extra}"""


@dataclass(frozen=True)
class Ws:
    """A workspace of two repositories, `api` and `web`, each cloned from a bare origin under tmp_path."""

    root: Path
    origins: dict[str, Path]
    state_dir: Path
    journals: Journals

    def journal(self) -> sqlite3.Connection:
        """Open this workspace's journal, closed when the test ends."""
        self.state_dir.mkdir(mode=0o700, exist_ok=True)  # as canopy creates it; anything wider is refused
        return self.journals.open(self.state_dir / db.DB_FILE_NAME)

    def clone(self, name: str) -> Path:
        return self.root / "repos" / name

    def remote_head(self, name: str, branch: str) -> str | None:
        out = git("for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}", cwd=self.origins[name])
        return out or None


def bare_origin(path: Path, tmp_path: Path) -> Path:
    path.mkdir(parents=True)
    git("init", "--quiet", "--bare", "--initial-branch=main", cwd=path)
    seed = tmp_path / f"seed-{path.stem}"
    seed.mkdir()
    git("init", "--quiet", "--initial-branch=main", cwd=seed)
    git("commit", "--quiet", "--allow-empty", "-m", f"initial {path.stem}", cwd=seed)
    git("push", "--quiet", str(path), "main", cwd=seed)
    return path


@pytest.fixture
def ws(canopy_env: CanopyEnv, treehouse_state: Path, tmp_path: Path) -> Iterator[Ws]:
    with mock.patch.dict(os.environ, HERMETIC_GIT):
        root = tmp_path / "acme"
        root.mkdir()
        origins = {name: bare_origin(tmp_path / "origins" / f"{name}.git", tmp_path) for name in ("api", "web")}
        for name, origin in origins.items():
            git("clone", "--quiet", str(origin), str(root / "repos" / name), cwd=tmp_path)
        (root / config.WORKSPACE_FILE_NAME).write_text(map_text(*((n, str(o)) for n, o in origins.items())))
        with contextlib.chdir(root):
            yield Ws(root, origins, root / ".canopy", canopy_env.journals)


def seed_pools(ws: Ws, treehouse_state: Path) -> None:
    """Give each repository's pool one slot, a clone of its origin, where canopy's pinned layout puts it."""
    pools: dict[str, object] = {}
    for name, origin in ws.origins.items():
        slot = ws.root / ".treehouse" / f"{name}-fake" / "1" / name
        slot.parent.mkdir(parents=True)
        git("clone", "--quiet", str(origin), str(slot), cwd=ws.root)
        git("checkout", "--quiet", "--detach", cwd=slot)
        pools[str(ws.clone(name))] = {"slots": [{"name": "1", "path": str(slot), "status": "available"}]}
    treehouse_state.write_text(json.dumps({"pools": pools}))


def th(treehouse_state: Path) -> dict[str, list[object]]:
    state: dict[str, list[object]] = json.loads(treehouse_state.read_text())
    return state


@pytest.fixture
def worktree_pool(
    canopy_env: CanopyEnv, git_pool: GitPool, treehouse_state: Path, tmp_path: Path
) -> tuple[Path, list[Path]]:
    """The primary clone and two worktree slots of it, which the fake treehouse leases instead of `git_pool`'s."""
    primary = tmp_path / "primary"
    git("clone", "--quiet", str(git_pool.origin), str(primary), cwd=tmp_path)
    slots = [tmp_path / "wpool" / name / "repo" for name in ("1", "2")]
    for slot in slots:
        git("worktree", "add", "--quiet", "--detach", str(slot), cwd=primary)
    state = [{"name": str(i), "path": str(p), "status": "available"} for i, p in enumerate(slots, 1)]
    treehouse_state.write_text(pool_state(canopy_env.repo, state, max_trees=len(slots)))
    return primary, slots
