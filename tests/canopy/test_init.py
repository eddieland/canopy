from pathlib import Path

import pytest

from canopy import resources
from canopy.cli import main
from canopy.config import load
from canopy.init import is_ssh_url
from tests.conftest import CanopyEnv, git


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
    assert main(["init"]) == 2
    assert "--provider" in capsys.readouterr().err
    assert not canopy_env.repo_file.exists()


@pytest.mark.parametrize("provider", ["../evil", "Jira Cloud", ""])
def test_init_rejects_odd_provider_names(canopy_env: CanopyEnv, provider: str) -> None:
    canopy_env.repo_file.unlink()
    assert main(["init", "--provider", provider]) == 2


def test_init_outside_a_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--provider", "jira"]) == 2


def test_init_rejects_provider_with_trailing_newline(canopy_env: CanopyEnv) -> None:
    canopy_env.repo_file.unlink()
    assert main(["init", "--provider", "jira\n"]) == 2
    assert not canopy_env.repo_file.exists()


@pytest.mark.parametrize(
    ("url", "ssh"),
    [
        ("git@github.com:acme/api.git", True),
        ("github.com:acme/api.git", True),
        ("ssh://git@github.com/acme/api.git", True),
        ("SSH://git@github.com:22/acme/api.git", True),
        ("git+ssh://git@github.com/acme/api.git", True),
        ("https://github.com/acme/api.git", False),
        ("http://example.com/a:b.git", False),
        ("file:///srv/git/api.git", False),
        ("/srv/git/api.git", False),
        ("./api:v2.git", False),
        ("api.git", False),
    ],
)
def test_is_ssh_url(url: str, *, ssh: bool) -> None:
    assert is_ssh_url(url) is ssh


@pytest.fixture
def no_env_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop git config passed through the environment, which may itself rewrite SSH URLs to HTTPS."""
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    monkeypatch.delenv("GIT_CONFIG_PARAMETERS", raising=False)


def _real_repo(canopy_env: CanopyEnv, url: str | None) -> None:
    (canopy_env.repo / ".git").rmdir()
    git("init", "--quiet", cwd=canopy_env.repo)
    if url is not None:
        git("remote", "add", "origin", url, cwd=canopy_env.repo)


@pytest.mark.usefixtures("no_env_git_config")
def test_init_warns_about_an_ssh_origin(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    _real_repo(canopy_env, "git@github.com:acme/api.git")
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "origin pushes over SSH (git@github.com:acme/api.git)" in out
    assert "D038" in out


@pytest.mark.usefixtures("no_env_git_config")
def test_init_warns_when_insteadof_rewrites_to_ssh(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    _real_repo(canopy_env, "https://github.com/acme/api.git")
    git("config", "url.git@github.com:.pushInsteadOf", "https://github.com/", cwd=canopy_env.repo)
    assert main(["init"]) == 0
    assert "origin pushes over SSH (git@github.com:acme/api.git)" in capsys.readouterr().out


def test_init_is_quiet_when_insteadof_rewrites_ssh_to_https(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    _real_repo(canopy_env, "git@github.com:acme/api.git")
    git("config", "url.https://github.com/.insteadOf", "git@github.com:", cwd=canopy_env.repo)
    assert main(["init"]) == 0
    assert "SSH" not in capsys.readouterr().out


@pytest.mark.usefixtures("no_env_git_config")
@pytest.mark.parametrize("url", ["https://github.com/acme/api.git", None])
def test_init_is_quiet_about_https_or_no_origin(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str], url: str | None
) -> None:
    _real_repo(canopy_env, url)
    assert main(["init"]) == 0
    assert "SSH" not in capsys.readouterr().out
