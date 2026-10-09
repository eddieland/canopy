import tomllib
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import config, workspace
from canopy.core.config import load
from canopy.setup.init import is_ssh_url
from tests.conftest import CanopyEnv


@pytest.fixture
def empty(canopy_env: CanopyEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty directory outside any workspace or repository, as the working directory, and no user file yet."""
    canopy_env.user_file.unlink()
    path = tmp_path / "new"
    path.mkdir()
    monkeypatch.chdir(path)
    return path


def test_init_in_an_empty_directory_makes_a_workspace_and_writes_nothing_else(
    canopy_env: CanopyEnv, empty: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--provider", "github"]) == 0
    out = capsys.readouterr().out

    assert "'agent-ready-tester'" in out
    assert "Branch protection" in out
    assert "does not load" not in out
    assert 'labels = ["agent-ready-tester"]' in canopy_env.user_file.read_text()
    assert 'provider = "github"' in (empty / config.WORKSPACE_FILE_NAME).read_text()
    # Agent runs load canopy's definitions from its own directory (D040).
    assert sorted(p.name for p in empty.iterdir()) == [".gitignore", "MAP.md", config.WORKSPACE_FILE_NAME]

    # What init wrote loads.
    found = workspace.load(empty)
    assert (found.name, found.repos, found.state_dir) == ("new", (), empty / ".canopy")
    cfg = load(empty, canopy_env.user_file)
    assert cfg.tracker.labels == ("agent-ready-tester",)
    assert "{definitions_dir}" in cfg.runtime.overseer_cmd
    assert "{definitions_dir}" in cfg.runtime.worker_cmd


def test_init_writes_only_keys_without_a_useful_default(canopy_env: CanopyEnv, empty: Path) -> None:
    # A default written into a file is pinned there: a later canopy's default never reaches it.
    assert main(["init", "--provider", "jira"]) == 0
    user = tomllib.loads(canopy_env.user_file.read_text())
    shared = tomllib.loads((empty / config.WORKSPACE_FILE_NAME).read_text())
    assert user == {
        "tracker": {"labels": ["agent-ready-tester"]},
        "trust": {"authorized_repliers": [], "trusted_reviewers": []},
    }
    assert sorted(shared) == ["tracker", "workspace"]
    assert sorted(shared["tracker"]) == ["provider", "query"]


def test_init_in_a_workspace_never_overwrites_configs(
    canopy_env: CanopyEnv, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    user_before = canopy_env.user_file.read_text()
    shared_before = canopy_env.shared_file.read_text()
    monkeypatch.chdir(canopy_env.repo)  # inside the workspace, not at its root
    assert main(["init", "--provider", "github"]) == 0
    assert canopy_env.user_file.read_text() == user_before
    assert canopy_env.shared_file.read_text() == shared_before
    out = capsys.readouterr().out
    assert f"kept    {canopy_env.user_file}" in out
    assert f"kept    {canopy_env.shared_file}" in out
    assert not (canopy_env.repo / "canopy.toml").exists()


def test_init_refuses_a_code_checkout(
    canopy_env: CanopyEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D016: canopy writes nothing into a code repository; --workspace makes a repository of its own one."""
    checkout = tmp_path / "code"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "src").mkdir()
    monkeypatch.chdir(checkout / "src")
    assert main(["init", "--provider", "jira"]) == 2
    assert f"is inside the git repository {checkout}" in capsys.readouterr().err
    assert sorted(p.name for p in checkout.iterdir()) == [".git", "src"]
    monkeypatch.chdir(checkout)
    assert main(["init", "--workspace", "--provider", "jira"]) == 0
    assert (checkout / config.WORKSPACE_FILE_NAME).is_file()


def test_init_explains_an_old_user_file(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace("env OPENCODE_CONFIG_DIR={definitions_dir} ", ""))
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "The config does not load yet" in out
    assert "'env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-worker {prompt}'" in out


def test_init_warns_about_copies_of_canopys_agents(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    old = canopy_env.root / ".opencode" / "agent" / "canopy-worker.md"
    old.parent.mkdir(parents=True)
    old.write_text("---\ndescription: an old copy\n---\n")
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert f"Warning: OpenCode config here defines one of canopy's agents ({old})" in out
    assert old.exists()


def test_init_needs_provider_when_not_interactive(
    empty: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["init"]) == 2
    assert "--provider" in capsys.readouterr().err
    assert list(empty.iterdir()) == []


@pytest.mark.parametrize("provider", ["../evil", "Jira Cloud", "", "jira\n"])
def test_init_rejects_odd_provider_names(empty: Path, provider: str) -> None:
    assert main(["init", "--provider", provider]) == 2
    assert list(empty.iterdir()) == []


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
