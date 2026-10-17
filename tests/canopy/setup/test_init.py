import contextlib
import json
import shlex
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, workspace
from canopy.core.config import load
from canopy.setup.init import is_ssh_url, sandbox_suggestion
from tests.conftest import CanopyEnv


@pytest.fixture
def empty(canopy_env: CanopyEnv, tmp_path: Path) -> Iterator[Path]:
    """An empty directory outside any workspace or repository, as the working directory, and no user file yet."""
    canopy_env.user_file.unlink()
    path = tmp_path / "new"
    path.mkdir()
    with contextlib.chdir(path):
        yield path


def test_init_in_an_empty_directory_makes_a_workspace_and_writes_nothing_else(
    canopy_env: CanopyEnv, empty: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--provider", "github"]) == 0
    out = capsys.readouterr().out

    assert "'agent-ready-tester'" in out
    assert "Branch protection" in out
    assert "does not load" not in out
    private_file = empty / ".canopy" / "config.toml"
    assert 'labels = ["agent-ready-tester"]' in private_file.read_text()
    assert private_file.stat().st_mode & 0o777 == 0o600
    assert not canopy_env.user_file.exists()
    assert 'provider = "github"' in (empty / config.WORKSPACE_FILE_NAME).read_text()
    # Agent runs load canopy's definitions from its own directory (D040).
    assert sorted(p.name for p in empty.iterdir()) == [".canopy", ".gitignore", "MAP.md", config.WORKSPACE_FILE_NAME]
    assert [p.name for p in (empty / ".canopy").iterdir()] == ["config.toml"]

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
    private = tomllib.loads((empty / ".canopy" / "config.toml").read_text())
    shared = tomllib.loads((empty / config.WORKSPACE_FILE_NAME).read_text())
    assert private == {
        "tracker": {"labels": ["agent-ready-tester"]},
        "trust": {"authorized_repliers": [], "trusted_reviewers": []},
    }
    assert sorted(shared) == ["tracker", "workspace"]
    assert sorted(shared["tracker"]) == ["provider", "query"]


def test_init_in_a_workspace_never_overwrites_configs(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    user_before = canopy_env.user_file.read_text()
    shared_before = canopy_env.shared_file.read_text()
    private_file = canopy_env.state_dir / "config.toml"
    with contextlib.chdir(canopy_env.repo):  # inside the workspace, not at its root
        assert main(["init", "--provider", "github"]) == 0
        assert canopy_env.user_file.read_text() == user_before
        assert canopy_env.shared_file.read_text() == shared_before
        out = capsys.readouterr().out
        assert f"wrote   {private_file}" in out
        assert f"kept    {canopy_env.shared_file}" in out
        assert not (canopy_env.repo / "canopy.toml").exists()

        private_file.write_text("# mine\n")
        assert main(["init"]) == 0
        assert f"kept    {private_file}" in capsys.readouterr().out
        assert private_file.read_text() == "# mine\n"


def test_init_leaves_out_of_the_private_file_what_the_user_file_sets(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    """An existing user file keeps working unchanged: the private file does not override its labels or trust lists."""
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("[runtime]", "[trust]\nauthorized_repliers = ['me']\n\n[runtime]")
    )
    assert main(["init"]) == 0

    assert "queue label" not in capsys.readouterr().out
    private = tomllib.loads((canopy_env.state_dir / "config.toml").read_text())
    assert private == {"trust": {"trusted_reviewers": []}}
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert (cfg.tracker.labels, cfg.trust.authorized_repliers) == (("agent-ready-tester",), ("me",))


def test_init_refuses_a_code_checkout(
    canopy_env: CanopyEnv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D016: canopy writes nothing into a code repository; --workspace makes a repository of its own one."""
    checkout = tmp_path / "code"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "src").mkdir()
    with contextlib.chdir(checkout / "src"):
        assert main(["init", "--provider", "jira"]) == 2
        assert f"is inside the git repository {checkout}" in capsys.readouterr().err
        assert sorted(p.name for p in checkout.iterdir()) == [".git", "src"]
    with contextlib.chdir(checkout):
        assert main(["init", "--workspace", "--provider", "jira"]) == 0
        assert (checkout / config.WORKSPACE_FILE_NAME).is_file()


def test_init_names_a_leftover_canopy_toml_in_the_checkout(
    canopy_env: CanopyEnv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    checkout = tmp_path / "code"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "canopy.toml").write_text("[tracker]\n")
    with contextlib.chdir(checkout):
        assert main(["init", "--provider", "jira"]) == 2
        assert f"{checkout / 'canopy.toml'} is not read: move its keys" in capsys.readouterr().err


def test_init_refuses_the_home_directory(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    """Every later init below it would fill it in, and its .canopy/ is an earlier canopy's journal."""
    with contextlib.chdir(canopy_env.home):
        assert main(["init", "--provider", "jira"]) == 2
        assert "is your home directory" in capsys.readouterr().err
        assert not (canopy_env.home / config.WORKSPACE_FILE_NAME).exists()


def test_init_refuses_a_directory_with_a_journal_and_no_workspace_file(
    empty: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (empty / ".canopy").mkdir(mode=0o700)
    assert main(["init", "--workspace", "--provider", "jira"]) == 2
    assert "may be an earlier canopy's journal" in capsys.readouterr().err
    assert not (empty / config.WORKSPACE_FILE_NAME).exists()


def test_init_under_a_home_that_is_a_dotfiles_repository(canopy_env: CanopyEnv) -> None:
    """A repository at the home directory is the operator's dotfiles, not a code repository."""
    (canopy_env.home / ".git").mkdir()
    root = canopy_env.home / "acme"
    root.mkdir()
    with contextlib.chdir(root):
        assert main(["init", "--provider", "jira"]) == 0
        assert (root / config.WORKSPACE_FILE_NAME).is_file()


def test_init_warns_about_copies_of_canopys_agents_in_a_repository(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    """An earlier single-repository init committed them; a clone of that repository carries them."""
    old = canopy_env.repo / ".opencode" / "agent" / "canopy-worker.md"
    old.parent.mkdir(parents=True)
    old.write_text("---\ndescription: an old copy\n---\n")
    assert main(["init"]) == 0
    assert f"Warning: OpenCode config here defines one of canopy's agents ({old})" in capsys.readouterr().out


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


def test_init_suggests_a_sandboxed_worker_cmd_and_writes_none(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    before = canopy_env.user_file.read_text()
    worker_cmd = load(canopy_env.root, canopy_env.user_file).runtime.worker_cmd
    assert main(["init"]) == 0
    out = capsys.readouterr().out

    assert "Optional: run workers in a sandbox" in out
    suggested = _suggested_worker_cmd(out)
    assert shlex.split(suggested) == [*SANDBOX_PREFIX, *shlex.split(worker_cmd)]
    assert canopy_env.user_file.read_text() == before

    # The suggestion is a template the config accepts.
    lines = [
        f"worker_cmd = {json.dumps(suggested)}" if x.startswith("worker_cmd =") else x for x in before.splitlines()
    ]
    canopy_env.write_user("\n".join(lines) + "\n")
    assert load(canopy_env.root, canopy_env.user_file).runtime.worker_cmd == suggested


def test_init_suggests_nothing_once_workers_are_sandboxed(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    sandboxed = "\nworker_cmd = '/opt/bin/canopy-sandbox worker --read {definitions_dir} -- env"
    canopy_env.write_user(canopy_env.user_file.read_text().replace("\nworker_cmd = 'env", sandboxed))
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "Branch protection" in out
    assert "Optional: run workers in a sandbox" not in out


@pytest.mark.parametrize(
    "worker_cmd",
    [
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker --title={title} {prompt}",
        # What a TOML literal string cannot hold, so the suggestion falls back to a basic one.
        "agent {definitions_dir} {prompt} --sep \"'''\"",
        'agent {definitions_dir} {prompt} --sep "\x07"',
        "agent {definitions_dir} '{prompt}'",
    ],
)
def test_sandbox_suggestion_reads_back_as_the_prefixed_template(worker_cmd: str, tmp_path: Path) -> None:
    out = sandbox_suggestion(worker_cmd, tmp_path / "config.toml")
    assert str(tmp_path / "config.toml") in out
    assert shlex.split(_suggested_worker_cmd(out)) == [*SANDBOX_PREFIX, *shlex.split(worker_cmd)]


SANDBOX_PREFIX = ["canopy-sandbox", "worker", "--read", "{definitions_dir}", "--"]


def _suggested_worker_cmd(out: str) -> str:
    """Read the `worker_cmd` that init suggests, from the `[runtime]` table it prints."""
    value: str = tomllib.loads(out[out.index("  [runtime]\n") :])["runtime"]["worker_cmd"]
    return value


def test_init_needs_provider_when_not_interactive(empty: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch.object(sys.stdin, "isatty", autospec=True, return_value=False):
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
