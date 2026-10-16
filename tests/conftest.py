"""Shared fixtures. The fakes in tests/fakes/ are real executables; these fixtures put them on PATH."""

from __future__ import annotations

import contextlib
import json
import os
import sys
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.core import db
from canopy.infra import resources
from canopy.infra.procs import SubprocessRunner

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator, Mapping, Sequence

FAKES_DIR = Path(__file__).parent / "fakes"
# Where this interpreter's scripts live, `canopy` among them. A fake agent runs `canopy` the way an overseer does.
SCRIPTS_DIR = Path(sys.executable).parent
# The prefixes tests/fakes/agent records in its log's `env`. Keep in sync with it.
RECORDED_ENV_PREFIXES = ("CANOPY_", "OPENCODE_")

# Commits made under test have a fixed author, and git reads no config of the operator's or the machine's.
HERMETIC_GIT = {
    "GIT_AUTHOR_NAME": "canopy test",
    "GIT_COMMITTER_NAME": "canopy test",
    "GIT_AUTHOR_EMAIL": "test@example.test",
    "GIT_COMMITTER_EMAIL": "test@example.test",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


@pytest.fixture(autouse=True)
def hermetic_agent_env() -> Iterator[None]:
    """Drop inherited CANOPY_* and OPENCODE_* variables, so a test's environment is only what it sets, and restore the
    whole environment when the test ends.

    Workers run this suite inside the agent runtime, which exports its own (OpenCode sets OPENCODE_PID). The fake
    agent records these prefixes and tests assert on them exactly, so an inherited one would fail them.
    """
    with mock.patch.dict(os.environ):
        for name in [k for k in os.environ if k.startswith(RECORDED_ENV_PREFIXES)]:
            del os.environ[name]
        yield


@pytest.fixture
def fakes_on_path() -> Iterator[Path]:
    """Put tests/fakes first on PATH, so `treehouse` and `agent` resolve to the fakes, and this environment's `canopy`
    right after it."""
    path = os.pathsep.join([str(FAKES_DIR), str(SCRIPTS_DIR), os.environ.get("PATH", "")])
    with mock.patch.dict(os.environ, {"PATH": path}):
        yield FAKES_DIR


@pytest.fixture
def treehouse_state(fakes_on_path: Path, tmp_path: Path) -> Iterator[Path]:
    """Fake treehouse on PATH with an empty pool. Yields its state file; write it to seed the pool, read it to assert.

    The file does not exist until the first `treehouse` call. See tests/fakes/treehouse for its keys.
    """
    state = tmp_path / "treehouse.json"
    with mock.patch.dict(os.environ, {"FAKE_TREEHOUSE_STATE": str(state)}):
        os.environ.pop("TREEHOUSE_LEASE_HOLDER", None)
        yield state


@pytest.fixture
def agent_log(fakes_on_path: Path, tmp_path: Path) -> Iterator[Path]:
    """Fake agent on PATH with default behavior. Yields the file each run appends its argv and cwd to.

    Tests change behavior with `mock.patch.dict(os.environ, ...)` on the FAKE_AGENT_* variables, or FAKE_OVERSEER_*
    and FAKE_WORKER_* for one role only; see tests/fakes/agent.
    """
    log = tmp_path / "agent.jsonl"
    with mock.patch.dict(os.environ, {"FAKE_AGENT_LOG": str(log)}):
        for role in ("AGENT", "OVERSEER", "WORKER", "WORKER_PRIVATE", "SPLITTER", "CHORE", "REVIEWER"):
            for name in ("RESULT", "EXIT", "SLEEP", "COMMANDS"):
                os.environ.pop(f"FAKE_{role}_{name}", None)
        yield log


@dataclass
class Journals:
    """The journal connections a test opens, each closed when the test ends.

    A connection left to the garbage collector raises a ResourceWarning, which fails the test (pyproject.toml).
    """

    _opened: list[sqlite3.Connection] = field(default_factory=list)

    def open(self, path: Path, *, migrate: bool = True) -> sqlite3.Connection:
        """Open the journal at `path`, applying the shipped migrations unless `migrate` is False."""
        return self.open_through(path, resources.migrations_dir() if migrate else None)

    def open_through(self, path: Path, migrations: Path | None) -> sqlite3.Connection:
        """Open the journal at `path` and apply the migrations in `migrations`, if any."""
        conn = db.connect(path)
        self._opened.append(conn)
        if migrations is not None:
            db.migrate(conn, migrations)
        return conn

    def close(self) -> None:
        for conn in self._opened:
            conn.close()
        self._opened.clear()


@pytest.fixture
def journals() -> Iterator[Journals]:
    """Open journals through this, and they close when the test ends."""
    with closing(Journals()) as opened:
        yield opened


@dataclass(frozen=True)
class CanopyEnv:
    """A workspace of one repository, `repo`, and an operator, all in tmp_path. The process cwd is the workspace root.

    `repo` is the repository's primary clone, `repos/repo`: just a `.git` directory. `shared_file` is the workspace
    file, whose `[tracker]` table comes last so that a test can append tracker keys to it; the user file ends with an
    empty `[paths]` table, for paths keys.
    """

    root: Path
    repo: Path
    home: Path
    user_file: Path
    shared_file: Path
    journals: Journals

    @property
    def state_dir(self) -> Path:
        return self.root / ".canopy"

    def journal(self, *, migrate: bool = True) -> sqlite3.Connection:
        """Open this workspace's journal, closed when the test ends."""
        return self.journals.open(self.state_dir / db.DB_FILE_NAME, migrate=migrate)

    def write_user(self, text: str) -> None:
        self.user_file.parent.mkdir(parents=True, exist_ok=True)
        self.user_file.write_text(text)

    def write_shared(self, text: str) -> None:
        self.shared_file.write_text(text)


REPO_NAME = "repo"
SHARED_TOML = f"""\
[workspace]
name = "acme"

[repos.{REPO_NAME}]
url = "https://example.test/acme/{REPO_NAME}.git"
summary = "The only repository."

[tracker]
provider = "jira"
query = "project = PROJ"
"""


def user_toml() -> str:
    return """\
[tracker]
labels = ["agent-ready-tester"]

[runtime]
overseer_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-overseer {prompt}'
worker_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-worker {prompt}'
private_worker_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-worker-private {prompt}'
split_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-splitter {prompt}'

[paths]
"""


@pytest.fixture
def canopy_env(tmp_path: Path, journals: Journals) -> Iterator[CanopyEnv]:
    """A workspace of one repository with its workspace file, and a user config whose runtime commands run the fake
    agent. HOME, XDG_CONFIG_HOME, and XDG_DATA_HOME point into tmp_path too, so nothing reads or writes the real
    operator's files.
    CANOPY_TICK_ID is cleared."""
    home = tmp_path / "home"
    root = tmp_path / "ws"
    repo = root / "repos" / REPO_NAME
    (repo / ".git").mkdir(parents=True)
    home.mkdir()
    env = CanopyEnv(
        root=root,
        repo=repo,
        home=home,
        user_file=home / ".config" / "canopy" / "config.toml",
        shared_file=root / "canopy-workspace.toml",
        journals=journals,
    )
    env.write_shared(SHARED_TOML)
    env.write_user(user_toml())
    # As canopy creates it, so a journal a test opens first is in a directory canopy accepts as the operator's own.
    env.state_dir.mkdir(mode=0o700)
    variables = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "USER": "tester",
    }
    with mock.patch.dict(os.environ, variables), contextlib.chdir(root):
        os.environ.pop("CANOPY_TICK_ID", None)
        yield env


def pool_state(repo: Path, slots: Sequence[Mapping[str, object]], max_trees: int | None = None) -> str:
    """The fake treehouse's state with `slots` as the pool of the repository whose primary clone is `repo`."""
    pool: dict[str, object] = {"slots": list(slots)}
    if max_trees is not None:
        pool["max_trees"] = max_trees
    return json.dumps({"pools": {str(repo): pool}})


def git(*args: str, cwd: Path) -> str:
    """Run git through the procs boundary (D015) and return its stripped stdout; fail the test if it fails."""
    result = SubprocessRunner().run(["git", *args], cwd=cwd)
    assert result.ok, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout.strip()


@dataclass(frozen=True)
class GitPool:
    """A bare `origin` with one commit on `main`, and treehouse slots that are clones of it."""

    origin: Path
    slots: tuple[Path, ...]

    def remote_head(self, branch: str) -> str | None:
        """The commit `branch` points to on origin, or None."""
        out = git("for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}", cwd=self.origin)
        return out or None

    def reject_pushes(self) -> None:
        """Make origin refuse every push, the way a protected branch or a lost network does."""
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'push refused by test hook' >&2\nexit 1\n")
        hook.chmod(0o755)


@pytest.fixture
def git_pool(canopy_env: CanopyEnv, treehouse_state: Path, tmp_path: Path) -> Iterator[GitPool]:
    """Real git behind the fake treehouse: `treehouse get` leases one of two clones of a bare origin, as `repo`'s pool.

    Real treehouse slots are worktrees of one repository; clones behave the same for what canopy runs in a slot.
    """
    with mock.patch.dict(os.environ, HERMETIC_GIT):
        yield seed_git_pool(canopy_env, treehouse_state, tmp_path)


def seed_git_pool(canopy_env: CanopyEnv, treehouse_state: Path, tmp_path: Path) -> GitPool:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git("init", "--quiet", "--bare", "--initial-branch=main", cwd=origin)
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "--quiet", "--initial-branch=main", cwd=seed)
    git("commit", "--quiet", "--allow-empty", "-m", "initial", cwd=seed)
    git("push", "--quiet", str(origin), "main", cwd=seed)

    slots: list[Path] = []
    for name in ("1", "2"):
        slot = tmp_path / "pool" / name / "repo"
        slot.parent.mkdir(parents=True)
        git("clone", "--quiet", str(origin), str(slot), cwd=tmp_path)
        git("checkout", "--quiet", "--detach", cwd=slot)
        slots.append(slot)
    pool = [{"name": str(i), "path": str(p), "status": "available"} for i, p in enumerate(slots, 1)]
    treehouse_state.write_text(pool_state(canopy_env.repo, pool, max_trees=len(slots)))
    return GitPool(origin, tuple(slots))
