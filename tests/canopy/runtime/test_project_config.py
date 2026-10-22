"""Where the runtime's own config refuses an agent's start: shadowing, canopy's servers, then tracker tools."""

from pathlib import Path

from canopy.runtime import project_config


def shadow(root: Path) -> Path:
    path = root / ".opencode" / "agents" / "canopy-worker.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\ndescription: x\n---\n")
    return path


def name_tool(root: Path, server: str) -> Path:
    path = root / "opencode.json"
    path.write_text(f'{{"permission": {{"{server}_editJiraIssue": "allow"}}}}')
    return path


def test_a_start_is_refused_where_any_place_shadows_a_canopy_agent(tmp_path: Path) -> None:
    clean, shadowed = tmp_path / "clean", tmp_path / "shadowed"
    clean.mkdir()
    shadowed.mkdir()
    assert project_config.refusal([clean]) is None
    found = shadow(shadowed)
    refused = project_config.refusal([clean, shadowed])
    assert refused is not None
    assert str(found) in refused


def test_only_a_run_given_the_tracker_server_is_refused_where_its_tools_are_named(tmp_path: Path) -> None:
    found = name_tool(tmp_path, "atlassian")
    assert project_config.refusal([tmp_path]) is None
    assert project_config.refusal([tmp_path], tracker_server="linear") is None
    refused = project_config.refusal([tmp_path], tracker_server="atlassian")
    assert refused is not None
    assert str(found) in refused
    assert "'atlassian'" in refused


def test_shadowing_is_what_a_refusal_names_first(tmp_path: Path) -> None:
    shadowed = shadow(tmp_path)
    named = name_tool(tmp_path, "atlassian")
    refused = project_config.refusal([tmp_path], tracker_server="atlassian")
    assert refused is not None
    assert str(shadowed) in refused
    assert str(named) not in refused


def test_a_run_given_one_of_canopys_servers_is_refused_where_it_is_named(tmp_path: Path) -> None:
    found = tmp_path / "opencode.json"
    found.write_text('{"mcp": {"canopy_git": {"environment": {"GIT_DIR": "/elsewhere"}}}}')
    assert project_config.refusal([tmp_path]) is None
    assert project_config.refusal([tmp_path], servers=["canopy_chore"]) is None
    refused = project_config.refusal([tmp_path], servers=["canopy_chore", "canopy_git"])
    assert refused is not None
    assert f"'canopy_git', or its tools ({found})" in refused
    assert "canopy_chore" not in refused


def test_canopys_servers_are_named_after_shadowing_and_before_the_trackers_tools(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "opencode.json").write_text('{"permission": {"canopy_git_*": "allow"}}')
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    name_tool(tracker, "atlassian")
    refused = project_config.refusal([tracker, server], servers=["canopy_git"], tracker_server="atlassian")
    assert refused is not None
    assert "'canopy_git'" in refused
    assert "'atlassian'" not in refused
    shadowed = shadow(server)
    refused = project_config.refusal([server], servers=["canopy_git"])
    assert refused is not None
    assert str(shadowed) in refused


def test_naming_servers_names_every_server_and_file_once(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    both = first / "opencode.json"
    both.write_text('{"permission": {"canopy_git_*": "allow", "canopy_chore_history": "deny"}}')
    chore = second / "opencode.json"
    chore.write_text('{"mcp": {"canopy_chore": {}}}')
    assert project_config.naming_servers([first, second], ["other"]) is None
    named = project_config.naming_servers([first, second], ["canopy_git", "canopy_chore"])
    assert named is not None
    assert f"servers 'canopy_git' and 'canopy_chore', or their tools ({both}, {chore})" in named
