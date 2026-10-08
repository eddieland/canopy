import tomllib
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core.config import load
from canopy.setup.init import is_ssh_url
from tests.conftest import CanopyEnv, git


def test_init_writes_both_configs_and_installs_nothing_else(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    canopy_env.user_file.unlink()
    canopy_env.repo_file.unlink()
    assert main(["init", "--provider", "github"]) == 0
    out = capsys.readouterr().out

    assert "'agent-ready-tester'" in out
    assert "Branch protection" in out
    assert "does not load" not in out
    assert 'labels = ["agent-ready-tester"]' in canopy_env.user_file.read_text()
    assert 'provider = "github"' in canopy_env.repo_file.read_text()
    # Agent runs load canopy's definitions from its own directory (D040); nothing goes into the repository.
    assert sorted(p.name for p in canopy_env.repo.iterdir()) == [".git", "canopy.toml"]

    # What init wrote loads. The user file has no state_dir, so it defaults under the fake HOME.
    cfg = load(canopy_env.repo, canopy_env.user_file)
    assert cfg.tracker.labels == ("agent-ready-tester",)
    assert cfg.paths.state_dir == canopy_env.home / ".canopy"
    assert "{definitions_dir}" in cfg.runtime.overseer_cmd
    assert "{definitions_dir}" in cfg.runtime.worker_cmd


def test_init_writes_only_keys_without_a_useful_default(canopy_env: CanopyEnv) -> None:
    # A default written into a file is pinned there: a later canopy's default never reaches it.
    canopy_env.user_file.unlink()
    canopy_env.repo_file.unlink()
    assert main(["init", "--provider", "jira"]) == 0
    user = tomllib.loads(canopy_env.user_file.read_text())
    repo = tomllib.loads(canopy_env.repo_file.read_text())
    assert user == {
        "tracker": {"labels": ["agent-ready-tester"]},
        "trust": {"authorized_repliers": [], "trusted_reviewers": []},
    }
    assert sorted(repo) == ["tracker"]
    assert sorted(repo["tracker"]) == ["provider", "query"]


def test_init_never_overwrites_configs(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    user_before = canopy_env.user_file.read_text()
    repo_before = canopy_env.repo_file.read_text()
    assert main(["init", "--provider", "github"]) == 0
    assert canopy_env.user_file.read_text() == user_before
    assert canopy_env.repo_file.read_text() == repo_before
    assert f"kept  {canopy_env.user_file}" in capsys.readouterr().out


def test_init_explains_an_old_user_file(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace("env OPENCODE_CONFIG_DIR={definitions_dir} ", ""))
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "The config does not load yet" in out
    assert "'env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-worker {prompt}'" in out


def test_init_warns_about_copies_of_canopys_agents(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    old = canopy_env.repo / ".opencode" / "agent" / "canopy-worker.md"
    old.parent.mkdir(parents=True)
    old.write_text("---\ndescription: an old copy\n---\n")
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert f"Warning: OpenCode config here defines one of canopy's agents ({old})" in out
    assert old.exists()


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
