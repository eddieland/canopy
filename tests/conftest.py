"""Shared fixtures. The fakes in tests/fakes/ are real executables; these fixtures put them on PATH."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FAKES_DIR = Path(__file__).parent / "fakes"


@pytest.fixture
def fakes_on_path(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put tests/fakes first on PATH, so `treehouse` and `agent` resolve to the fakes."""
    monkeypatch.setenv("PATH", f"{FAKES_DIR}{os.pathsep}{os.environ.get('PATH', '')}")
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
    for var in ("FAKE_AGENT_RESULT", "FAKE_AGENT_EXIT", "FAKE_AGENT_SLEEP"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("FAKE_AGENT_LOG", str(log))
    return log
