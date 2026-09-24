"""Shared fixtures. The fakes in tests/fakes/ are real executables; these fixtures put them on PATH."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

FAKES_DIR = Path(__file__).parent / "fakes"
# Where this interpreter's scripts live, `canopy` among them. A fake agent runs `canopy` the way an overseer does.
SCRIPTS_DIR = Path(sys.executable).parent


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

    Tests change behavior with monkeypatch.setenv on the FAKE_AGENT_* variables; see tests/fakes/agent.
    """
    log = tmp_path / "agent.jsonl"
    for var in ("FAKE_AGENT_RESULT", "FAKE_AGENT_EXIT", "FAKE_AGENT_SLEEP", "FAKE_AGENT_COMMANDS"):
        monkeypatch.delenv(var, raising=False)
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
overseer_cmd = 'agent run --agent canopy-overseer {{prompt}}'
worker_cmd = 'agent run --agent canopy-worker {{prompt}}'

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
