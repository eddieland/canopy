"""`canopy agents`: what each of canopy's agents is offered, asked of a fake `opencode` started as a run starts it."""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.runtime import definitions
from tests.conftest import executable

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from tests.conftest import CanopyEnv

#: A fake `opencode` that plays `debug config`, `skill`, and `agent NAME` as 1.19.3 prints them. It answers only when
#: OpenCode's config directory holds canopy's agent, and denies github to the chore, as an operator's rule would. Its
#: config merges the inline config's servers deep into its own, as OpenCode does.
FAKE = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
agents = Path(os.environ["OPENCODE_CONFIG_DIR"]) / "agents"
args = sys.argv[1:]
if args == ["debug", "config"]:
    mcp = {{"github": {{"type": "remote", "url": "https://x.test/"}}}}
    for name, entry in json.loads(os.environ.get("OPENCODE_CONFIG_CONTENT", "{{}}")).get("mcp", {{}}).items():
        mcp[name] = {{**mcp.get(name, {{}}), **entry}}
    print(json.dumps({{"mcp": mcp}}))
elif args == ["debug", "skill"]:
    print(json.dumps([{{"name": "tracker-jira", "location": "/s", "content": "x"}}]))
elif args[:2] == ["debug", "agent"] and (agents / (args[2] + ".md")).is_file():
    rules = [{{"permission": "*", "pattern": "*", "action": "allow"}}]
    if args[2] == "canopy-chore":
        rules.append({{"permission": "github_*", "pattern": "*", "action": "deny"}})
    tools = {{"invalid": True, "bash": args[2] != "canopy-chore", "read": True}}
    print(json.dumps({{"name": args[2], "permission": rules, "tools": tools}}))
else:
    print("Error: Agent " + args[-1] + " not found", file=sys.stderr)
    sys.exit(1)
"""


@pytest.fixture
def opencode(tmp_path: Path) -> Iterator[Path]:
    """The fake `opencode`, first on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable(bin_dir / "opencode", FAKE)
    with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}):
        yield bin_dir


@pytest.mark.opencode1  # the fake above plays OpenCode 1's `debug`
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
    # OpenCode's stand-in for a call to a tool it lacks is no tool the agent is offered.
    assert "\ncanopy-chore\n  github: none\n  skills: tracker-jira\n  built-in tools: read\n" in out
    assert by_agent["canopy-worker"]["tools"] == ["bash", "read"]


@pytest.mark.opencode1  # the fake above plays OpenCode 1's `debug`
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


@pytest.mark.opencode1  # the fake above plays OpenCode 1's `debug`
@pytest.mark.usefixtures("opencode")
def test_canopy_agents_says_a_server_config_turns_off_is_off(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The runtime is asked with the operator's servers turned off as each run turns them off."""
    assert main(["agents", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["disabled_servers"] == []
    canopy_env.configure(canopy_env.user_file, {"runtime": {"mcp_servers": {"disabled": ["github"]}}})
    assert main(["agents", "--json"]) == 0
    printed = capsys.readouterr()
    assert json.loads(printed.out)["disabled_servers"] == ["github"]
    assert printed.err == ""


@pytest.mark.opencode1  # the fake above plays OpenCode 1's `debug`
@pytest.mark.usefixtures("opencode")
def test_canopy_agents_warns_of_a_server_to_turn_off_the_runtime_does_not_have(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Its entry has no type, which OpenCode ignores and starts nothing for: no server, and nothing to turn off."""
    canopy_env.configure(canopy_env.user_file, {"runtime": {"mcp_servers": {"disabled": ["github", "slack"]}}})
    assert main(["agents", "--json"]) == 0
    printed = capsys.readouterr()
    found = json.loads(printed.out)
    assert (found["servers"], found["disabled_servers"]) == (["github"], ["github"])
    assert printed.err == (
        "runtime.mcp_servers names slack, which your runtime config does not have: nothing to turn off.\n"
    )


@pytest.mark.opencode1  # the fake above plays OpenCode 1's `debug`
@pytest.mark.usefixtures("opencode")
def test_canopy_agents_says_which_agents_keep_a_server_out_of_their_own_runs(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The runtime, asked about every agent at once, has on what some role starts: the rest is each agent's."""
    tables: dict[str, object] = {"disabled": ["github"], "worker": {"disabled": []}}
    canopy_env.configure(canopy_env.user_file, {"runtime": {"mcp_servers": tables}})
    assert main(["agents", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found["disabled_servers"] == []
    off = {agent: ["github"] for agent in ("canopy-planner", "canopy-reviewer", "canopy-overseer", "canopy-chore")}
    assert found["mcp_servers_off"] == off
    assert main(["agents"]) == 0
    out = capsys.readouterr().out
    reviewer = out.split("\ncanopy-reviewer\n", 1)[1].split("\n\n", 1)[0]
    assert "\n  off in its runs by runtime.mcp_servers: github" in reviewer
    worker = out.split("\ncanopy-worker\n", 1)[1].split("\n\n", 1)[0]
    assert "runtime.mcp_servers" not in worker


def test_canopy_agents_fails_when_opencode_cannot_say(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch.dict(os.environ, {"PATH": str(tmp_path / "nothing")}):
        assert main(["agents"]) == 1
    assert capsys.readouterr().out == "The runtime could not say what it offers: opencode is not on PATH\n"
