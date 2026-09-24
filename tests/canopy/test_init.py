from pathlib import Path

import pytest
from conftest import CanopyEnv

from canopy import resources
from canopy.cli import main
from canopy.config import load


def test_init_writes_both_configs_and_installs_agents_and_skill(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    canopy_env.user_file.unlink()
    canopy_env.repo_file.unlink()
    assert main(["init", "--provider", "github"]) == 0
    out = capsys.readouterr().out

    assert "'agent-ready-tester'" in out
    assert "Branch protection" in out
    assert 'labels = ["agent-ready-tester"]' in canopy_env.user_file.read_text()
    assert 'provider = "github"' in canopy_env.repo_file.read_text()
    for name in ("canopy-overseer.md", "canopy-worker.md"):
        installed = canopy_env.repo / ".opencode" / "agent" / name
        assert installed.read_text() == (resources.agents_dir() / name).read_text()
    skill = canopy_env.repo / ".opencode" / "skill" / "tracker-github" / "SKILL.md"
    assert skill.read_text() == (resources.skills_dir() / "tracker-github" / "SKILL.md").read_text()

    # What init wrote loads. The user file has no state_dir, so it defaults under the fake HOME.
    cfg = load(canopy_env.repo, canopy_env.user_file)
    assert cfg.tracker.labels == ("agent-ready-tester",)
    assert cfg.paths.state_dir == canopy_env.home / ".canopy"


def test_init_never_overwrites_configs(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    user_before = canopy_env.user_file.read_text()
    repo_before = canopy_env.repo_file.read_text()
    assert main(["init", "--provider", "github"]) == 0
    assert canopy_env.user_file.read_text() == user_before
    assert canopy_env.repo_file.read_text() == repo_before
    out = capsys.readouterr().out
    assert f"kept  {canopy_env.user_file}" in out
    # The existing canopy.toml says jira, so the jira skill is installed, not the one named on the command line.
    assert (canopy_env.repo / ".opencode" / "skill" / "tracker-jira" / "SKILL.md").exists()
    assert not (canopy_env.repo / ".opencode" / "skill" / "tracker-github").exists()


def test_init_uses_existing_repo_provider_and_refreshes_agents(canopy_env: CanopyEnv) -> None:
    agent = canopy_env.repo / ".opencode" / "agent" / "canopy-overseer.md"
    agent.parent.mkdir(parents=True)
    agent.write_text("stale\n")
    assert main(["init"]) == 0
    assert agent.read_text() == (resources.agents_dir() / "canopy-overseer.md").read_text()
    assert (canopy_env.repo / ".opencode" / "skill" / "tracker-jira" / "SKILL.md").exists()


def test_init_without_skill_for_provider(canopy_env: CanopyEnv) -> None:
    canopy_env.repo_file.unlink()
    assert main(["init", "--provider", "linear"]) == 0
    assert not (canopy_env.repo / ".opencode" / "skill").exists()


def test_init_needs_provider_when_not_interactive(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    canopy_env.repo_file.unlink()
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["init"]) == 2  # noqa: PLR2004
    assert "--provider" in capsys.readouterr().err
    assert not canopy_env.repo_file.exists()


@pytest.mark.parametrize("provider", ["../evil", "Jira Cloud", ""])
def test_init_rejects_odd_provider_names(canopy_env: CanopyEnv, provider: str) -> None:
    canopy_env.repo_file.unlink()
    assert main(["init", "--provider", provider]) == 2  # noqa: PLR2004


def test_init_outside_a_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--provider", "jira"]) == 2  # noqa: PLR2004


def test_init_rejects_provider_with_trailing_newline(canopy_env: CanopyEnv) -> None:
    canopy_env.repo_file.unlink()
    assert main(["init", "--provider", "jira\n"]) == 2  # noqa: PLR2004
    assert not canopy_env.repo_file.exists()
