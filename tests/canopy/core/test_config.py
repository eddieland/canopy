import contextlib
import os
import re
import tomllib
from pathlib import Path
from unittest import mock

import pytest
from canopy_artifacts import tools as store_tools

from canopy.cli.main import main
from canopy.core import config, workspace
from canopy.core.config import ConfigError, PlannerApproval, load, render_command
from canopy.core.context import Context
from canopy.loop import reread
from canopy.runtime.implementation import Version
from tests.conftest import HERMETIC_GIT, SHARED_TOML, TRACKER_SOURCE, TRACKER_TOML, CanopyEnv, git, user_toml

#: A reviewer's command the operator set, without a private server.
REVIEW_CMD = "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-reviewer"

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
        canopy_env.user_file.read_text().replace("[runtime]", '[trust]\nbranch_prefix = "mine/"\n\n[runtime]', 1),
    )
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert cfg.tracker.query == "project = A"
    assert cfg.trust.branch_prefix == "mine/"


def test_needs_human_label_is_set_by_the_workspace_and_overridden_by_the_user(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared('needs_human_label = "blocked-on-team"\n')
    assert load(canopy_env.root, canopy_env.user_file).tracker.needs_human_label == "blocked-on-team"
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("[tracker]\n", '[tracker]\nneeds_human_label = "ask-me"\n', 1),
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
        ("paths", "reviewer_instructions = '/tmp/x'"),
        ("paths", "chore_instructions = '/tmp/x'"),
        # A persona is instructions in every run it reaches, so a shared file neither supplies nor chooses one.
        ("paths", "personas = '/tmp/x'"),
        # Every plan's text is pushed where it points.
        ("paths", "plan_archive = '/tmp/x'"),
        # Turning prompts back on would push the operator's messages to a remote they chose for plans alone.
        ("paths", "plan_archive_prompts = true"),
        # It chooses what is committed in the operator's own clone.
        ("paths", "plan_archive_workspace_dir = false"),
        # A conversation, a private ticket's too, would go to a remote the operator never chose for it.
        ("paths", "plan_archive_conversations = true"),
        # Comments are the operator's words, sent to a remote only they choose.
        ("paths", "plan_archive_comments = true"),
        ("personas", "worker = 'canopy'"),
        ("personas", "planner = 'skeptic'"),
        ("personas", "reviewer = 'lenient'"),
    ],
)
def test_the_workspace_file_may_not_set_user_only_keys(canopy_env: CanopyEnv, section_key: tuple[str, str]) -> None:
    section, line = section_key
    extra = f"\n[{section}]\n{line}\n" if section != "tracker" else f"{line}\n"
    canopy_env.append_shared(extra)
    with pytest.raises(ConfigError, match="is private"):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize("name", ["", "Skeptic", "skeptic.md", "../skeptic", "-x", "a" * 41])
def test_a_persona_is_named_as_its_file_is(canopy_env: CanopyEnv, name: str) -> None:
    canopy_env.append_user(f"\n[personas]\nreviewer = '{name}'\n")
    with pytest.raises(ConfigError, match="must be lowercase words joined by hyphens, at most 40 characters"):
        load(canopy_env.root, canopy_env.user_file)


def test_every_agent_writes_in_canopys_voice_until_the_operator_chooses(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert (cfg.personas.worker, cfg.personas.planner, cfg.personas.reviewer) == ("canopy", "canopy", "canopy")
    assert cfg.paths.personas is None


#: An eval case's keys but `kind` and `lines` (DESIGN §21, Scoring the reviewer).
EVAL_CASE = f'pr = "https://github.com/acme/api/pull/7"\nrepo = "api"\nsha = "{"a" * 40}"\nbase = "{"b" * 40}"\n'


def test_an_eval_case_is_a_pr_at_a_commit_with_the_lines_its_bug_is_on(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user(
        f'\n[[review.eval_cases]]\nname = "retry"\n{EVAL_CASE}kind = "bug"\nlines = ["src/retry.py:42", "a.py:3-9"]\n'
        f'\n[[review.eval_cases]]\nname = "sound"\n{EVAL_CASE}kind = "clean"\n',
    )
    retry, sound = load(canopy_env.root, canopy_env.user_file).review.eval_cases
    assert (retry.name, retry.kind, retry.lines) == ("retry", "bug", ("src/retry.py:42", "a.py:3-9"))
    assert (sound.name, sound.kind, sound.lines) == ("sound", "clean", ())


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        (f'name = "x"\n{EVAL_CASE}kind = "bug"\n', "bug case x needs lines"),
        (f'name = "x"\n{EVAL_CASE}kind = "clean"\nlines = ["a.py:1"]\n', "clean case x has no bug"),
        (f'name = "x"\n{EVAL_CASE}kind = "bug"\nlines = ["a.py"]\n', "must be path:line or path:first-last"),
        (f'name = "x"\n{EVAL_CASE}kind = "bug"\nlines = ["a.py:9-3"]\n', "ends before it starts"),
        (f'name = "X"\n{EVAL_CASE}kind = "clean"\n', "must match"),
        (f'name = "x"\n{EVAL_CASE.replace("a" * 40, "HEAD")}kind = "clean"\n', "must be a full commit"),
        (f'name = "x"\n{EVAL_CASE.replace("https", "http")}kind = "clean"\n', "plain https:// URL"),
    ],
)
def test_an_eval_case_that_cannot_be_scored_is_refused(canopy_env: CanopyEnv, toml: str, message: str) -> None:
    canopy_env.append_user(f"\n[[review.eval_cases]]\n{toml}")
    with pytest.raises(ConfigError, match=message):
        load(canopy_env.root, canopy_env.user_file)


def test_eval_cases_are_named_once_and_only_in_private_config(canopy_env: CanopyEnv) -> None:
    case = f'\n[[review.eval_cases]]\nname = "x"\n{EVAL_CASE}kind = "clean"\n'
    canopy_env.append_user(case * 2)
    with pytest.raises(ConfigError, match="names x more than once"):
        load(canopy_env.root, canopy_env.user_file)
    canopy_env.write_user(user_toml())
    # A case may name a private repository's PR, and authorizes a review of it (TRUST_MODEL T7).
    canopy_env.append_shared(case)
    with pytest.raises(ConfigError, match=r"review\.eval_cases is private and cannot be set in the workspace file"):
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
    canopy_env: CanopyEnv,
    where: str,
    key: str,
    says: str,
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
    canopy_env: CanopyEnv,
    table: str,
    key: str,
    says: str,
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


@pytest.mark.parametrize(
    ("table", "key"),
    [
        ("policy", 'plan_triage = "on"'),
        ("policy", 'trivial = "A typo."'),
        ("runtime", "plan_triage_cmd = 'opencode run {prompt}'"),
        ("runtime", "plan_triage_temperature = 0.1"),
        ("runtime", "plan_triage_timeout_minutes = 10"),
    ],
)
def test_triages_keys_were_removed_and_say_how_to_skip_a_plan(canopy_env: CanopyEnv, table: str, key: str) -> None:
    """Triage before a plan waived too few plans to pay for itself, so trivial work is planned (M55)."""
    text = canopy_env.user_file.read_text()
    heading = f"\n[{table}]\n"
    canopy_env.write_user(text.replace(heading, f"{heading}{key}\n") if heading in text else f"{text}{heading}{key}\n")
    name = key.split(" ", 1)[0]
    with pytest.raises(ConfigError, match=rf"{table}\.{name} was removed: delete it; .* canopy plan KEY --skip"):
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
        ("[runtime]\nreview_temperature = -0.1\n", "must be from 0 to 2, or -1 to set none"),
        ("[runtime]\nreview_temperature = 2.5\n", "must be from 0 to 2, or -1 to set none"),
        ("[runtime]\nreview_temperature = true\n", r"runtime\.review_temperature: Input should be a valid number"),
        ("[runtime]\nreview_temperature = '0.1'\n", r"runtime\.review_temperature: Input should be a valid number"),
        ("[runtime]\noverseer_temperature = -0.5\n", "must be from 0 to 2, or -1 to set none"),
        ("[runtime]\nsandbox_repos = ['API']\n", "repository name 'API' must match"),
        (
            "[runtime]\nsandbox_repos = ['api']\nworker_cmd_prefix = 'canopy-sandbox worker --'\n",
            r"runtime\.worker_cmd_prefix starts with canopy-sandbox, and runtime\.sandbox_repos has canopy add it",
        ),
        (
            "[runtime]\nsandbox_repos = ['api']\nsetup_cmd = '/opt/bin/canopy-sandbox setup -- make'\n",
            r"runtime\.setup_cmd starts with canopy-sandbox",
        ),
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


@pytest.mark.parametrize("wrapper", ["canopy-sandbox", "/opt/bin/canopy-sandbox"])
def test_an_overseer_in_the_sandbox_is_taken_since_the_tick_starts_its_runs(
    canopy_env: CanopyEnv,
    wrapper: str,
) -> None:
    """No run the overseer asks for is its descendant (DESIGN §40), so its command may start in the wrapper."""
    overseer_cmd = f"{wrapper} overseer --read {{definitions_dir}} -- env OPENCODE_CONFIG_DIR={{definitions_dir}} agent"
    canopy_env.configure(canopy_env.user_file, {"runtime": {"overseer_cmd": overseer_cmd}})

    assert load(canopy_env.root, canopy_env.user_file).runtime.overseer_cmd == overseer_cmd


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
        (
            "canopy-overseer {prompt} --copy {prompt}",
            r"runtime\.overseer_cmd: Value error, must contain \{prompt\} at most once",
        ),
        ("{prompt}{prompt}", r"must contain \{prompt\} at most once"),
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
    rendered = render_command("opencode run --agent 'canopy overseer' {prompt}", prompt, Path("/defs"), "tick 1")
    assert rendered == config.Rendered(["opencode", "run", "--agent", "canopy overseer", prompt], None)


def test_render_command_writes_the_prompt_on_stdin_when_the_template_places_none() -> None:
    # Past Linux's 128 KiB for one argument, as a state block with many tickets' observations is.
    prompt = "x {title} {prompt}" * 20_000
    rendered = render_command("agent run --title={title}", prompt, Path("/defs"), "tick 1")
    assert rendered == config.Rendered(["agent", "run", "--title=tick 1"], prompt)


def test_render_command_fills_in_the_definitions_dir() -> None:
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker {prompt}"
    argv = render_command(template, "do {definitions_dir}", Path("/state/runtime/abc"), "tick 1").argv
    assert argv[:2] == ["env", "OPENCODE_CONFIG_DIR=/state/runtime/abc"]
    assert argv[-1] == "do {definitions_dir}"


def test_render_command_fills_in_the_title_and_nothing_inside_the_prompt() -> None:
    template = "agent run --title={title} {prompt}"
    argv = render_command(template, "do {title}", Path("/defs"), "PROJ-1 implement: {prompt}").argv
    assert argv == ["agent", "run", "--title=PROJ-1 implement: {prompt}", "do {title}"]


def test_a_worker_template_runs_between_the_prefix_and_the_suffix() -> None:
    runtime = config.Runtime(
        worker_cmd_prefix="wrap --read {definitions_dir} --",
        worker_cmd_suffix="--log-level 'a b'",
    )
    argv = render_command(runtime.worker_template("agent {prompt}"), "do it", Path("/defs"), "PROJ-1 implement").argv
    assert argv == ["wrap", "--read", "/defs", "--", "agent", "do it", "--log-level", "a b"]
    assert config.Runtime().worker_template("agent {prompt}") == "agent {prompt}"


@pytest.mark.parametrize("key", ["worker_cmd_prefix", "worker_cmd_suffix"])
@pytest.mark.parametrize(
    ("value", "error"),
    [("wrap {prompt}", "must not contain {prompt}"), ("wrap 'open", "No closing quotation")],
)
def test_a_worker_prefix_or_suffix_places_no_prompt(canopy_env: CanopyEnv, key: str, value: str, error: str) -> None:
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("\n[runtime]\n", f'\n[runtime]\n{key} = "{value}"\n'),
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
        "\n".join(line for line in canopy_env.user_file.read_text().splitlines() if "_cmd" not in line),
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
        runtime.chore_cmd,
        runtime.review_cmd,
    ):
        # No `{prompt}`: canopy writes the prompt on stdin, past any limit on one argument (D023).
        assert config.PROMPT not in template
        assert template.endswith(" --title={title}")
        # Events, with the model's reasoning among them, so a transcript shows why a call did what it did (DESIGN §22).
        assert " --format json --thinking " in template


def test_runtime_version_2_runs_opencode_2_and_its_default_templates(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(
        "\n".join(line for line in canopy_env.user_file.read_text().splitlines() if "_cmd" not in line),
    )
    assert load(canopy_env.root, canopy_env.user_file).runtime.version == Version.ONE
    canopy_env.configure(
        canopy_env.user_file,
        {"runtime": {"version": 2, "review_cmd": REVIEW_CMD}},
    )
    runtime = load(canopy_env.root, canopy_env.user_file).runtime
    assert runtime.version == Version.TWO
    # Each on a private server of its own, but the one the operator set, which stays as they wrote it.
    for template in (runtime.overseer_cmd, runtime.worker_cmd, runtime.private_worker_cmd, runtime.plan_cmd):
        assert template.startswith(
            "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --standalone --agent canopy-",
        )
    assert runtime.chore_cmd.startswith("env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --standalone ")
    assert runtime.review_cmd == REVIEW_CMD


@pytest.mark.parametrize("version", [3, "2", 0, True, 2.0])
def test_a_runtime_version_canopy_does_not_run_is_refused(canopy_env: CanopyEnv, version: object) -> None:
    canopy_env.configure(canopy_env.user_file, {"runtime": {"version": version}})
    with pytest.raises(ConfigError, match=r"runtime\.version"):
        load(canopy_env.root, canopy_env.user_file)


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
        '\n[chores.deps]\nprompt = "~/chores/deps.md"\nevery_minutes = 60\n',
    )
    after = load(canopy_env.root, canopy_env.user_file)
    # A table section is one key, whichever of its tables changed.
    assert config.changed(before, after) == ["capacity.max_workers", "serve.port", "chores"]
    assert config.changed(after, before) == ["capacity.max_workers", "serve.port", "chores"]


def test_the_private_file_wins_over_the_user_file_and_the_workspace_file(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared('\n[trust]\nbranch_prefix = "team/"\n')
    canopy_env.append_user('\n[trust]\nbranch_prefix = "mine/"\n')
    canopy_env.write_private(
        '[tracker]\nlabels = ["agent-ready-acme"]\nquery = "project = MINE"\n\n[trust]\nbranch_prefix = "acme/"\n',
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
        run_files_days=30,
        tick_files_days=7,
        journal_days=90,
        log_max_mib=50,
        log_keep=3,
        memory_days=30,
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
    assert list(cfg.connect.named()) == [TRACKER_SOURCE, config.DEFAULT_SOURCE]
    assert (cfg.connect.max_age_minutes, cfg.connect.every_minutes) == (30, 2)


def test_review_replies_and_sources_are_set_in_the_operators_files(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace(TRACKER_TOML, ""))
    canopy_env.append_user(
        '\n[trust]\nreview_replies = "post"\n\n[connect.sources.ghe]\nkind = "vcs"\n'
        'cmd = "ghe-read --host ghe.example.com"\ntimeout_minutes = 5\n'
        '\n[connect.sources.issues]\nkind = "tracker"\ncmd = "canopy-connect-github --repo acme/api"\n'
        'post_cmd = "canopy-post-github"\n',
    )
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert cfg.trust.review_replies == "post"
    assert cfg.connect.vcs() == config.Source(kind="vcs", cmd="ghe-read --host ghe.example.com", timeout_minutes=5)
    assert cfg.connect.tracker() == config.Source(
        kind="tracker",
        cmd="canopy-connect-github --repo acme/api",
        post_cmd="canopy-post-github",
    )
    assert list(cfg.connect.named()) == ["issues", "ghe"]


@pytest.mark.parametrize(
    "toml",
    [
        pytest.param("", id="none"),
        pytest.param('\n[connect.sources.issues]\nkind = "tracker"\npost_cmd = "post"\n', id="posts only"),
        pytest.param('\n[connect.sources.ghe]\nkind = "vcs"\ncmd = "ghe-read"\n', id="a vcs source alone"),
    ],
)
def test_a_workspace_with_no_tracker_source_that_reads_is_refused(canopy_env: CanopyEnv, toml: str) -> None:
    """Config requires a tracker source with a cmd, since canopy reads no ticket any other way (DESIGN §30, §39)."""
    canopy_env.write_user(canopy_env.user_file.read_text().replace(TRACKER_TOML, "") + toml)
    with pytest.raises(ConfigError) as e:
        load(canopy_env.root, canopy_env.user_file)
    assert str(e.value) == f"connect: Value error, {config.TRACKER_REQUIRED}"
    assert main(["status"]) == 2


def test_a_private_files_sources_replace_the_user_files_so_they_name_the_tracker_source_too(
    canopy_env: CanopyEnv,
) -> None:
    """`connect.sources` is one key: the private file's table replaces the user file's whole, its tracker source too."""
    canopy_env.write_private('[connect.sources.ghe]\nkind = "vcs"\ncmd = "ghe-read"\n')
    with pytest.raises(ConfigError, match="a tracker source is required"):
        load(canopy_env.root, canopy_env.user_file)
    canopy_env.write_private(
        '[connect.sources.ghe]\nkind = "vcs"\ncmd = "ghe-read"\n'
        '\n[connect.sources.jira]\nkind = "tracker"\ncmd = "canopy-connect-jira --site acme.atlassian.net"\n',
    )
    assert list(load(canopy_env.root, canopy_env.user_file).connect.named()) == ["jira", "ghe"]


@pytest.mark.parametrize(
    ("value", "level"),
    [
        # The key was a switch first: an operator's file that set it reads as it did.
        (True, PlannerApproval.STRICT),
        (False, PlannerApproval.OFF),
        ("strict", PlannerApproval.STRICT),
        ("normal", PlannerApproval.NORMAL),
        ("lenient", PlannerApproval.LENIENT),
        ("off", PlannerApproval.OFF),
    ],
)
def test_planner_may_approve_is_a_level_and_reads_its_old_switch(
    canopy_env: CanopyEnv,
    value: object,
    level: PlannerApproval,
) -> None:
    assert load(canopy_env.root, canopy_env.user_file).policy.planner_may_approve is PlannerApproval.OFF
    canopy_env.configure(canopy_env.private_file, {"policy": {"planner_may_approve": value}})
    policy = load(canopy_env.root, canopy_env.user_file).policy
    assert policy.planner_may_approve is level
    assert policy.planner_approves() is (level is not PlannerApproval.OFF)


@pytest.mark.parametrize("value", ["sometimes", "true", 1, ""])
def test_a_level_planner_may_approve_does_not_have_is_refused(canopy_env: CanopyEnv, value: object) -> None:
    canopy_env.configure(canopy_env.private_file, {"policy": {"planner_may_approve": value}})
    with pytest.raises(ConfigError, match=r"policy\.planner_may_approve"):
        load(canopy_env.root, canopy_env.user_file)


def test_a_tick_runs_the_tracker_then_the_vcs_then_the_artifacts_then_the_slack_source(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace(TRACKER_TOML, ""))
    canopy_env.append_user(
        '\n[connect.sources.a-slack]\nkind = "slack"\ncmd = "canopy-connect-slack --channel C1"\noperators = ["U1A"]\n'
        '\n[connect.sources.a-feed]\nkind = "artifacts"\ncmd = "canopy-artifacts feed --store /s"\n'
        '\n[connect.sources.b-jira]\nkind = "tracker"\ncmd = "canopy-connect-jira --site acme.atlassian.net"\n'
        'operators = ["557058:f58131cb"]\n',
    )
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert [(name, s.kind) for name, s in cfg.connect.named().items()] == [
        ("b-jira", "tracker"),
        ("github", "vcs"),
        ("a-feed", "artifacts"),
        ("a-slack", "slack"),
    ]
    assert cfg.connect.sources["a-slack"].operators == ("U1A",)
    # A tracker source's are account ids, whatever the tracker's shape: no Slack id is asked of them.
    assert cfg.connect.sources["b-jira"].operators == ("557058:f58131cb",)


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
        (
            '[connect.sources.a]\nkind = "artifacts"\ncmd = "r"\n[connect.sources.b]\nkind = "artifacts"\ncmd = "s"\n',
            "at most one source of each kind",
        ),
        ('[connect.sources.a]\nkind = "artifacts"\npost_cmd = "post"\n', "an artifacts source needs cmd"),
        ('[connect.sources.a]\nkind = "artifacts"\ncmd = "r"\npost_cmd = "p"\n', "takes no post_cmd"),
        ('[connect.sources.a]\nkind = "slack"\ncmd = "r"\n', "a slack source needs cmd and operators"),
        ('[connect.sources.a]\nkind = "slack"\ncmd = "r"\noperators = ["U1A"]\npost_cmd = "p"\n', "takes no post_cmd"),
        ('[connect.sources.a]\nkind = "slack"\ncmd = "r"\noperators = ["@me"]\n', "is not a Slack user id"),
        (
            '[connect.sources.a]\nkind = "vcs"\ncmd = "r"\noperators = ["U1A"]\n',
            "operators is a slack or tracker source's",
        ),
    ],
)
def test_review_replies_and_sources_are_checked(canopy_env: CanopyEnv, toml: str, message: str) -> None:
    canopy_env.append_user("\n" + toml)
    with pytest.raises(ConfigError, match=message):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize(
    "toml",
    ['[trust]\nreview_replies = "post"\n', '[connect.sources.a]\nkind = "vcs"\ncmd = "r"\n'],
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


def test_artifacts_are_off_until_the_operator_names_a_store(canopy_env: CanopyEnv) -> None:
    artifacts = load(canopy_env.root, canopy_env.user_file).artifacts
    assert (artifacts.mcp_server, artifacts.publish_roles, artifacts.authorized_authors) == ("", (), ())
    assert artifacts.publishing() is None


def test_artifacts_name_a_store_and_the_workers_that_publish_to_it(canopy_env: CanopyEnv) -> None:
    canopy_env.write_private(
        '[artifacts]\nmcp_server = "louvre"\nnamespace = "canopy/operator"\n'
        'authorized_authors = ["u_ana", "u_raj"]\npublish_roles = ["worker"]\n',
    )
    artifacts = load(canopy_env.root, canopy_env.user_file).artifacts
    assert (artifacts.namespace, artifacts.authorized_authors) == ("canopy/operator", ("u_ana", "u_raj"))
    publishing = artifacts.publishing()
    assert publishing is not None
    assert (publishing.server, publishing.agents) == ("louvre", {"canopy-worker"})
    # A worker publishes and answers threads; the feed is for the source that reads comments back (DESIGN §38).
    assert "artifact_publish" in publishing.tools
    assert "comment_feed" not in publishing.tools


def test_a_store_no_role_publishes_to_is_one_no_agent_publishes_to(canopy_env: CanopyEnv) -> None:
    canopy_env.write_private('[artifacts]\nmcp_server = "louvre"\n')
    publishing = load(canopy_env.root, canopy_env.user_file).artifacts.publishing()
    assert publishing is not None
    assert publishing.agents == frozenset()


@pytest.mark.parametrize(
    "line",
    ['mcp_server = "louvre"', 'publish_roles = ["worker"]', 'authorized_authors = ["u_ana"]', 'namespace = "x"'],
)
def test_the_workspace_file_cannot_choose_who_publishes_or_whose_comments_count(
    canopy_env: CanopyEnv,
    line: str,
) -> None:
    canopy_env.append_shared(f"\n[artifacts]\n{line}\n")
    with pytest.raises(ConfigError, match=r"artifacts\.\w+ is private and cannot be set in the workspace file"):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ('mcp_server = "louvre"\npublish_roles = ["planner"]', "'planner' cannot publish: the planner writes one file"),
        ('mcp_server = "louvre"\npublish_roles = ["worker-private"]', "a private ticket's worker never publishes"),
        ('mcp_server = "louvre"\npublish_roles = ["reviewer"]', "'reviewer' is not an agent that may publish"),
        ('mcp_server = "louvre"\npublish_roles = ["implement"]', "'implement' is not an agent that may publish"),
        ('mcp_server = "lou vre"', "must match"),
        ('authorized_authors = [""]', "artifacts.authorized_authors"),
    ],
)
def test_artifacts_are_checked(canopy_env: CanopyEnv, toml: str, message: str) -> None:
    canopy_env.write_private(f"[artifacts]\n{toml}\n")
    with pytest.raises(ConfigError, match=re.escape(message)):
        load(canopy_env.root, canopy_env.user_file)


def test_a_publishing_worker_gets_every_tool_of_the_stores_contract_but_its_feed() -> None:
    assert sorted(config.ARTIFACT_TOOLS) == sorted({t.name for t in store_tools.TOOLS} - {"comment_feed"})
