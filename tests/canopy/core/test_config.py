import contextlib
import os
import re
import tomllib
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, workspace
from canopy.core.config import ConfigError, load, render_command
from canopy.core.context import Context
from canopy.loop import reread
from tests.conftest import HERMETIC_GIT, SHARED_TOML, CanopyEnv, git, user_toml

EXAMPLES = Path(__file__).parents[3] / "examples"


def test_defaults_fill_in_everything_else(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert cfg.tracker.provider == "jira"
    assert cfg.tracker.labels == ("agent-ready-tester",)
    assert cfg.tracker.needs_human_label == "needs-human"
    assert (cfg.policy.max_resume_attempts, cfg.policy.ci_cooldown_minutes) == (6, 30)
    assert cfg.trust.branch_prefix == "agent/"
    assert cfg.trust.authorized_repliers == ()
    assert cfg.trust.trusted_reviewers == ()
    assert cfg.trust.comment_prefix == "CANOPY:"
    assert cfg.trust.comment_suffix == ""
    assert cfg.trust.commit_trailer is True
    assert cfg.trust.commit_trailer_name == "canopy worker"
    assert cfg.trust.commit_trailer_email == "noreply@canopy.invalid"
    assert cfg.capacity.max_workers == 2
    assert cfg.loop.interval_minutes == 15
    assert cfg.paths.prompt_overrides == canopy_env.user_file.parent / "prompts"


def test_trusted_reviewers_take_logins_and_canopys_reviewer(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user('\n[trust]\ntrusted_reviewers = ["octocat", "canopy:review", "ci[bot]"]\n')
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert cfg.trust.trusted_reviewers == ("octocat", "canopy:review", "ci[bot]")


def test_user_file_wins_over_the_workspace_file_for_shared_keys(canopy_env: CanopyEnv) -> None:
    canopy_env.write_shared('[tracker]\nprovider = "jira"\nquery = "project = A"\n[trust]\nbranch_prefix = "bot/"\n')
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("[runtime]", '[trust]\nbranch_prefix = "mine/"\n\n[runtime]', 1)
    )
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert cfg.tracker.query == "project = A"
    assert cfg.trust.branch_prefix == "mine/"


def test_needs_human_label_is_set_by_the_workspace_and_overridden_by_the_user(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared('needs_human_label = "blocked-on-team"\n')
    assert load(canopy_env.root, canopy_env.user_file).tracker.needs_human_label == "blocked-on-team"
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("[tracker]\n", '[tracker]\nneeds_human_label = "ask-me"\n', 1)
    )
    assert load(canopy_env.root, canopy_env.user_file).tracker.needs_human_label == "ask-me"


@pytest.mark.parametrize(
    "section_key",
    [
        ("tracker", 'labels = ["x"]'),
        ("tracker", "query_every_minutes = 5"),
        ("trust", 'authorized_repliers = ["mallory"]'),
        ("trust", 'trusted_reviewers = ["review-bot[bot]"]'),
        ("trust", 'comment_prefix = "Please"'),
        ("trust", "commit_trailer = false"),
        ("trust", 'commit_trailer_name = "Alice Example"'),
        ("trust", 'commit_trailer_email = "alice@example.com"'),
        ("trust", "rebase = true"),
        ("capacity", "max_workers = 99"),
        ("loop", "interval_minutes = 1"),
        ("loop", "idle_max_minutes = 1"),
        ("loop", "min_gap_minutes = 1"),
        ("loop", "min_free_disk_mib = 0"),
        ("runtime", "overseer_cmd = 'sh -c evil {prompt}'"),
        ("runtime", "pr_skill = 'evil-pr'"),
        ("notify", "cmd = 'curl evil'"),
        ("paths", "worktree_include = '/tmp/x'"),
        ("paths", "worker_instructions = '/tmp/x'"),
        ("paths", "overseer_instructions = '/tmp/x'"),
    ],
)
def test_the_workspace_file_may_not_set_user_only_keys(canopy_env: CanopyEnv, section_key: tuple[str, str]) -> None:
    section, line = section_key
    extra = f"\n[{section}]\n{line}\n" if section != "tracker" else f"{line}\n"
    canopy_env.append_shared(extra)
    with pytest.raises(ConfigError, match="is private"):
        load(canopy_env.root, canopy_env.user_file)


def test_a_removed_key_says_what_to_do(canopy_env: CanopyEnv) -> None:
    """`paths.state_dir` was in the example user config; a copy of it must say to delete the key (D016)."""
    canopy_env.append_user('state_dir = "~/.canopy"\n')
    with pytest.raises(ConfigError, match=r"paths\.state_dir was removed: delete it; state is always in the workspace"):
        load(canopy_env.root, canopy_env.user_file)


def test_a_removed_pr_label_says_to_delete_it(canopy_env: CanopyEnv) -> None:
    """`trust.pr_label` was in the example workspace file; a copy of it must say to delete the key."""
    canopy_env.append_shared('[trust]\npr_label = "agent"\n')
    with pytest.raises(ConfigError, match=r"trust\.pr_label was removed: delete it"):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize(
    ("key", "says"),
    [
        (
            "max_fix_ci_attempts = 3",
            r"policy\.max_fix_ci_attempts was removed: delete it; .* raise policy\.max_resume_attempts",
        ),
        (
            "fix_ci_cooldown_minutes = 30",
            r"policy\.fix_ci_cooldown_minutes was removed: rename it policy\.ci_cooldown_minutes",
        ),
    ],
)
@pytest.mark.parametrize("where", ["workspace", "user"])
def test_fix_cis_keys_were_removed_and_say_what_replaced_them(
    canopy_env: CanopyEnv, where: str, key: str, says: str
) -> None:
    """A resume fixes CI now, so its limit counts CI runs, and the cooldown holds a resume for CI alone (DESIGN §8)."""
    if where == "workspace":
        canopy_env.append_shared(f"[policy]\n{key}\n")
    else:
        canopy_env.append_user(f"\n[policy]\n{key}\n")
    with pytest.raises(ConfigError, match=says):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize(
    ("table", "key", "says"),
    [
        ("policy", "max_split_attempts = 1", r"policy\.max_split_attempts was removed: delete it; workers file"),
        ("runtime", "split_cmd = 'opencode run {prompt}'", r"runtime\.split_cmd was removed: delete it; workers file"),
    ],
)
def test_splits_keys_were_removed_and_say_what_replaced_them(
    canopy_env: CanopyEnv, table: str, key: str, says: str
) -> None:
    """Workers file follow-up tickets now, which replaced split runs (M46)."""
    text = canopy_env.user_file.read_text()
    heading = f"\n[{table}]\n"
    canopy_env.write_user(text.replace(heading, f"{heading}{key}\n") if heading in text else f"{text}{heading}{key}\n")
    with pytest.raises(ConfigError, match=says):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize("where", ["workspace", "user"])
def test_unknown_keys_are_errors(canopy_env: CanopyEnv, where: str) -> None:
    if where == "workspace":
        canopy_env.append_shared("jql = 'x'\n")
    else:
        canopy_env.append_user("\n[extras]\nfoo = 1\n")
    with pytest.raises(ConfigError, match="unknown key"):
        load(canopy_env.root, canopy_env.user_file)


def test_workspace_policy_only_tightens(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared("[policy]\nmax_implement_attempts = 9\nci_cooldown_minutes = 5\nmax_resume_attempts = 1\n")
    policy = load(canopy_env.root, canopy_env.user_file).policy
    assert policy.max_implement_attempts == 2  # looser than the default: ignored
    assert policy.ci_cooldown_minutes == 30  # shorter cooldown is looser: ignored
    assert policy.max_resume_attempts == 1  # tighter: used


def test_triage_is_off_by_default_and_only_the_operator_turns_it_on(canopy_env: CanopyEnv) -> None:
    # It loosens the plan gate, so unlike the rest of `[policy]` a shared file may not touch it (TRUST_MODEL T7).
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert (cfg.policy.plan_triage, cfg.policy.trivial, cfg.runtime.plan_triage_timeout_minutes) == ("off", "", 10)
    # The operator need not say what is trivial: the triage's prompt has its own measure.
    canopy_env.append_user('\n[policy]\nplan_triage = "on"\n')
    assert load(canopy_env.root, canopy_env.user_file).policy.plan_triage == "on"
    canopy_env.append_shared('[policy]\ntrivial = "Anything at all."\n')
    with pytest.raises(ConfigError, match=r"policy\.trivial is private"):
        load(canopy_env.root, canopy_env.user_file)


def test_user_policy_may_loosen(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared("[policy]\nmax_resume_attempts = 1\n")
    canopy_env.append_user("\n[policy]\nmax_resume_attempts = 9\n")
    assert load(canopy_env.root, canopy_env.user_file).policy.max_resume_attempts == 9


def test_stacking_defaults_to_auto(canopy_env: CanopyEnv) -> None:
    assert load(canopy_env.root, canopy_env.user_file).policy.stacking == "auto"


def test_the_workspace_may_turn_stacking_off_and_the_user_back_on(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared('[policy]\nstacking = "never"\n')
    assert load(canopy_env.root, canopy_env.user_file).policy.stacking == "never"  # stricter: used
    canopy_env.append_user('\n[policy]\nstacking = "auto"\n')
    assert load(canopy_env.root, canopy_env.user_file).policy.stacking == "auto"  # the user file may loosen


def test_unknown_stacking_value_is_an_error_naming_the_file(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared('[policy]\nstacking = "sometimes"\n')
    with pytest.raises(ConfigError, match=r"canopy-workspace\.toml.*policy\.stacking"):
        load(canopy_env.root, canopy_env.user_file)


def test_missing_user_file_says_run_init(canopy_env: CanopyEnv) -> None:
    canopy_env.user_file.unlink()
    with pytest.raises(ConfigError, match="canopy init"):
        load(canopy_env.root, canopy_env.user_file)


def test_required_keys_name_both_files(canopy_env: CanopyEnv) -> None:
    canopy_env.shared_file.unlink()
    with pytest.raises(ConfigError) as exc:
        load(canopy_env.root, canopy_env.user_file)
    private_file = canopy_env.state_dir / "config.toml"
    files = f"{canopy_env.shared_file}, {private_file}, or {canopy_env.user_file}"
    assert f"missing required key tracker.provider; set it in {files}" in str(exc.value)
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
        ("[trust]\ntrusted_reviewers = ['']\n", "or 'canopy:review'"),
        ("[trust]\ntrusted_reviewers = ['two words']\n", "no spaces"),
        ("[trust]\ntrusted_reviewers = ['`bot`']\n", "no spaces, colon, or backtick"),
        ("[trust]\ntrusted_reviewers = ['canopy:reviewer']\n", "no spaces, colon, or backtick"),
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
        ("[trust]\ncommit_trailer_name = ''\n", "with a letter or digit"),
        ("[trust]\ncommit_trailer_name = 'bot <x@y>'\n", "no backtick or angle bracket"),
        ('[trust]\ncommit_trailer_name = "bot\\nSigned-off-by: x"\n', "one line"),
        ("[trust]\ncommit_trailer_name = ' bot'\n", "no surrounding spaces"),
        ("[trust]\ncommit_trailer_email = ''\n", "one '@'"),
        ("[trust]\ncommit_trailer_email = 'bot'\n", "one '@'"),
        ("[trust]\ncommit_trailer_email = 'a@b@c'\n", "one '@'"),
        ("[trust]\ncommit_trailer_email = 'bot@x.test> y'\n", "no whitespace"),
        (f"[trust]\ncommit_trailer_email = 'a@{'x' * 253}'\n", "at most 254 characters"),
        ("[runtime]\npr_skill = 'Acme-PR'\n", "a skill name of at most 64"),
        ("[runtime]\npr_skill = 'acme--pr'\n", "a skill name of at most 64"),
        ("[runtime]\npr_skill = '-acme'\n", "a skill name of at most 64"),
        (f"[runtime]\npr_skill = '{'a' * 65}'\n", "a skill name of at most 64"),
        ("[notify]\ncmd = 3\n", "Input should be a valid string"),
        ("[loop]\nidle_max_minutes = 0\n", "greater than or equal to 1"),
        ("[loop]\nmin_gap_minutes = 0\n", "greater than or equal to 1"),
        (
            "[loop]\nidle_max_minutes = 14\n",
            r"loop\.idle_max_minutes \(14\) must be at least loop\.interval_minutes \(15\)",
        ),
        (f"[policy]\ntrivial = '{'x' * 2001}'\n", "at most 2000 characters"),
        ('[policy]\nplan_triage = "yes"\n', "Input should be 'off' or 'on'"),
        ("[runtime]\nplan_triage_timeout_minutes = 0\n", "greater than or equal to 1"),
        ("[runtime]\nreview_temperature = -0.1\n", "must be from 0 to 2, or -1 to set none"),
        ("[runtime]\nreview_temperature = 2.5\n", "must be from 0 to 2, or -1 to set none"),
        ("[runtime]\nreview_temperature = true\n", r"runtime\.review_temperature: Input should be a valid number"),
        ("[runtime]\nreview_temperature = '0.1'\n", r"runtime\.review_temperature: Input should be a valid number"),
        ("[runtime]\noverseer_temperature = -0.5\n", "must be from 0 to 2, or -1 to set none"),
        ("[runtime]\nplan_triage_temperature = 3.0\n", "must be from 0 to 2, or -1 to set none"),
    ],
)
def test_invalid_values(canopy_env: CanopyEnv, user_extra: str, message: str) -> None:
    header, line = user_extra.rstrip("\n").split("\n", 1)
    text = canopy_env.user_file.read_text()
    # Add the key to its table, creating the table if the file has none; TOML forbids repeating a header.
    text = text.replace(header, f"{header}\n{line}", 1) if header in text else f"{text}\n{header}\n{line}\n"
    canopy_env.write_user(text)
    with pytest.raises(ConfigError, match=message):
        load(canopy_env.root, canopy_env.user_file)


def test_idle_max_minutes_defaults_to_120_and_may_equal_the_interval(canopy_env: CanopyEnv) -> None:
    base = canopy_env.user_file.read_text()
    assert load(canopy_env.root, canopy_env.user_file).loop.idle_max_minutes == 120
    canopy_env.write_user(base + "\n[loop]\ninterval_minutes = 30\nidle_max_minutes = 30\n")
    assert load(canopy_env.root, canopy_env.user_file).loop.idle_max_minutes == 30
    # Unset, the default under a longer interval is no error: the cap is not above it, so idle pacing is off.
    canopy_env.write_user(base + "\n[loop]\ninterval_minutes = 180\n")
    assert load(canopy_env.root, canopy_env.user_file).loop.idle_max_minutes == 120


def test_labels_must_not_be_empty(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace('["agent-ready-tester"]', "[]"))
    with pytest.raises(ConfigError, match="at least 1 item"):
        load(canopy_env.root, canopy_env.user_file)


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
        load(canopy_env.root, canopy_env.user_file)


def test_ticket_url_is_a_shared_template_with_the_key_once(canopy_env: CanopyEnv) -> None:
    assert load(canopy_env.root, canopy_env.user_file).tracker.ticket_url == ""
    template = "https://acme.atlassian.net/browse/{key}?focusedCommentId=1"
    canopy_env.append_shared(f'ticket_url = "{template}"\n')
    assert load(canopy_env.root, canopy_env.user_file).tracker.ticket_url == template


@pytest.mark.parametrize(
    "template",
    [
        "http://jira.example/browse/{key}",
        "https://jira.example/browse/KEY",
        "https://jira.example/{key}/{key}",
        "https://jira.example/browse/{id}-{key}",
        "https://jira.example/browse/{ key}",
        "javascript:alert(1)//{key}",
        "https://jira.example/browse/ {key}",
        "https://jira.example/" + "a" * 500 + "{key}",
    ],
)
def test_ticket_url_is_refused_unless_a_plain_https_template(canopy_env: CanopyEnv, template: str) -> None:
    canopy_env.append_shared(f'ticket_url = "{template}"\n')
    with pytest.raises(ConfigError, match=r"tracker\.ticket_url: Value error, must be empty, or a plain https://"):
        load(canopy_env.root, canopy_env.user_file)


def test_render_command_keeps_the_prompt_in_one_argument() -> None:
    prompt = "it's a `prompt` with $HOME; rm -rf / && echo {prompt} {definitions_dir}"
    argv = render_command("opencode run --agent 'canopy overseer' {prompt}", prompt, Path("/defs"), "tick 1")
    assert argv == ["opencode", "run", "--agent", "canopy overseer", prompt]


def test_render_command_fills_in_the_definitions_dir() -> None:
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker {prompt}"
    argv = render_command(template, "do {definitions_dir}", Path("/state/runtime/abc"), "tick 1")
    assert argv[:2] == ["env", "OPENCODE_CONFIG_DIR=/state/runtime/abc"]
    assert argv[-1] == "do {definitions_dir}"


def test_render_command_fills_in_the_title_and_nothing_inside_the_prompt() -> None:
    template = "agent run --title={title} {prompt}"
    argv = render_command(template, "do {title}", Path("/defs"), "PROJ-1 implement: {prompt}")
    assert argv == ["agent", "run", "--title=PROJ-1 implement: {prompt}", "do {title}"]


def test_a_worker_template_runs_between_the_prefix_and_the_suffix() -> None:
    runtime = config.Runtime(worker_cmd_prefix="wrap --read {definitions_dir} --", worker_cmd_suffix="--model 'a b'")
    argv = render_command(runtime.worker_template("agent {prompt}"), "do it", Path("/defs"), "PROJ-1 implement")
    assert argv == ["wrap", "--read", "/defs", "--", "agent", "do it", "--model", "a b"]
    assert config.Runtime().worker_template("agent {prompt}") == "agent {prompt}"


@pytest.mark.parametrize("key", ["worker_cmd_prefix", "worker_cmd_suffix"])
@pytest.mark.parametrize(
    ("value", "error"), [("wrap {prompt}", "must not contain {prompt}"), ("wrap 'open", "No closing quotation")]
)
def test_a_worker_prefix_or_suffix_places_no_prompt(canopy_env: CanopyEnv, key: str, value: str, error: str) -> None:
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("\n[runtime]\n", f'\n[runtime]\n{key} = "{value}"\n')
    )
    with pytest.raises(ConfigError, match=re.escape(f"runtime.{key}: Value error, {error}")):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize("key", ["overseer_cmd", "worker_cmd"])
def test_an_agent_template_without_the_definitions_dir_prints_its_replacement(canopy_env: CanopyEnv, key: str) -> None:
    old = f"opencode run --agent canopy-{key.removesuffix('_cmd')} {{prompt}}"
    text = re.sub(rf"^{key} = .*$", f"{key} = '{old}'", canopy_env.user_file.read_text(), flags=re.MULTILINE)
    canopy_env.write_user(text)
    with pytest.raises(ConfigError) as e:
        load(canopy_env.root, canopy_env.user_file)
    assert f"runtime.{key}: Value error, must contain {{definitions_dir}}" in str(e.value)
    assert f"'env OPENCODE_CONFIG_DIR={{definitions_dir}} {old}'" in str(e.value)


def test_the_default_templates_name_the_definitions_dir(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(
        "\n".join(line for line in canopy_env.user_file.read_text().splitlines() if "_cmd" not in line)
    )
    runtime = load(canopy_env.root, canopy_env.user_file).runtime
    for template in (runtime.overseer_cmd, runtime.worker_cmd):
        assert template.startswith("env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-")
    # One word, so even a title that read as an option could not be taken for one (DESIGN §13).
    for template in (
        runtime.overseer_cmd,
        runtime.worker_cmd,
        runtime.private_worker_cmd,
        runtime.plan_cmd,
        runtime.plan_triage_cmd,
        runtime.chore_cmd,
        runtime.review_cmd,
    ):
        assert template.endswith(" --title={title} {prompt}")
        # Events, with the model's reasoning among them, so a transcript shows why a call did what it did (DESIGN §22).
        assert " --format json --thinking " in template


def test_xdg_config_home(tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
        assert config.user_config_path() == tmp_path / "canopy" / "config.toml"
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "", "HOME": str(tmp_path / "home")}):
        assert config.user_config_path() == tmp_path / "home" / ".config" / "canopy" / "config.toml"


def test_examples_are_valid(tmp_path: Path) -> None:
    (tmp_path / config.WORKSPACE_FILE_NAME).write_text((EXAMPLES / config.WORKSPACE_FILE_NAME).read_text())
    assert [r.name for r in workspace.load(tmp_path).repos] == ["api", "web"]
    cfg = load(tmp_path, EXAMPLES / "config.toml")
    with (EXAMPLES / "config.toml").open("rb") as f:
        assert list(cfg.tracker.labels) == tomllib.load(f)["tracker"]["labels"]


def test_empty_prompt_overrides_means_the_default(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user('prompt_overrides = ""\n')
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert cfg.paths.prompt_overrides == canopy_env.user_file.parent / "prompts"


@pytest.mark.parametrize(
    ("key", "value"),
    [("prompt_overrides", "prompts"), ("prompt_overrides", "."), ("worktree_include", "")],
)
def test_user_paths_must_not_resolve_against_the_workspace(canopy_env: CanopyEnv, key: str, value: str) -> None:
    # The working directory is the workspace; a relative path would let a shared one supply prompts (T7).
    text = canopy_env.user_file.read_text()
    text = re.sub(rf"^{key} = .*$", "", text, flags=re.MULTILINE) + f'{key} = "{value}"\n'
    canopy_env.write_user(text)
    with pytest.raises(ConfigError, match=rf"paths\.{key}: Value error, must be an absolute path or start with ~"):
        load(canopy_env.root, canopy_env.user_file)


def test_user_paths_expand_the_home_directory(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user('prompt_overrides = "~/my-prompts"\n')
    paths = load(canopy_env.root, canopy_env.user_file).paths
    assert paths.prompt_overrides == canopy_env.home / "my-prompts"


def test_changed_names_the_keys_whose_values_differ_in_the_schemas_order(canopy_env: CanopyEnv) -> None:
    before = load(canopy_env.root, canopy_env.user_file)
    assert config.changed(before, before) == []
    canopy_env.append_user(
        "\n[serve]\nport = 9000\n\n[capacity]\nmax_workers = 3\n"
        '\n[chores.deps]\nprompt = "~/chores/deps.md"\nevery_minutes = 60\n'
    )
    after = load(canopy_env.root, canopy_env.user_file)
    # A table section is one key, whichever of its tables changed.
    assert config.changed(before, after) == ["capacity.max_workers", "serve.port", "chores"]
    assert config.changed(after, before) == ["capacity.max_workers", "serve.port", "chores"]


def test_the_private_file_wins_over_the_user_file_and_the_workspace_file(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared('\n[trust]\nbranch_prefix = "team/"\n')
    canopy_env.append_user('\n[trust]\nbranch_prefix = "mine/"\n')
    canopy_env.write_private(
        '[tracker]\nlabels = ["agent-ready-acme"]\nquery = "project = MINE"\n\n[trust]\nbranch_prefix = "acme/"\n'
    )
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert cfg.tracker.labels == ("agent-ready-acme",)
    assert cfg.tracker.query == "project = MINE"
    assert cfg.trust.branch_prefix == "acme/"
    assert cfg.tracker.provider == "jira"  # from the workspace file, which nothing overrides
    assert "agent run" in cfg.runtime.worker_cmd  # from the user file, which the private file leaves alone


def test_a_private_key_in_the_workspace_file_names_the_private_file(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared("\n[serve]\nport = 9000\n")
    with pytest.raises(ConfigError) as e:
        load(canopy_env.root, canopy_env.user_file)
    assert str(e.value) == (
        f"{canopy_env.shared_file}: serve.port is private and cannot be set in the workspace file; set it in "
        f"{canopy_env.private_file}, or in {canopy_env.user_file} for every workspace"
    )


def test_retention_defaults_to_the_proposal_and_takes_zero_for_forever(canopy_env: CanopyEnv) -> None:
    assert load(canopy_env.root, canopy_env.user_file).retention == config.Retention(
        run_files_days=30, tick_files_days=7, journal_days=90, log_max_mib=50, log_keep=3, memory_days=30
    )
    canopy_env.append_user("\n[retention]\nrun_files_days = 0\nlog_keep = 0\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert (cfg.retention.run_files_days, cfg.retention.log_keep) == (0, 0)


@pytest.mark.parametrize("value", ["-1", "true", '"30"', "1.5"])
def test_retention_takes_only_non_negative_integers(canopy_env: CanopyEnv, value: str) -> None:
    canopy_env.append_user(f"\n[retention]\njournal_days = {value}\n")
    with pytest.raises(ConfigError, match=r"retention\.journal_days"):
        load(canopy_env.root, canopy_env.user_file)


def test_the_workspace_file_cannot_shorten_retention(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared("\n[retention]\nrun_files_days = 1\n")
    with pytest.raises(ConfigError, match=r"retention\.run_files_days is private"):
        load(canopy_env.root, canopy_env.user_file)


def test_review_replies_and_the_vcs_source_default_to_drafting_and_canopys_own_programs(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert cfg.trust.review_replies == "approve"
    assert cfg.connect.vcs() == config.Source(kind="vcs", cmd="canopy-connect-github", post_cmd="canopy-post-github")
    assert cfg.connect.tracker() is None
    assert list(cfg.connect.named()) == [config.DEFAULT_SOURCE]
    assert (cfg.connect.max_age_minutes, cfg.connect.every_minutes) == (30, 2)


def test_review_replies_and_sources_are_set_in_the_operators_files(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user(
        '\n[trust]\nreview_replies = "post"\n\n[connect.sources.ghe]\nkind = "vcs"\n'
        'cmd = "ghe-read --host ghe.example.com"\ntimeout_minutes = 5\n'
        '\n[connect.sources.issues]\nkind = "tracker"\npost_cmd = "canopy-post-github"\n'
    )
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert cfg.trust.review_replies == "post"
    assert cfg.connect.vcs() == config.Source(kind="vcs", cmd="ghe-read --host ghe.example.com", timeout_minutes=5)
    assert cfg.connect.tracker() == config.Source(kind="tracker", post_cmd="canopy-post-github")
    # A tick runs only a source that reads: `issues` only posts.
    assert list(cfg.connect.named()) == ["ghe"]


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ('[trust]\nreview_replies = "draft"\n', r"trust\.review_replies"),
        ('[connect.sources.a]\nkind = "vcs"\npost_cmd = "post"\n', "a vcs source needs cmd"),
        ('[connect.sources.a]\nkind = "tracker"\n', "set cmd, post_cmd, or both"),
        ('[connect.sources.a]\nkind = "vcs"\ncmd = "read {prompt}"\n', "must not contain {prompt}"),
        ('[connect.sources.a]\nkind = "mail"\ncmd = "read"\n', r"connect\.sources\[a\]\[kind\]"),
        ("[connect]\nmax_age_minutes = 1\nevery_minutes = 2\n", "max_age_minutes must be at least every_minutes"),
        ('[connect.sources.A]\nkind = "vcs"\ncmd = "read"\n', "source name 'A' must match"),
        (
            '[connect.sources.a]\nkind = "vcs"\ncmd = "r"\n[connect.sources.b]\nkind = "vcs"\ncmd = "s"\n',
            "at most one source of each kind",
        ),
    ],
)
def test_review_replies_and_sources_are_checked(canopy_env: CanopyEnv, toml: str, message: str) -> None:
    canopy_env.append_user("\n" + toml)
    with pytest.raises(ConfigError, match=message):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize(
    "toml", ['[trust]\nreview_replies = "post"\n', '[connect.sources.a]\nkind = "vcs"\ncmd = "r"\n']
)
def test_the_workspace_file_cannot_say_how_replies_go_or_what_reads_github(canopy_env: CanopyEnv, toml: str) -> None:
    canopy_env.append_shared("\n" + toml)
    with pytest.raises(ConfigError, match="is private and cannot be set in the workspace file"):
        load(canopy_env.root, canopy_env.user_file)


def test_a_private_file_and_no_user_file_runs(canopy_env: CanopyEnv) -> None:
    canopy_env.user_file.unlink()
    canopy_env.write_private(user_toml())
    assert load(canopy_env.root, canopy_env.user_file).tracker.labels == ("agent-ready-tester",)
    assert main(["status"]) == 0


def test_with_neither_config_file_the_error_names_the_private_file_and_init(canopy_env: CanopyEnv) -> None:
    canopy_env.user_file.unlink()
    with pytest.raises(ConfigError) as e:
        load(canopy_env.root, canopy_env.user_file)
    assert str(e.value) == (
        f"no config at {canopy_env.private_file} or {canopy_env.user_file}; run `canopy init` in the workspace"
    )


def test_a_validation_error_names_the_files_a_private_key_may_come_from(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace("labels = ", "# labels = "))
    with pytest.raises(ConfigError) as e:
        load(canopy_env.root, canopy_env.user_file)
    files = f"{canopy_env.private_file} or {canopy_env.user_file}"
    assert str(e.value) == f"missing required key tracker.labels; set it in {files}"

    canopy_env.write_private('[tracker]\nlabels = ["mine"]\n\n[capacity]\nmax_workers = -1\n')
    with pytest.raises(ConfigError, match=rf"^{re.escape(str(canopy_env.private_file))}: capacity\.max_workers: "):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize("tracked", ["config.toml", "canopy.db"])
def test_a_state_directory_git_tracks_is_refused(canopy_env: CanopyEnv, tracked: str) -> None:
    """A `.canopy/` checked out of a shared workspace repository passes the permission check (D053), not this one."""
    canopy_env.write_private("# the operator's own\n")
    (canopy_env.state_dir / "canopy.db").write_bytes(b"")
    with mock.patch.dict(os.environ, HERMETIC_GIT):
        git("init", "--quiet", cwd=canopy_env.root)
        assert load(canopy_env.root, canopy_env.user_file).tracker.provider == "jira"  # untracked: fine

        git("add", "--force", f".canopy/{tracked}", cwd=canopy_env.root)
        with pytest.raises(ConfigError, match=rf"{re.escape(str(canopy_env.state_dir / tracked))} is tracked by git"):
            load(canopy_env.root, canopy_env.user_file)
        with contextlib.chdir(canopy_env.repo):
            assert main(["status"]) == 2

        git("rm", "--quiet", "--cached", f".canopy/{tracked}", cwd=canopy_env.root)
        assert load(canopy_env.root, canopy_env.user_file).tracker.provider == "jira"


def test_a_repository_git_cannot_read_is_refused(canopy_env: CanopyEnv) -> None:
    (canopy_env.root / ".git").mkdir()  # not a repository git reads: it cannot say what it tracks
    with mock.patch.dict(os.environ, HERMETIC_GIT), pytest.raises(ConfigError, match="git could not list"):
        load(canopy_env.root, canopy_env.user_file)


def test_a_symlinked_private_file_is_refused(canopy_env: CanopyEnv, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.toml"
    elsewhere.write_text('[tracker]\nlabels = ["theirs"]\n')
    canopy_env.private_file.symlink_to(elsewhere)
    with pytest.raises(ConfigError, match="a symlink; canopy reads it only as a regular file of yours"):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize("mode", [0o620, 0o602])
def test_a_private_file_others_can_write_is_refused(canopy_env: CanopyEnv, mode: int) -> None:
    canopy_env.write_private("# mine\n")
    canopy_env.private_file.chmod(mode)
    with pytest.raises(ConfigError, match="is not private to you"):
        load(canopy_env.root, canopy_env.user_file)
    canopy_env.private_file.chmod(0o644)  # others may read it: nothing in it is secret
    assert load(canopy_env.root, canopy_env.user_file).tracker.provider == "jira"


def test_someone_elses_private_file_is_refused(canopy_env: CanopyEnv) -> None:
    canopy_env.write_private("# theirs\n")
    with (
        mock.patch.object(os, "getuid", autospec=True, return_value=os.getuid() + 1),
        pytest.raises(ConfigError, match="is not private to you"),
    ):
        load(canopy_env.root, canopy_env.user_file)


def test_a_private_file_that_is_not_a_regular_file_is_refused(canopy_env: CanopyEnv) -> None:
    canopy_env.private_file.mkdir()
    with pytest.raises(ConfigError, match="is not private to you"):
        load(canopy_env.root, canopy_env.user_file)


def test_a_reload_takes_up_a_change_to_the_private_file(ctx: Context, canopy_env: CanopyEnv) -> None:
    canopy_env.write_private("[loop]\ninterval_minutes = 30\n")
    found = reread.load(ctx)
    assert found.changed == ("loop.interval_minutes",)
    assert found.config.loop.interval_minutes == 30


def test_two_workspaces_each_read_their_own_private_file(canopy_env: CanopyEnv, tmp_path: Path) -> None:
    other = tmp_path / "other"
    (other / ".canopy").mkdir(parents=True, mode=0o700)
    (other / config.WORKSPACE_FILE_NAME).write_text(SHARED_TOML)
    canopy_env.write_private('[tracker]\nlabels = ["acme-queue"]\n\n[serve]\nport = 8801\n')
    (other / ".canopy" / "config.toml").write_text('[tracker]\nlabels = ["other-queue"]\n\n[serve]\nport = 8802\n')

    acme, second = load(canopy_env.root, canopy_env.user_file), load(other, canopy_env.user_file)
    assert (acme.serve.port, acme.tracker.labels) == (8801, ("acme-queue",))
    assert (second.serve.port, second.tracker.labels) == (8802, ("other-queue",))


def test_a_relative_path_in_the_private_file_names_a_file_in_the_state_directory(canopy_env: CanopyEnv) -> None:
    canopy_env.write_private('[paths]\nworker_instructions = "worker-instructions.md"\nprompt_overrides = "~/p"\n')
    paths = load(canopy_env.root, canopy_env.user_file).paths
    assert paths.worker_instructions == canopy_env.state_dir / "worker-instructions.md"
    assert paths.prompt_overrides == canopy_env.home / "p"

    canopy_env.private_file.unlink()
    canopy_env.append_user('worker_instructions = "worker-instructions.md"\n')
    with pytest.raises(ConfigError, match=r"paths\.worker_instructions: Value error, must be an absolute path or"):
        load(canopy_env.root, canopy_env.user_file)
