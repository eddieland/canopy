"""Property tests for the validators that stand between agent-written text and paths, argv, and prompts."""

import re
import string
from collections.abc import Callable
from pathlib import Path

import click
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from canopy.cli.params import (
    CURSOR_VALUE_RE,
    KEY_RE,
    MAX_TEXT,
    REASON,
    REASON_RE,
    SLUG,
    TICKET_KEY,
    CursorType,
    TextType,
    valid_key,
)
from canopy.core import bash_allows, config
from canopy.infra.procs import SubprocessRunner
from canopy.runs import dispatch
from canopy.runtime.definitions import BASH_ALLOW_RE
from canopy.setup import init

# Characters that mean something to a shell, a path, a glob, or a git ref.
UNSAFE = set(" \t\n\r\x0b\x0c/\\;$`&|<>()'\"*?#~!{}[]=:^@,.%+")
fixtures = [HealthCheck.function_scoped_fixture]


def near(pattern: re.Pattern[str]) -> st.SearchStrategy[str]:
    """Strings that match `pattern`, with a little junk around them. Random text almost never lands one character away
    from a valid value, which is where anchoring bugs live (a trailing newline once passed as part of a key)."""
    junk = st.text(max_size=3) | st.sampled_from(["\n", "\r\n", " ", "/", ";"])
    return st.builds(_concat, junk | st.just(""), st.from_regex(pattern, fullmatch=True), junk)


def _concat(before: str, value: str, after: str) -> str:
    return before + value + after


@given(st.text() | near(KEY_RE))
def test_accepted_keys_are_inert(value: str) -> None:
    if valid_key(value):
        assert value
        assert not value.startswith("-")
        assert not set(value) & UNSAFE
        assert value.isascii()


@given(st.from_regex(KEY_RE, fullmatch=True))
def test_every_key_the_pattern_describes_is_accepted(value: str) -> None:
    assert valid_key(value)


def _converts(param: click.ParamType[object, object], value: str) -> bool:
    try:
        param.convert(value, None, None)
    except click.BadParameter:
        return False
    return True


def accepts_ticket_key(value: str) -> bool:
    return _converts(TICKET_KEY, value)


def accepts_reason(value: str) -> bool:
    return _converts(REASON, value)


def accepts_cursor_id(value: str) -> bool:
    return _converts(CursorType(), f"comment={value}")


def accepts_slug(value: str) -> bool:
    return _converts(SLUG, value)


def accepts_branch_prefix(value: str) -> bool:
    try:
        config.Trust(branch_prefix=value)
    except ValidationError:
        return False
    return True


# Each validator the CLI and init actually call, with the pattern it is meant to enforce on the whole string.
VALIDATORS = [
    pytest.param(KEY_RE, accepts_ticket_key, id="ticket-key-type"),
    pytest.param(KEY_RE, valid_key, id="decide-key"),
    pytest.param(REASON_RE, accepts_reason, id="reason-type"),
    pytest.param(CURSOR_VALUE_RE, accepts_cursor_id, id="cursor-type"),
    pytest.param(init.PROVIDER_RE, init.valid_provider, id="provider"),
    pytest.param(dispatch.SLUG_RE, accepts_slug, id="slug-type"),
    pytest.param(dispatch.SLUG_RE, dispatch.valid_slug, id="dispatch-slug"),
    pytest.param(config.BRANCH_PREFIX_RE, accepts_branch_prefix, id="branch-prefix"),
]


@pytest.mark.parametrize(("pattern", "accepts"), VALIDATORS)
@given(data=st.data())
def test_validators_accept_the_whole_pattern_and_nothing_around_it(
    pattern: re.Pattern[str],
    accepts: Callable[[str], bool],
    data: st.DataObject,
) -> None:
    value = data.draw(near(pattern))
    accepted = accepts(value)
    assert accepted == (pattern.fullmatch(value) is not None)
    if accepted:
        assert not any(c.isspace() for c in value)


@given(st.text())
def test_accepted_cursor_ids_are_short_and_unbroken(value: str) -> None:
    try:
        name, cursor_id = CursorType().convert(f"comment={value}", None, None)
    except click.BadParameter:
        return
    assert name == "comment"
    assert cursor_id == value
    assert 0 < len(value) <= 200
    assert not any(c.isspace() for c in value)


@given(st.text())
def test_text_is_stripped_non_empty_and_bounded(value: str) -> None:
    try:
        text = TextType().convert(value, None, None)
    except click.BadParameter:
        assert not value.strip()
        return
    assert text == text.strip() or text.endswith("...")
    assert 0 < len(text) <= MAX_TEXT


WORDS = st.text(alphabet=string.ascii_letters + string.digits + "-_", min_size=1, max_size=12)


@given(st.lists(WORDS, min_size=1, max_size=4), st.text())
def test_the_prompt_is_always_exactly_one_argument(words: list[str], prompt: str) -> None:
    rendered = config.render_command(" ".join([*words, "{prompt}"]), prompt, Path("/defs"), "tick 1")
    assert rendered == config.Rendered([*words, prompt], None)


@given(st.lists(WORDS, min_size=1, max_size=4), st.text())
def test_a_template_with_no_prompt_gets_it_whole_on_stdin(words: list[str], prompt: str) -> None:
    rendered = config.render_command(" ".join(words), prompt, Path("/defs"), "tick 1")
    assert rendered == config.Rendered(words, prompt)


@given(st.text())
def test_the_prompt_survives_quoting_in_the_template(prompt: str) -> None:
    argv = config.render_command("agent --message='{prompt}'", prompt, Path("/defs"), "tick 1").argv
    assert argv == ["agent", f"--message={prompt}"]


@settings(suppress_health_check=fixtures, max_examples=50)
@given(attempts=st.integers(min_value=0, max_value=10**6), cooldown=st.integers(min_value=0, max_value=10**6))
def test_workspace_policy_never_loosens_the_defaults(tmp_path: Path, attempts: int, cooldown: int) -> None:
    (tmp_path / config.WORKSPACE_FILE_NAME).write_text(
        '[tracker]\nprovider = "jira"\nquery = "q"\n'
        f"[policy]\nmax_resume_attempts = {attempts}\nci_cooldown_minutes = {cooldown}\n"
        f"max_implement_attempts = {attempts}\n",
    )
    user = tmp_path / "config.toml"
    user.write_text('[tracker]\nlabels = ["mine"]\n')
    policy = config.load(tmp_path, user).policy
    assert policy.max_resume_attempts == min(attempts, 6)
    assert policy.max_implement_attempts == min(attempts, 2)
    assert policy.ci_cooldown_minutes == max(cooldown, 30)


def test_every_config_key_declares_a_scope() -> None:
    assert {*config.SECTIONS, *config.TABLE_SECTIONS} == set(config.Config.model_fields)
    for spec in config.SPECS.values():
        assert spec.scope in (config.Scope.SHARED, config.Scope.PRIVATE)
    private = {name for name, spec in config.SPECS.items() if spec.scope is config.Scope.PRIVATE}
    # TRUST_MODEL §6: commands, prompt paths, capacity, labels, and repliers never come from a shared file.
    assert private >= {
        "runtime.overseer_cmd",
        "runtime.worker_cmd",
        "runtime.worker_cmd_prefix",
        "runtime.worker_cmd_suffix",
        "notify.cmd",
        "paths.prompt_overrides",
        "paths.worker_instructions",
        "paths.overseer_instructions",
        "paths.reviewer_instructions",
        "paths.chore_instructions",
        "capacity.max_workers",
        "tracker.labels",
        "trust.authorized_repliers",
        "trust.trusted_reviewers",
        "trust.comment_prefix",
        "runtime.plan_cmd",
        # Feedback plans hold trusted reviewers' feedback, and plan anyone else's unasked (DESIGN §32).
        "policy.feedback_plan",
        # It lets a planner's own word stand for the operator's approval (DESIGN §25).
        "policy.planner_may_approve",
        "runtime.chore_cmd",
        "capacity.max_chores",
        "chores",
        # It widens what an agent's shell reaches (TRUST_MODEL T1).
        "runtime.allow_bash",
        # Which agents may send what they read to a store, and whose comments there steer a worker (DESIGN §38).
        "artifacts.mcp_server",
        "artifacts.publish_roles",
        "artifacts.authorized_authors",
    }


@pytest.mark.parametrize("name", sorted(config.SPECS))
def test_workspace_file_cannot_set_private_keys(tmp_path: Path, name: str) -> None:
    if config.SPECS[name].scope is not config.Scope.PRIVATE:
        return
    if name in config.TABLE_SECTIONS:
        extra = f'[{name}.x]\nprompt = "~/x"\n'
    else:
        section, key = name.split(".")
        extra = f'{key} = "x"\n' if section == "tracker" else f'[{section}]\n{key} = "x"\n'
    (tmp_path / config.WORKSPACE_FILE_NAME).write_text(f'[tracker]\nprovider = "jira"\nquery = "q"\n{extra}')
    user = tmp_path / "config.toml"
    user.write_text('[tracker]\nlabels = ["mine"]\n')
    with pytest.raises(config.ConfigError, match="is private"):
        config.load(tmp_path, user)


@settings(max_examples=50, deadline=None)
@given(
    st.from_regex(config.BRANCH_PREFIX_RE, fullmatch=True),
    st.from_regex(KEY_RE, fullmatch=True),
    st.from_regex(dispatch.SLUG_RE, fullmatch=True),
)
def test_branch_names_are_plain_git_branches(prefix: str, key: str, slug: str) -> None:
    # Branch names reach git's argv. git must read each as a branch name, never an option or a revision expression.
    branch = dispatch.branch_name(prefix, key, slug)
    assert not branch.startswith("-")
    assert not {"..", "@{", "//", " "} & {branch[i : i + 2] for i in range(len(branch))}
    result = SubprocessRunner().run(["git", "check-ref-format", "--branch", branch])
    assert result.ok, (branch, result.stderr)
    assert result.stdout.strip() == branch


@given(near(dispatch.SLUG_RE))
def test_accepted_slugs_are_short_and_plain(value: str) -> None:
    if dispatch.valid_slug(value):
        assert 1 <= len(value) <= 40
        assert set(value) <= set(string.ascii_lowercase + string.digits + "-")


#: Characters that mean something to a shell or to YAML: none may reach a rendered bash rule.
SHELL_SIGNIFICANT = set("\"'`$;&|<>\\(){}[]#~!^\n\r\t")


@given(st.text() | near(BASH_ALLOW_RE))
def test_an_accepted_bash_allow_is_one_plain_command_line_of_a_command_that_runs_no_other(value: str) -> None:
    try:
        bash_allows.check_pattern(value)
    except ValueError:
        return
    command = value.split(" ", 1)[0].lower()
    assert 0 < len(value) <= bash_allows.MAX_PATTERN
    assert value.isascii()
    assert value.isprintable()
    assert value == value.strip()
    assert "  " not in value
    assert not set(value) & SHELL_SIGNIFICANT
    # A literal command: no wildcard, path, assignment, or option where its name goes.
    assert not set(command) & set("*?/=")
    assert not command.startswith("-")
    assert command not in bash_allows.RUNS_COMMANDS | bash_allows.WEB_COMMANDS | bash_allows.VCS_COMMANDS
    for own in ("canopy", "treehouse", "git", "opencode"):
        assert command != own
        assert not command.startswith(f"{own}-")


REFUSED_COMMANDS = sorted(
    {*bash_allows.RUNS_COMMANDS, *bash_allows.WEB_COMMANDS, *bash_allows.VCS_COMMANDS}
    | {
        "canopy",
        "canopy-post-github",
        "treehouse",
        "opencode",
        "git",
        "git-upload-pack",
        "python3.12",
        "pip3",
        "node22",
    },
)


@given(
    st.sampled_from(REFUSED_COMMANDS),
    st.lists(st.booleans(), min_size=30, max_size=30),
    st.sampled_from(["", " *", " -c *", " decide *", " issue list *"]),
)
def test_a_command_that_runs_others_or_is_the_loops_own_is_refused_however_spelled(
    command: str,
    upper: list[bool],
    rest: str,
) -> None:
    # A file system that ignores case runs `Bash` as `bash`.
    spelled = "".join(c.upper() if up else c for c, up in zip(command, upper, strict=False))
    with pytest.raises(ValueError, match=f"allows '{re.escape(command)}'"):
        bash_allows.check_pattern(spelled + rest)
