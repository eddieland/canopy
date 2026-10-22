"""The runtime's own config where an agent starts: the guard against a definition that shadows canopy's (D044)."""

from pathlib import Path

import pytest

from canopy.runtime.opencode import project_config


@pytest.mark.parametrize(
    "rel",
    [
        ".opencode/agent/canopy-worker.md",
        ".opencode/agents/canopy-overseer.md",
        ".opencode/mode/canopy-worker.md",
        ".opencode/modes/canopy-worker.md",
    ],
)
def test_shadowing_finds_an_agent_file_with_a_canopy_name(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("---\ndescription: x\n---\n")
    assert project_config.shadowing(tmp_path) == [path]


@pytest.mark.parametrize(
    "rel",
    [".opencode/agent/my-helper.md", ".opencode/agent/team/canopy-worker.md", ".opencode/skill/canopy-worker/SKILL.md"],
)
def test_shadowing_ignores_other_agents_and_skills(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("---\ndescription: x\n---\n")
    assert project_config.shadowing(tmp_path) == []


@pytest.mark.parametrize(
    "rel",
    ["opencode.json", "opencode.jsonc", ".opencode/opencode.json", ".opencode/opencode.jsonc"],
)
def test_shadowing_finds_a_json_config_that_names_a_canopy_agent(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"agent": {"canopy-worker": {"permission": {"bash": {"*": "allow"}}}}}')
    assert project_config.shadowing(tmp_path) == [path]


def test_shadowing_accepts_a_json_config_that_does_not(tmp_path: Path) -> None:
    (tmp_path / "opencode.json").write_text('{"mcp": {"docs": {"type": "remote", "url": "https://example.test"}}}')
    assert project_config.shadowing(tmp_path) == []


def test_the_shadowing_message_names_the_files(tmp_path: Path) -> None:
    message = project_config.shadowing_message([tmp_path / "opencode.json"])
    assert str(tmp_path / "opencode.json") in message
    assert "D044" in message


def test_naming_tools_finds_a_config_that_names_a_tool_of_the_server(tmp_path: Path) -> None:
    (tmp_path / ".opencode" / "agent").mkdir(parents=True)
    named = tmp_path / ".opencode" / "agent" / "helper.md"
    named.write_text('---\npermission:\n  "atlassian_editJiraIssue": allow\n---\n')
    (tmp_path / "opencode.json").write_text('{"mcp": {"github": {}}}')
    assert project_config.naming_tools(tmp_path, "atlassian") == [named]
    assert project_config.naming_tools(tmp_path, "linear") == []
    message = project_config.naming_tools_message("atlassian", [named])
    assert str(named) in message
    assert "'atlassian'" in message


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("opencode.json", '{"mcp": {"canopy_git": {"command": ["./git-tools"]}}}'),
        (".opencode/opencode.jsonc", '{"permission": {"canopy_git_*": "allow"}}'),
        (".opencode/agent/helper.md", "---\ntools:\n  canopy_git_diff: true\n---\n"),
    ],
)
def test_naming_server_finds_a_config_that_names_the_server_or_its_tools(tmp_path: Path, rel: str, text: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    assert project_config.naming_server(tmp_path, "canopy_git") == [path]
    assert project_config.naming_server(tmp_path, "canopy_chore") == []


def test_the_naming_server_message_names_each_server_and_the_files(tmp_path: Path) -> None:
    found = [tmp_path / "opencode.json"]
    one = project_config.naming_server_message(["canopy_git"], found)
    assert f"MCP server 'canopy_git', or its tools ({found[0]})" in one
    both = project_config.naming_server_message(["canopy_git", "canopy_chore"], found)
    assert "MCP servers 'canopy_git' and 'canopy_chore', or their tools" in both
