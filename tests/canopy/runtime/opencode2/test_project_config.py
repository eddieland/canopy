"""OpenCode 2's own config where an agent starts or above it: the guard against a definition that shadows canopy's."""

from pathlib import Path

import pytest

from canopy.runtime.opencode2 import project_config


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
    [
        ".opencode/agent/my-helper.md",
        ".opencode/agent/team/canopy-worker.md",
        ".opencode/skills/canopy-worker/SKILL.md",
    ],
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


def test_shadowing_looks_in_every_directory_above_where_the_agent_starts(tmp_path: Path) -> None:
    # OpenCode 2 walks up to the filesystem's root, past the repository's, as a pool's worktree sits in canopy's state.
    worktree = tmp_path / "pools" / "api" / "slot-1"
    (worktree / ".git").mkdir(parents=True)
    above = tmp_path / ".opencode" / "agents" / "canopy-worker.md"
    above.parent.mkdir(parents=True)
    above.write_text("---\ndescription: x\n---\n")
    config = tmp_path / "pools" / "opencode.json"
    config.write_text('{"agent": {"canopy-reviewer": {}}}')
    assert project_config.shadowing(worktree) == [config, above]


def test_shadowing_looks_above_both_a_link_and_where_it_leads(tmp_path: Path) -> None:
    real = tmp_path / "real" / "worktree"
    real.mkdir(parents=True)
    (tmp_path / "links").mkdir()
    (tmp_path / "links" / "worktree").symlink_to(real)
    above_real = tmp_path / "real" / "opencode.json"
    above_link = tmp_path / "links" / "opencode.json"
    for config in (above_real, above_link):
        config.write_text('{"agent": {"canopy-worker": {}}}')
    assert project_config.shadowing(tmp_path / "links" / "worktree") == [above_link, above_real]


def test_shadowing_accepts_a_json_config_that_does_not(tmp_path: Path) -> None:
    (tmp_path / "opencode.json").write_text('{"mcp": {"docs": {"type": "remote", "url": "https://example.test"}}}')
    assert project_config.shadowing(tmp_path) == []


def test_the_shadowing_message_names_the_files(tmp_path: Path) -> None:
    message = project_config.shadowing_message([tmp_path / "opencode.json"])
    assert str(tmp_path / "opencode.json") in message
    assert "D044" in message


def test_naming_tools_finds_a_config_here_or_above_that_names_a_tool_of_the_server(tmp_path: Path) -> None:
    (tmp_path / ".opencode" / "agent").mkdir(parents=True)
    named = tmp_path / ".opencode" / "agent" / "helper.md"
    named.write_text('---\npermission:\n  "atlassian_editJiraIssue": allow\n---\n')
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "opencode.json").write_text('{"mcp": {"github": {}}}')
    assert project_config.naming_tools(tmp_path / "repo", "atlassian") == [named]
    assert project_config.naming_tools(tmp_path / "repo", "linear") == []
    message = project_config.naming_tools_message("atlassian", [named])
    assert str(named) in message
    assert "'atlassian'" in message


@pytest.mark.parametrize("rel", ["opencode.json", ".opencode/opencode.jsonc"])
def test_shadowing_finds_a_json_config_that_names_a_canopy_server(tmp_path: Path, rel: str) -> None:
    # Merged after it, its keys would reach canopy's own server for the overseer: its environment, say (DESIGN §27).
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"mcp": {"servers": {"canopy" : {"type": "local", "environment": {"PYTHONPATH": "/tmp/x"}}}}}')
    assert project_config.shadowing(tmp_path) == [path]
    assert "MCP server `canopy`" in project_config.shadowing_message([path])


def test_shadowing_accepts_another_server_whose_name_starts_with_canopy(tmp_path: Path) -> None:
    (tmp_path / "opencode.json").write_text('{"mcp": {"servers": {"canopy-docs": {"type": "remote"}}}}')
    assert project_config.shadowing(tmp_path) == []
