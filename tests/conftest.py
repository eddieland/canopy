"""Shared fixtures. The fakes in tests/fakes/ are real executables; these fixtures put them on PATH."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from canopy.infra.procs import SubprocessRunner

FAKES_DIR = Path(__file__).parent / "fakes"
# Where this interpreter's scripts live, `canopy` among them. A fake agent runs `canopy` the way an overseer does.
SCRIPTS_DIR = Path(sys.executable).parent
# The prefixes tests/fakes/agent records in its log's `env`. Keep in sync with it.
RECORDED_ENV_PREFIXES = ("CANOPY_", "OPENCODE_")


@pytest.fixture(autouse=True)
def hermetic_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop inherited CANOPY_* and OPENCODE_* variables, so a test's environment is only what it sets.

    Workers run this suite inside the agent runtime, which exports its own (OpenCode sets OPENCODE_PID). The fake
    agent records these prefixes and tests assert on them exactly, so an inherited one would fail them.
    """
    for name in [k for k in os.environ if k.startswith(RECORDED_ENV_PREFIXES)]:
        monkeypatch.delenv(name)


@pytest.fixture
def fakes_on_path(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put tests/fakes first on PATH, so `treehouse` and `agent` resolve to the fakes, and this environment's `canopy`
    right after it."""
    monkeypatch.setenv("PATH", os.pathsep.join([str(FAKES_DIR), str(SCRIPTS_DIR), os.environ.get("PATH", "")]))
    return FAKES_DIR


@pytest.fixture
def treehouse_state(fakes_on_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake treehouse on PATH with an empty pool. Returns its state file; write it to seed the pool, read it to assert.

    The file does not exist until the first `treehouse` call. See tests/fakes/treehouse for its keys.
    """
    state = tmp_path / "treehouse.json"
    monkeypatch.setenv("FAKE_TREEHOUSE_STATE", str(state))
    monkeypatch.delenv("TREEHOUSE_LEASE_HOLDER", raising=False)
    return state


@pytest.fixture
def agent_log(fakes_on_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake agent on PATH with default behavior. Returns the file each run appends its argv and cwd to.

    Tests change behavior with monkeypatch.setenv on the FAKE_AGENT_* variables, or FAKE_OVERSEER_* and FAKE_WORKER_*
    for one role only; see tests/fakes/agent.
    """
    log = tmp_path / "agent.jsonl"
    for role in ("AGENT", "OVERSEER", "WORKER", "SPLITTER"):
        for name in ("RESULT", "EXIT", "SLEEP", "COMMANDS"):
            monkeypatch.delenv(f"FAKE_{role}_{name}", raising=False)
    monkeypatch.setenv("FAKE_AGENT_LOG", str(log))
    return log


@dataclass(frozen=True)
class CanopyEnv:
    """A repository and an operator, both in tmp_path. The process cwd is the repository."""

    repo: Path
    home: Path
    user_file: Path
    repo_file: Path
    state_dir: Path

    def write_user(self, text: str) -> None:
        self.user_file.parent.mkdir(parents=True, exist_ok=True)
        self.user_file.write_text(text)

    def write_repo(self, text: str) -> None:
        self.repo_file.write_text(text)


REPO_TOML = """\
[tracker]
provider = "jira"
query = "project = PROJ"
"""


def user_toml(state_dir: Path) -> str:
    return f"""\
[tracker]
labels = ["agent-ready-tester"]

[runtime]
overseer_cmd = 'env OPENCODE_CONFIG_DIR={{definitions_dir}} agent run --agent canopy-overseer {{prompt}}'
worker_cmd = 'env OPENCODE_CONFIG_DIR={{definitions_dir}} agent run --agent canopy-worker {{prompt}}'
split_cmd = 'env OPENCODE_CONFIG_DIR={{definitions_dir}} agent run --agent canopy-splitter {{prompt}}'

[paths]
state_dir = {json.dumps(str(state_dir))}
"""


@pytest.fixture
def canopy_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CanopyEnv:
    """A git repository (just a `.git` directory) with a canopy.toml, and a user config whose runtime commands run the
    fake agent and whose state dir is in tmp_path. HOME and XDG_CONFIG_HOME point into tmp_path too, so nothing reads
    or writes the real operator's files. CANOPY_TICK_ID is cleared."""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.delenv("CANOPY_TICK_ID", raising=False)
    monkeypatch.chdir(repo)
    env = CanopyEnv(
        repo=repo,
        home=home,
        user_file=home / ".config" / "canopy" / "config.toml",
        repo_file=repo / "canopy.toml",
        state_dir=tmp_path / "state",
    )
    env.write_repo(REPO_TOML)
    env.write_user(user_toml(env.state_dir))
    return env


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
def git_pool(treehouse_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GitPool:
    """Real git behind the fake treehouse: `treehouse get` leases one of two clones of a bare origin.

    Real treehouse slots are worktrees of one repository; clones behave the same for what canopy runs in a slot.
    """
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "canopy test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "test@example.test")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

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
    treehouse_state.write_text(json.dumps({"max_trees": len(slots), "slots": pool}))
    return GitPool(origin, tuple(slots))
