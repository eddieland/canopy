"""Where the runtime's own config refuses an agent's start: shadowing first, then a private run's tracker tools."""

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


def test_a_file_two_places_share_is_named_once(tmp_path: Path) -> None:
    # The runtime reads a place's parents too, so a repository in the workspace finds the workspace's config.
    found = shadow(tmp_path)
    named = name_tool(tmp_path, "atlassian")
    repo = tmp_path / "repo"
    repo.mkdir()
    refused = project_config.refusal([tmp_path, repo])
    assert refused is not None
    assert refused.count(str(found)) == 1
    found.unlink()
    refused = project_config.refusal([tmp_path, repo], tracker_server="atlassian")
    assert refused is not None
    assert refused.count(str(named)) == 1
