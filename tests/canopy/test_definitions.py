"""The snapshot agent runs load canopy's agents and skills from, and the guard against shadowing them (D040, D044)."""

import os
import shutil
import time
from pathlib import Path

import pytest

from canopy.core import definitions
from canopy.infra import resources


def test_the_snapshot_holds_the_bundled_agents_and_skills(tmp_path: Path) -> None:
    snapshot = definitions.ensure(tmp_path)
    assert snapshot == tmp_path / "runtime" / definitions.digest()
    for name in definitions.agent_names():
        bundled = resources.agents_dir() / f"{name}.md"
        assert (snapshot / "agents" / f"{name}.md").read_text() == bundled.read_text()
    for skill in resources.skills_dir().iterdir():
        assert (snapshot / "skills" / skill.name / "SKILL.md").read_text() == (skill / "SKILL.md").read_text()
    assert "canopy-worker" in definitions.agent_names()
    assert "canopy-overseer" in definitions.agent_names()


def test_an_existing_snapshot_is_reused_as_is(tmp_path: Path) -> None:
    snapshot = definitions.ensure(tmp_path)
    # OpenCode writes into the directory it loads; that must not make canopy copy again.
    (snapshot / "node_modules").mkdir()
    assert definitions.ensure(tmp_path) == snapshot
    assert (snapshot / "node_modules").is_dir()
    assert [p.name for p in (tmp_path / "runtime").iterdir()] == [snapshot.name]


def test_losing_the_race_to_create_a_snapshot_uses_the_winners(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = tmp_path / "runtime" / definitions.digest()
    real_rename = os.rename

    def another_process_wins(src: Path, dst: Path) -> None:
        shutil.copytree(src, final)
        (final / "winner").touch()
        real_rename(src, dst)  # refused: dst is a directory that is not empty

    monkeypatch.setattr(os, "rename", another_process_wins)
    assert definitions.ensure(tmp_path) == final
    assert (final / "winner").exists()
    assert [p.name for p in (tmp_path / "runtime").iterdir()] == [final.name]


def test_prune_keeps_the_current_snapshot_and_fresh_temporary_directories(tmp_path: Path) -> None:
    current = definitions.ensure(tmp_path)
    runtime = tmp_path / "runtime"
    old = runtime / "0123456789abcdef"
    old.mkdir()
    fresh_tmp = runtime / ".tmp-fresh"
    fresh_tmp.mkdir()
    stale_tmp = runtime / ".tmp-stale"
    stale_tmp.mkdir()
    hours_ago = time.time() - 2 * 3600
    os.utime(stale_tmp, (hours_ago, hours_ago))

    assert definitions.prune(tmp_path, current) == [stale_tmp, old]
    assert sorted(p.name for p in runtime.iterdir()) == sorted([current.name, fresh_tmp.name])


def test_prune_without_a_runtime_directory(tmp_path: Path) -> None:
    assert definitions.prune(tmp_path, tmp_path / "runtime" / "x") == []


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
    assert definitions.shadowing(tmp_path) == [path]


@pytest.mark.parametrize(
    "rel",
    [".opencode/agent/my-helper.md", ".opencode/agent/team/canopy-worker.md", ".opencode/skill/canopy-worker/SKILL.md"],
)
def test_shadowing_ignores_other_agents_and_skills(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("---\ndescription: x\n---\n")
    assert definitions.shadowing(tmp_path) == []


@pytest.mark.parametrize(
    "rel", ["opencode.json", "opencode.jsonc", ".opencode/opencode.json", ".opencode/opencode.jsonc"]
)
def test_shadowing_finds_a_json_config_that_names_a_canopy_agent(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"agent": {"canopy-worker": {"permission": {"bash": {"*": "allow"}}}}}')
    assert definitions.shadowing(tmp_path) == [path]


def test_shadowing_accepts_a_json_config_that_does_not(tmp_path: Path) -> None:
    (tmp_path / "opencode.json").write_text('{"mcp": {"docs": {"type": "remote", "url": "https://example.test"}}}')
    assert definitions.shadowing(tmp_path) == []


def test_the_shadowing_message_names_the_files(tmp_path: Path) -> None:
    message = definitions.shadowing_message([tmp_path / "opencode.json"])
    assert str(tmp_path / "opencode.json") in message
    assert "D044" in message
