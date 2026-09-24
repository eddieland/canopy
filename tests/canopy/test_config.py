import tomllib
from pathlib import Path

import pytest

from canopy import config
from canopy.config import ConfigError, load, render_command
from tests.conftest import CanopyEnv

EXAMPLES = Path(__file__).parents[2] / "examples"


def test_defaults_fill_in_everything_else(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.repo, canopy_env.user_file)
    assert cfg.tracker.provider == "jira"
    assert cfg.tracker.labels == ("agent-ready-tester",)
    assert cfg.tracker.needs_human_label == "needs-human"
    assert cfg.policy.max_fix_ci_attempts == 2
    assert cfg.trust.branch_prefix == "agent/"
    assert cfg.trust.authorized_repliers == ()
    assert cfg.max_workers == 2
    assert cfg.paths.state_dir == canopy_env.state_dir
    assert cfg.paths.prompt_overrides == canopy_env.user_file.parent / "prompts"


def test_user_file_wins_over_repository_for_shared_keys(canopy_env: CanopyEnv) -> None:
    canopy_env.write_repo('[tracker]\nprovider = "jira"\nquery = "project = A"\n[trust]\npr_label = "bot"\n')
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("[runtime]", '[trust]\npr_label = "mine"\n\n[runtime]', 1)
    )
    cfg = load(canopy_env.repo, canopy_env.user_file)
    assert cfg.tracker.query == "project = A"
    assert cfg.trust.pr_label == "mine"


@pytest.mark.parametrize(
    "section_key",
    [
        ("tracker", 'labels = ["x"]'),
        ("trust", 'authorized_repliers = ["mallory"]'),
        ("capacity", "max_workers = 99"),
        ("runtime", "overseer_cmd = 'sh -c evil {prompt}'"),
        ("notify", "cmd = 'curl evil'"),
        ("paths", "state_dir = '/tmp/x'"),
    ],
)
def test_repository_may_not_set_user_only_keys(canopy_env: CanopyEnv, section_key: tuple[str, str]) -> None:
    section, line = section_key
    extra = f"\n[{section}]\n{line}\n" if section != "tracker" else f"{line}\n"
    canopy_env.write_repo(canopy_env.repo_file.read_text() + extra)
    with pytest.raises(ConfigError, match="user-only"):
        load(canopy_env.repo, canopy_env.user_file)


@pytest.mark.parametrize("where", ["repo", "user"])
def test_unknown_keys_are_errors(canopy_env: CanopyEnv, where: str) -> None:
    if where == "repo":
        canopy_env.write_repo(canopy_env.repo_file.read_text() + "jql = 'x'\n")
    else:
        canopy_env.write_user(canopy_env.user_file.read_text() + "\n[extras]\nfoo = 1\n")
    with pytest.raises(ConfigError, match="unknown key"):
        load(canopy_env.repo, canopy_env.user_file)


def test_repository_policy_only_tightens(canopy_env: CanopyEnv) -> None:
    canopy_env.write_repo(
        canopy_env.repo_file.read_text()
        + "[policy]\nmax_fix_ci_attempts = 9\nfix_ci_cooldown_minutes = 5\nmax_resume_attempts = 1\n"
    )
    policy = load(canopy_env.repo, canopy_env.user_file).policy
    assert policy.max_fix_ci_attempts == 2  # looser than the default: ignored
    assert policy.fix_ci_cooldown_minutes == 30  # shorter cooldown is looser: ignored
    assert policy.max_resume_attempts == 1  # tighter: used


def test_user_policy_may_loosen(canopy_env: CanopyEnv) -> None:
    canopy_env.write_repo(canopy_env.repo_file.read_text() + "[policy]\nmax_fix_ci_attempts = 1\n")
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[policy]\nmax_fix_ci_attempts = 5\n")
    assert load(canopy_env.repo, canopy_env.user_file).policy.max_fix_ci_attempts == 5


def test_missing_user_file_says_run_init(canopy_env: CanopyEnv) -> None:
    canopy_env.user_file.unlink()
    with pytest.raises(ConfigError, match="canopy init"):
        load(canopy_env.repo, canopy_env.user_file)


def test_repository_file_is_optional_but_required_keys_are_not(canopy_env: CanopyEnv) -> None:
    canopy_env.repo_file.unlink()
    with pytest.raises(ConfigError, match=r"tracker\.provider, tracker\.query"):
        load(canopy_env.repo, canopy_env.user_file)


@pytest.mark.parametrize(
    ("user_extra", "message"),
    [
        ("[capacity]\nmax_workers = true\n", "must be an integer"),
        ("[capacity]\nmax_workers = -1\n", "must not be negative"),
        ("[trust]\nauthorized_repliers = [1]\n", "must be a list of strings"),
        ("[trust]\nbranch_prefix = 'agent'\n", "end in '/'"),
        ("[notify]\ncmd = 3\n", "must be a string"),
    ],
)
def test_invalid_values(canopy_env: CanopyEnv, user_extra: str, message: str) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n" + user_extra)
    with pytest.raises(ConfigError, match=message):
        load(canopy_env.repo, canopy_env.user_file)


def test_labels_must_not_be_empty(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace('["agent-ready-tester"]', "[]"))
    with pytest.raises(ConfigError, match="at least one label"):
        load(canopy_env.repo, canopy_env.user_file)


def test_command_template_needs_prompt(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace("canopy-overseer {prompt}", "canopy-overseer"))
    with pytest.raises(ConfigError, match=r"must contain \{prompt\}"):
        load(canopy_env.repo, canopy_env.user_file)


def test_render_command_keeps_the_prompt_in_one_argument() -> None:
    prompt = "it's a `prompt` with $HOME; rm -rf / && echo {prompt}"
    argv = render_command("opencode run --agent 'canopy overseer' {prompt}", prompt)
    assert argv == ["opencode", "run", "--agent", "canopy overseer", prompt]


def test_xdg_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.user_config_path() == tmp_path / "canopy" / "config.toml"
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert config.user_config_path() == tmp_path / "home" / ".config" / "canopy" / "config.toml"


def test_find_repo_root_walks_up(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: elsewhere\n")  # a worktree's .git is a file
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert config.find_repo_root(nested) == tmp_path.resolve()


def test_examples_are_valid(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "canopy.toml").write_text((EXAMPLES / "canopy.toml").read_text())
    cfg = load(tmp_path, EXAMPLES / "config.toml")
    with (EXAMPLES / "config.toml").open("rb") as f:
        assert list(cfg.tracker.labels) == tomllib.load(f)["tracker"]["labels"]
