"""`canopy agents`: what each of canopy's agents is offered, asked of the fake `opencode` started as a run starts it."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.runtime import definitions

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import CanopyEnv

#: What the fake `opencode` has: a GitHub server outside code mode, as one an agent needs is set, a skill, and a rule
#: that denies github and the shell to the chore, as an operator's config would.
STATE = {
    "config": {"mcp": {"github": {"type": "remote", "url": "https://x.test/", "codemode": False}}},
    "skills": ["tracker-jira"],
    "agents": {"canopy-chore": [["github_*", "*", "deny"], ["bash", "*", "deny"]]},
}


@pytest.fixture
def opencode(opencode_state: Path) -> Path:
    """The fake `opencode`, first on PATH, with `STATE`."""
    opencode_state.write_text(json.dumps(STATE))
    return opencode_state


@pytest.mark.usefixtures("opencode")
def test_canopy_agents_says_what_each_agent_is_offered(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["agents", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert (found["servers"], found["skills"], found["error"]) == (["github"], ["tracker-jira"], None)
    by_agent = {a["agent"]: a for a in found["agents"]}
    # Every agent canopy ships, asked with canopy's definitions snapshot as OpenCode's config directory.
    assert sorted(by_agent) == definitions.agent_names()
    assert by_agent["canopy-chore"]["servers"] == [{"server": "github", "reach": "none", "exceptions": []}]
    assert by_agent["canopy-worker"]["servers"] == [{"server": "github", "reach": "all", "exceptions": []}]
    assert main(["agents"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("MCP servers: github.\nSkills: tracker-jira.\n")
    assert "\ncanopy-chore\n  github: none\n  skills: tracker-jira\n  built-in tools: " in out
    assert "shell" in by_agent["canopy-worker"]["tools"]
    assert "shell" not in by_agent["canopy-chore"]["tools"]


@pytest.mark.usefixtures("opencode")
def test_canopy_agents_shows_the_commands_config_allows_an_agent(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["agents", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["allow_bash"] == {}
    allows = ["jira issue list *", "jira issue view *"]
    canopy_env.configure(canopy_env.user_file, {"runtime": {"allow_bash": {"overseer": allows}}})
    assert main(["agents"]) == 0
    out = capsys.readouterr().out
    # The overseer's block ends with them, after what the runtime offers it; no other agent's names any.
    overseer = out.split("\ncanopy-overseer\n", 1)[1].split("\n\n", 1)[0]
    assert overseer.endswith("\n  bash allowed by runtime.allow_bash: jira issue list *; jira issue view *")
    assert out.count("bash allowed") == 1
    assert main(["agents", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["allow_bash"] == {"canopy-overseer": allows}


def test_canopy_agents_fails_when_opencode_cannot_say(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch.dict(os.environ, {"PATH": str(tmp_path / "nothing")}):
        assert main(["agents"]) == 1
    assert capsys.readouterr().out == "The runtime could not say what it offers: opencode is not on PATH\n"
