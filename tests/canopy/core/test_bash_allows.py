"""`runtime.allow_bash`: the commands the operator lets an agent run beyond its own bash rules, and what is refused."""

import pytest

from canopy.core import bash_allows, config
from canopy.runtime import agents
from tests.conftest import CanopyEnv

JIRA = ["jira issue list *", "jira issue view *"]


def _load(canopy_env: CanopyEnv, allow_bash: dict[str, object]) -> config.Config:
    canopy_env.configure(canopy_env.user_file, {"runtime": {"allow_bash": allow_bash}})
    return config.load(canopy_env.root, canopy_env.user_file)


def test_the_overseer_takes_the_operators_allows_in_order(canopy_env: CanopyEnv) -> None:
    cfg = _load(canopy_env, {"overseer": JIRA})
    assert cfg.runtime.allow_bash == {"overseer": tuple(JIRA)}
    assert bash_allows.by_agent(cfg.runtime.allow_bash) == {agents.OVERSEER: tuple(JIRA)}


def test_none_by_default_and_an_empty_list_allows_nothing(canopy_env: CanopyEnv) -> None:
    assert config.load(canopy_env.root, canopy_env.user_file).runtime.allow_bash == {}
    assert bash_allows.by_agent(_load(canopy_env, {"overseer": []}).runtime.allow_bash) == {}


def test_the_private_file_may_set_it(canopy_env: CanopyEnv) -> None:
    canopy_env.write_private('[runtime.allow_bash]\noverseer = ["acli jira workitem view *"]\n')
    cfg = config.load(canopy_env.root, canopy_env.user_file)
    assert cfg.runtime.allow_bash == {"overseer": ("acli jira workitem view *",)}


def test_the_workspace_file_may_not(canopy_env: CanopyEnv) -> None:
    # Anyone who can push to a shared workspace would widen the operator's overseer (TRUST_MODEL T7).
    canopy_env.append_shared('\n[runtime.allow_bash]\noverseer = ["jira issue list *"]\n')
    with pytest.raises(config.ConfigError, match=r"runtime\.allow_bash is private"):
        config.load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize(
    "pattern",
    [
        "jira",
        "jira issue list *",
        "jira issue view PROJ-?? --plain",
        "acli jira workitem search --jql=project=PROJ,status=Open",
        "kubectl-get-pods pods",
        "my_tool.v2 --out=/tmp/x.json @me 50%",
    ],
)
def test_a_plain_command_line_is_accepted(pattern: str) -> None:
    assert bash_allows.check_pattern(pattern) == pattern


@pytest.mark.parametrize(
    "pattern",
    [
        "",
        "*",
        " jira issue list",
        "jira issue list ",
        "jira  issue list",
        "jira* issue list",
        "j?ra issue list",
        "/usr/local/bin/jira issue list",
        "./jira issue list",
        "-jira",
        "FOO=1 jira issue list",
        "jira issue list; rm -rf ~",
        "jira issue list && sh",
        "jira issue list | sh",
        "jira issue list > out",
        "jira issue list < in",
        "jira issue view $(whoami)",
        "jira issue view `whoami`",
        "jira issue view 'x'",
        'jira issue view "x"',
        "jira issue view \\x",
        "jira issue view {file:x}",
        "jira issue view ~/x",
        "jira issue view\nsh",
        "jira issue view\tx",
        "jira issue view \u200bx",
        "jira issue view é",
        "jira " + "x" * bash_allows.MAX_PATTERN,
    ],
)
def test_anything_but_one_plain_command_line_is_refused(pattern: str) -> None:
    with pytest.raises(ValueError, match="must be one command line"):
        bash_allows.check_pattern(pattern)


@pytest.mark.parametrize(
    ("pattern", "why"),
    [
        ("canopy decide *", "one of the loop's own tools"),
        ("canopy-post-github *", "one of the loop's own tools"),
        ("treehouse get *", "one of the loop's own tools"),
        ("opencode run *", "one of the loop's own tools"),
        ("sh -c *", "runs a command it is given"),
        ("Bash -c *", "runs a command it is given"),
        ("env *", "runs a command it is given"),
        ("xargs *", "runs a command it is given"),
        ("timeout 5 *", "runs a command it is given"),
        ("sudo jira", "runs a command it is given"),
        ("eval *", "runs a command it is given"),
        ("python3.12 -c *", "runs a command it is given"),
        ("pip3 install *", "runs a command it is given"),
        ("node -e *", "runs a command it is given"),
        ("npx *", "runs a command it is given"),
        ("uv run *", "runs a command it is given"),
        ("find . -exec *", "runs a command it is given"),
        ("less *", "runs a command it is given"),
        ("sqlite3 *", "runs a command it is given"),
        ("psql *", "runs a command it is given"),
        ("curl *", "fetches pages"),
        ("wget *", "fetches pages"),
        ("git *", "can push, merge, or close"),
        ("git-receive-pack *", "can push, merge, or close"),
        ("gh pr merge *", "can push, merge, or close"),
    ],
)
def test_a_command_that_would_undo_the_trust_model_is_refused(pattern: str, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        bash_allows.check_pattern(pattern)


@pytest.mark.parametrize("role", sorted(bash_allows.REFUSED_ROLES))
def test_no_agent_but_the_overseer_takes_an_allow(canopy_env: CanopyEnv, role: str) -> None:
    # A worker's shell already runs what its rules do not deny, so an allow could only undo a deny; the rest have none.
    with pytest.raises(config.ConfigError, match=rf"'{role}' takes no bash allows: "):
        _load(canopy_env, {role: ["jira issue list *"]})


@pytest.mark.parametrize("role", ["canopy-overseer", "everyone", "*"])
def test_a_name_that_is_no_agent_is_refused(canopy_env: CanopyEnv, role: str) -> None:
    with pytest.raises(config.ConfigError, match="is not an agent bash allows may name; name overseer"):
        _load(canopy_env, {role: ["jira issue list *"]})


def test_a_refused_pattern_fails_the_config_naming_its_file_and_key(canopy_env: CanopyEnv) -> None:
    found = r"config\.toml: runtime\.allow_bash\[overseer\]\[1\]: Value error, 'sh -c \*' allows 'sh', which runs"
    with pytest.raises(config.ConfigError, match=found):
        _load(canopy_env, {"overseer": ["jira issue list *", "sh -c *"]})


def test_a_repeated_or_a_twenty_first_pattern_is_refused(canopy_env: CanopyEnv) -> None:
    with pytest.raises(config.ConfigError, match="names 'jira issue list \\*' more than once"):
        _load(canopy_env, {"overseer": ["jira issue list *", "jira issue list *"]})
    with pytest.raises(config.ConfigError, match=f"at most {bash_allows.MAX_PATTERNS} patterns"):
        _load(canopy_env, {"overseer": [f"jira issue view P-{n}" for n in range(bash_allows.MAX_PATTERNS + 1)]})
