import re
import tomllib
from pathlib import Path

import pytest

from canopy.core import config
from canopy.core.config import ConfigError, load, render_command
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
    assert cfg.trust.comment_prefix == "CANOPY:"
    assert cfg.trust.comment_suffix == ""
    assert cfg.capacity.max_workers == 2
    assert cfg.loop.interval_minutes == 15
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


def test_needs_human_label_is_set_by_the_repository_and_overridden_by_the_user(canopy_env: CanopyEnv) -> None:
    canopy_env.write_repo(canopy_env.repo_file.read_text() + 'needs_human_label = "blocked-on-team"\n')
    assert load(canopy_env.repo, canopy_env.user_file).tracker.needs_human_label == "blocked-on-team"
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("[tracker]\n", '[tracker]\nneeds_human_label = "ask-me"\n', 1)
    )
    assert load(canopy_env.repo, canopy_env.user_file).tracker.needs_human_label == "ask-me"


@pytest.mark.parametrize(
    "section_key",
    [
        ("tracker", 'labels = ["x"]'),
        ("trust", 'authorized_repliers = ["mallory"]'),
        ("trust", 'comment_prefix = "Please"'),
        ("capacity", "max_workers = 99"),
        ("loop", "interval_minutes = 1"),
        ("runtime", "overseer_cmd = 'sh -c evil {prompt}'"),
        ("runtime", "pr_skill = 'evil-pr'"),
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


def test_stacking_defaults_to_auto(canopy_env: CanopyEnv) -> None:
    assert load(canopy_env.repo, canopy_env.user_file).policy.stacking == "auto"


def test_repository_may_turn_stacking_off_and_the_user_back_on(canopy_env: CanopyEnv) -> None:
    canopy_env.write_repo(canopy_env.repo_file.read_text() + '[policy]\nstacking = "never"\n')
    assert load(canopy_env.repo, canopy_env.user_file).policy.stacking == "never"  # stricter: used
    canopy_env.write_user(canopy_env.user_file.read_text() + '\n[policy]\nstacking = "auto"\n')
    assert load(canopy_env.repo, canopy_env.user_file).policy.stacking == "auto"  # the user file may loosen


def test_unknown_stacking_value_is_an_error_naming_the_file(canopy_env: CanopyEnv) -> None:
    canopy_env.write_repo(canopy_env.repo_file.read_text() + '[policy]\nstacking = "sometimes"\n')
    with pytest.raises(ConfigError, match=r"canopy\.toml.*policy\.stacking"):
        load(canopy_env.repo, canopy_env.user_file)


def test_missing_user_file_says_run_init(canopy_env: CanopyEnv) -> None:
    canopy_env.user_file.unlink()
    with pytest.raises(ConfigError, match="canopy init"):
        load(canopy_env.repo, canopy_env.user_file)


def test_repository_file_is_optional_but_required_keys_are_not(canopy_env: CanopyEnv) -> None:
    canopy_env.repo_file.unlink()
    with pytest.raises(ConfigError) as exc:
        load(canopy_env.repo, canopy_env.user_file)
    assert "missing required key tracker.provider" in str(exc.value)
    assert "missing required key tracker.query" in str(exc.value)


@pytest.mark.parametrize(
    ("user_extra", "message"),
    [
        ("[capacity]\nmax_workers = true\n", r"capacity\.max_workers: Input should be a valid integer"),
        ("[capacity]\nmax_workers = '2'\n", r"capacity\.max_workers: Input should be a valid integer"),
        ("[capacity]\nmax_workers = -1\n", "greater than or equal to 0"),
        ("[runtime]\nworker_timeout_minutes = 0\n", "greater than or equal to 1"),
        ("[trust]\nauthorized_repliers = [1]\n", r"trust\.authorized_repliers\[0\]: Input should be a valid string"),
        ("[trust]\nauthorized_repliers = ['  ']\n", "must not be empty"),
        ("[trust]\nbranch_prefix = 'agent'\n", "end in '/'"),
        ("[trust]\nbranch_prefix = '-c/'\n", "end in '/'"),
        ("[trust]\nbranch_prefix = 'a/../'\n", "end in '/'"),
        ("[trust]\nbranch_prefix = 'a b/'\n", "end in '/'"),
        ("[trust]\nbranch_prefix = 'agent//'\n", "end in '/'"),
        ("[trust]\nbranch_prefix = '/'\n", "end in '/'"),
        ("[trust]\ncomment_prefix = ''\n", "set trust.comment_prefix, trust.comment_suffix, or both"),
        ("[trust]\ncomment_prefix = '`CANOPY`'\n", "no backtick"),
        ("[trust]\ncomment_prefix = '>'\n", "with a letter or digit"),
        ("[trust]\ncomment_prefix = 'CANOPY: '\n", "no surrounding spaces"),
        ('[trust]\ncomment_suffix = "by\\ncanopy"\n', "one line"),
        (f"[trust]\ncomment_suffix = '{'x' * 81}'\n", "at most 80 characters"),
        ("[runtime]\npr_skill = 'Acme-PR'\n", "a skill name of at most 64"),
        ("[runtime]\npr_skill = 'acme--pr'\n", "a skill name of at most 64"),
        ("[runtime]\npr_skill = '-acme'\n", "a skill name of at most 64"),
        (f"[runtime]\npr_skill = '{'a' * 65}'\n", "a skill name of at most 64"),
        ("[notify]\ncmd = 3\n", "Input should be a valid string"),
    ],
)
def test_invalid_values(canopy_env: CanopyEnv, user_extra: str, message: str) -> None:
    header, line = user_extra.rstrip("\n").split("\n", 1)
    text = canopy_env.user_file.read_text()
    # Add the key to its table, creating the table if the file has none; TOML forbids repeating a header.
    text = text.replace(header, f"{header}\n{line}", 1) if header in text else f"{text}\n{header}\n{line}\n"
    canopy_env.write_user(text)
    with pytest.raises(ConfigError, match=message):
        load(canopy_env.repo, canopy_env.user_file)


def test_labels_must_not_be_empty(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace('["agent-ready-tester"]', "[]"))
    with pytest.raises(ConfigError, match="at least 1 item"):
        load(canopy_env.repo, canopy_env.user_file)


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("canopy-overseer", r"runtime\.overseer_cmd: Value error, must contain \{prompt\} exactly once"),
        ("canopy-overseer {prompt} --copy {prompt}", r"must contain \{prompt\} exactly once"),
        ("{prompt}{prompt}", r"must contain \{prompt\} exactly once"),
        ('canopy-overseer "{prompt}', "No closing quotation"),
    ],
)
def test_command_template_is_checked(canopy_env: CanopyEnv, replacement: str, message: str) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace("canopy-overseer {prompt}", replacement))
    with pytest.raises(ConfigError, match=message):
        load(canopy_env.repo, canopy_env.user_file)


def test_render_command_keeps_the_prompt_in_one_argument() -> None:
    prompt = "it's a `prompt` with $HOME; rm -rf / && echo {prompt} {definitions_dir}"
    argv = render_command("opencode run --agent 'canopy overseer' {prompt}", prompt, Path("/defs"))
    assert argv == ["opencode", "run", "--agent", "canopy overseer", prompt]


def test_render_command_fills_in_the_definitions_dir() -> None:
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker {prompt}"
    argv = render_command(template, "do {definitions_dir}", Path("/state/runtime/abc"))
    assert argv[:2] == ["env", "OPENCODE_CONFIG_DIR=/state/runtime/abc"]
    assert argv[-1] == "do {definitions_dir}"


@pytest.mark.parametrize("key", ["overseer_cmd", "worker_cmd"])
def test_an_agent_template_without_the_definitions_dir_prints_its_replacement(canopy_env: CanopyEnv, key: str) -> None:
    old = f"opencode run --agent canopy-{key.removesuffix('_cmd')} {{prompt}}"
    text = re.sub(rf"^{key} = .*$", f"{key} = '{old}'", canopy_env.user_file.read_text(), flags=re.MULTILINE)
    canopy_env.write_user(text)
    with pytest.raises(ConfigError) as e:
        load(canopy_env.repo, canopy_env.user_file)
    assert f"runtime.{key}: Value error, must contain {{definitions_dir}}" in str(e.value)
    assert f"'env OPENCODE_CONFIG_DIR={{definitions_dir}} {old}'" in str(e.value)


def test_the_default_templates_name_the_definitions_dir(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(
        "\n".join(line for line in canopy_env.user_file.read_text().splitlines() if "_cmd" not in line)
    )
    runtime = load(canopy_env.repo, canopy_env.user_file).runtime
    for template in (runtime.overseer_cmd, runtime.worker_cmd):
        assert template.startswith("env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-")


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


def test_empty_prompt_overrides_means_the_default(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + 'prompt_overrides = ""\n')
    cfg = load(canopy_env.repo, canopy_env.user_file)
    assert cfg.paths.prompt_overrides == canopy_env.user_file.parent / "prompts"


@pytest.mark.parametrize(
    ("key", "value"),
    [("prompt_overrides", "prompts"), ("prompt_overrides", "."), ("state_dir", ""), ("state_dir", "state")],
)
def test_user_paths_must_not_resolve_against_the_repository(canopy_env: CanopyEnv, key: str, value: str) -> None:
    # The working directory is the repository; a relative path would let it supply prompts or state (T7).
    text = canopy_env.user_file.read_text()
    text = re.sub(rf"^{key} = .*$", "", text, flags=re.MULTILINE) + f'{key} = "{value}"\n'
    canopy_env.write_user(text)
    with pytest.raises(ConfigError, match=rf"paths\.{key}: Value error, must be an absolute path or start with ~"):
        load(canopy_env.repo, canopy_env.user_file)


def test_user_paths_expand_the_home_directory(canopy_env: CanopyEnv) -> None:
    text = re.sub(
        r"^state_dir = .*$", 'state_dir = "~/somewhere"', canopy_env.user_file.read_text(), flags=re.MULTILINE
    )
    canopy_env.write_user(text + 'prompt_overrides = "~/my-prompts"\n')
    paths = load(canopy_env.repo, canopy_env.user_file).paths
    assert paths.state_dir == canopy_env.home / "somewhere"
    assert paths.prompt_overrides == canopy_env.home / "my-prompts"
