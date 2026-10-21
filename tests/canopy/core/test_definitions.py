"""The snapshot agent runs load canopy's agents and skills from, and the guard against shadowing them (D040, D044)."""

import fnmatch
import os
import shutil
import stat
import time
from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from pathlib import Path
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.chores import history
from canopy.core import config, definitions, git_tools, plans, prompts
from canopy.infra import resources
from canopy.runtime import agents
from canopy.runtime import definitions as runtime_definitions
from canopy.runtime.opencode import definitions as opencode_definitions
from tests.conftest import CanopyEnv

PROMPT_MARKER = "<!-- canopy: overseer prompt -->\n"
SKILL_MARKER = "    # canopy: skill rule\n"


def test_the_snapshot_holds_the_bundled_agents_skills_and_plugins(tmp_path: Path) -> None:
    snapshot = definitions.ensure(tmp_path)
    assert snapshot == tmp_path / "runtime" / definitions.digest()
    for name in runtime_definitions.agent_names():
        bundled = resources.agents_dir() / f"{name}.md"
        assert (snapshot / "agents" / f"{name}.md").read_text() == bundled.read_text()
    for skill in resources.skills_dir().iterdir():
        assert (snapshot / "skills" / skill.name / "SKILL.md").read_text() == (skill / "SKILL.md").read_text()
    # The clock, which every run that loads the snapshot loads (DESIGN §33).
    clock = resources.plugins_dir() / "canopy-clock.js"
    assert (snapshot / "plugins" / "canopy-clock.js").read_text() == clock.read_text()
    assert "canopy-worker" in runtime_definitions.agent_names()
    assert "canopy-overseer" in runtime_definitions.agent_names()


def test_the_snapshot_is_unwritable_by_anyone_its_owner_included(tmp_path: Path) -> None:
    # So the runtime installs nothing into it, and no run waits on the registry for that (DESIGN §33).
    snapshot = definitions.ensure(tmp_path)
    found = [snapshot, *snapshot.rglob("*")]
    assert {p.relative_to(snapshot).as_posix() for p in found} >= {".", "plugins", "plugins/canopy-clock.js"}
    assert [p for p in found if p.lstat().st_mode & 0o222] == []
    assert all(p.lstat().st_mode & stat.S_IRUSR for p in found)
    # Still the operator's alone, as canopy checks before loading one.
    assert definitions.ensure(tmp_path) == snapshot


def test_the_snapshots_digest_changes_with_its_plugins(tmp_path: Path) -> None:
    before = definitions.digest()
    plugins = tmp_path / "plugins"
    shutil.copytree(resources.plugins_dir(), plugins)
    with (plugins / "canopy-clock.js").open("a") as f:
        f.write("// changed\n")
    with mock.patch.object(resources, "plugins_dir", autospec=True, return_value=plugins):
        changed = definitions.ensure(tmp_path / "state")
    assert changed.name != before
    assert (changed / "plugins" / "canopy-clock.js").read_text().endswith("// changed\n")


@pytest.mark.parametrize("name", runtime_definitions.agent_names())
def test_no_agent_has_web_tools(name: str) -> None:
    # Fetched and searched pages are text anyone can shape (TRUST_MODEL T1, D077). Scalars, so a repository's config
    # cannot loosen them (D044).
    frontmatter = (resources.agents_dir() / f"{name}.md").read_text().split("---")[1]
    for tool in ("webfetch", "websearch", "codesearch"):
        assert f"\n  {tool}: deny\n" in frontmatter


@pytest.mark.parametrize("name", runtime_definitions.agent_names())
def test_no_bundled_agent_sets_a_temperature(name: str) -> None:
    # An agent runs on whatever model its command names, and some, such as OpenAI's reasoning models, refuse a request
    # that sets one. The overseer's and the reviewer's come from `runtime`, rendered into the snapshot rather than set
    # in their bundled files.
    frontmatter = (resources.agents_dir() / f"{name}.md").read_text().split("---")[1]
    assert "\ntemperature:" not in frontmatter


def test_the_operator_skill_is_not_in_the_snapshot(tmp_path: Path) -> None:
    # It is for the operator's own sessions; an operator's copy of it in $HOME would clash with a second one here.
    snapshot = definitions.ensure(tmp_path)
    names = [p.name for p in (snapshot / "skills").iterdir()]
    assert "canopy" not in names
    assert names


@pytest.mark.parametrize("agent", runtime_definitions.agent_names())
def test_no_agent_is_offered_the_operator_skill(canopy_env: CanopyEnv, agent: str) -> None:
    # The operator may install it where OpenCode finds skills for every agent, canopy's too (DESIGN §13).
    frontmatter = resources.operator_skill().read_text().split("---")[1]
    name = next(line.removeprefix("name:").strip() for line in frontmatter.splitlines() if line.startswith("name:"))
    ruleset = _ruleset(canopy_env, agent)
    assert _opencode_action(ruleset, "skill", name) == "deny"
    assert _opencode_action(ruleset, "skill", "tracker-jira") == ("deny" if agent == agents.OVERSEER else "allow")
    # The overseer's body holds the tracker's skill, so its skill tool is denied whole and not sent.
    assert _opencode_disabled(ruleset, "skill") == (agent == agents.OVERSEER)


def test_an_existing_snapshot_is_reused_as_is(tmp_path: Path) -> None:
    snapshot = definitions.ensure(tmp_path)
    # OpenCode writes into a directory it loads that it can write, as into a snapshot made before canopy took the write
    # permission away; that must not make canopy copy again.
    snapshot.chmod(0o700)
    (snapshot / "node_modules").mkdir()
    assert definitions.ensure(tmp_path) == snapshot
    assert (snapshot / "node_modules").is_dir()
    assert [p.name for p in (tmp_path / "runtime").iterdir()] == [snapshot.name]


def test_losing_the_race_to_create_a_snapshot_uses_the_winners(tmp_path: Path) -> None:
    final = tmp_path / "runtime" / definitions.digest()
    real_rename = os.rename

    def another_process_wins(src: Path, dst: Path) -> None:
        shutil.copytree(src, final)
        final.chmod(0o700)
        (final / "winner").touch()
        final.chmod(0o500)
        real_rename(src, dst)  # refused: dst is a directory that is not empty

    with mock.patch.object(os, "rename", autospec=True, side_effect=another_process_wins):
        assert definitions.ensure(tmp_path) == final
    assert (final / "winner").exists()
    assert [p.name for p in (tmp_path / "runtime").iterdir()] == [final.name]


def test_prune_keeps_the_current_snapshot_and_fresh_temporary_directories(tmp_path: Path) -> None:
    current = definitions.ensure(tmp_path)
    runtime = tmp_path / "runtime"
    old = runtime / "0123456789abcdef"
    old.mkdir()
    fresh_tmp = runtime / ".tmp-fresh"
    fresh_tmp.mkdir()
    (old / "agents").mkdir()
    (old / "agents" / "canopy-worker.md").touch()
    stale_tmp = runtime / ".tmp-stale"
    stale_tmp.mkdir()
    # Unwritable, as canopy leaves a snapshot and the copy a process died with after taking its write permission away.
    for unwritable in (old / "agents" / "canopy-worker.md", old / "agents", old, stale_tmp):
        unwritable.chmod(0o500)
    hours_ago = time.time() - 2 * 3600
    os.utime(stale_tmp, (hours_ago, hours_ago))

    assert definitions.prune(tmp_path, current) == [stale_tmp, old]
    assert sorted(p.name for p in runtime.iterdir()) == sorted([current.name, fresh_tmp.name])


def test_prune_without_a_runtime_directory(tmp_path: Path) -> None:
    assert definitions.prune(tmp_path, tmp_path / "runtime" / "x") == []


def _rules(agent: str, section: str = "") -> list[tuple[str, str]]:
    """The agent's quoted permission rules, in order: its top-level ones, OpenCode's patterns for MCP tool names, or
    those under `section`, such as `bash`, whose patterns are command lines."""
    return _rules_in((resources.agents_dir() / f"{agent}.md").read_text(), section)


def _rules_in(definition: str, section: str = "") -> list[tuple[str, str]]:
    frontmatter = definition.split("---")[1]
    indent = "    " if section else "  "
    inside = not section
    rules: list[tuple[str, str]] = []
    for line in frontmatter.splitlines():
        if section and line.startswith("  ") and not line.startswith("   ") and not line.lstrip().startswith("#"):
            inside = line.strip() == f"{section}:"
        elif inside and line.startswith(f'{indent}"'):
            pattern, action = line.strip().rsplit(":", 1)
            rules.append((pattern.strip('"'), action.strip()))
    return rules


@pytest.mark.parametrize("agent", ["canopy-worker", agents.PRIVATE_WORKER])
def test_workers_may_push_as_their_prompts_say_and_never_force(agent: str) -> None:
    """The prompts push HEAD by refspec from a detached checkout (D109); the definitions must not refuse it."""
    rules = _rules(agent, "bash")
    assert rules
    assert _allowed(rules, "git push origin HEAD:refs/heads/agent/PROJ-1-docs-fix")
    for refused in (
        "git push --force origin HEAD:refs/heads/agent/PROJ-1-x",
        "git push -f origin HEAD:refs/heads/agent/PROJ-1-x",
        "git push origin +HEAD:refs/heads/agent/PROJ-1-x",
        "git push origin :refs/heads/agent/PROJ-1-x",
    ):
        assert not _allowed(rules, refused), refused


LEASED_PUSH = "git push --force-with-lease origin HEAD:refs/heads/agent/PROJ-1-x"


@pytest.mark.parametrize("agent", ["canopy-worker", agents.PRIVATE_WORKER])
def test_with_rebase_workers_may_push_with_a_lease_and_no_other_force(canopy_env: CanopyEnv, agent: str) -> None:
    """`trust.rebase` adds the one forced push the prompts name; every other force, and the rest, stay denied."""
    path = f"agents/{agent}.md"
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[path].decode()
    assert not _allowed(_rules_in(rendered, "bash"), LEASED_PUSH)
    canopy_env.append_user("\n[trust]\nrebase = true\n")
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[path].decode()
    rules = _rules_in(rendered, "bash")
    assert _allowed(rules, LEASED_PUSH)
    assert _allowed(rules, "git push origin HEAD:refs/heads/agent/PROJ-1-x")
    for refused in (
        "git push --force origin HEAD:refs/heads/agent/PROJ-1-x",
        "git push --force-with-lease origin HEAD:refs/heads/agent/PROJ-1-x --force",
        "git push --force-with-lease origin HEAD:refs/heads/agent/PROJ-1-x --force --no-verify",
        "git push --force-with-lease origin HEAD:refs/heads/agent/PROJ-1-x -f",
        "git push --force-with-lease=refs/heads/main origin HEAD:refs/heads/main",
        "git push --force-with-lease origin +HEAD:refs/heads/agent/PROJ-1-x",
        "git push --force-with-lease origin HEAD:refs/heads/agent/PROJ-1-x --delete",
        "git push --force-with-lease origin HEAD:refs/heads/agent/PROJ-1-x --mirror",
        "git push --force-with-lease origin HEAD:refs/heads/agent/PROJ-1-x :refs/heads/main",
        "git push -f origin HEAD:refs/heads/agent/PROJ-1-x",
    ):
        assert not _allowed(rules, refused), refused


# Each agent whose temperature is rendered from config, with its key in `[runtime]`.
TEMPERATURES = [
    ("canopy-reviewer", "review_temperature"),
    ("canopy-overseer", "overseer_temperature"),
]


@pytest.mark.parametrize(("agent", "rendered"), [("canopy-reviewer", None), ("canopy-overseer", "0.1")])
def test_an_agent_gets_its_default_temperature(canopy_env: CanopyEnv, agent: str, rendered: str | None) -> None:
    """The reviewer sets none, since it often runs on a model that refuses one, such as OpenAI's reasoning models."""
    text = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[f"agents/{agent}.md"].decode()
    frontmatter = text.split("---")[1]
    if rendered is None:
        assert "\ntemperature:" not in frontmatter
    else:
        assert f"\ntemperature: {rendered}\n" in frontmatter


@pytest.mark.parametrize(("agent", "key"), TEMPERATURES)
@pytest.mark.parametrize(("setting", "rendered"), [("0.1", "0.1"), ("0.7", "0.7"), ("0", "0.0")])
def test_an_agent_gets_its_configured_temperature(
    canopy_env: CanopyEnv,
    agent: str,
    key: str,
    setting: str,
    rendered: str,
) -> None:
    _set_runtime(canopy_env, f"{key} = {setting}")
    text = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[f"agents/{agent}.md"].decode()
    assert f"\ntemperature: {rendered}\n" in text.split("---")[1]


@pytest.mark.parametrize(("agent", "key"), TEMPERATURES)
def test_a_temperature_of_minus_one_sets_none(canopy_env: CanopyEnv, agent: str, key: str) -> None:
    """-1 leaves the model's own, for a model that refuses a request that sets one; a new snapshot says so."""
    user = canopy_env.user_file.read_text()
    _set_runtime(canopy_env, f"{key} = 0.1")
    sets_one = config.load(canopy_env.root, canopy_env.user_file)
    canopy_env.write_user(user)
    _set_runtime(canopy_env, f"{key} = -1")
    unset = config.load(canopy_env.root, canopy_env.user_file)
    frontmatter = definitions.sources(unset)[f"agents/{agent}.md"].decode().split("---")[1]
    assert "\ntemperature:" not in frontmatter
    assert definitions.digest(unset) != definitions.digest(sets_one)


def _set_runtime(canopy_env: CanopyEnv, line: str) -> None:
    # The user file has a `[runtime]` table already, and TOML forbids repeating a header.
    canopy_env.write_user(canopy_env.user_file.read_text().replace("[runtime]\n", f"[runtime]\n{line}\n", 1))


def _allowed(rules: Iterable[tuple[str, str]], tool: str) -> bool:
    # The last matching rule wins (D021); a tool no rule names keeps what the operator's runtime grants.
    verdicts = [action for pattern, action in rules if fnmatch.fnmatchcase(tool, pattern)]
    return not verdicts or verdicts[-1] != "deny"


@pytest.mark.parametrize(
    "tool",
    [
        "github_merge_pull_request",
        "github_pull_request_review_write",
        "github_create_pull_request_review",
        "github_create_and_submit_pull_request_review",
        "github_submit_pending_pull_request_review",
        "github_add_comment_to_pending_review",
        "github_close_issue",
        "github_close_pull_request",
        "github_sub_issue_write",
        "github_create_branch",
        "github_push_files",
        "github_delete_file",
        "github_fork_repository",
        "atlassian_transitionJiraIssue",
    ],
)
@pytest.mark.parametrize("agent", ["canopy-worker", agents.PRIVATE_WORKER])
def test_workers_deny_dangerous_mcp_tools(agent: str, tool: str) -> None:
    assert not _allowed(_rules(agent), tool)


@pytest.mark.parametrize("tool", ["github_create_issue", "atlassian_createJiraIssue"])
def test_the_public_worker_may_create_follow_up_tickets(tool: str) -> None:
    # A public worker files follow-ups in its ticket's project (DESIGN §18, TRUST_MODEL T6). The private worker's
    # definition, as shipped, names no tracker's tools: canopy renders them from config, below.
    assert _allowed(_rules("canopy-worker"), tool)
    assert not _allowed(_rules(agents.PRIVATE_WORKER), tool)


@pytest.mark.parametrize(
    ("provider", "tool", "allowed"),
    [
        ("github", "github_issue_write", True),
        ("github", "github_issue_read", True),
        ("github", "github_add_issue_comment", False),
        ("github", "github_sub_issue_write", False),
        ("github", "github_someWriteToolNoPatternNames", False),
        ("jira", "atlassian_createJiraIssue", True),
        ("jira", "atlassian_getJiraIssue", True),
        ("jira", "atlassian_editJiraIssue", False),
        ("jira", "atlassian_addCommentToJiraIssue", False),
        ("jira", "atlassian_transitionJiraIssue", False),
        ("jira", "atlassian_someWriteToolNoPatternNames", False),
    ],
)
def test_the_private_worker_may_create_follow_ups_and_write_nothing_else_to_the_tracker(
    provider: str,
    tool: str,
    *,
    allowed: bool,
) -> None:
    # Its follow-ups are the one thing it writes there (DESIGN §18, §22): the create tools are allowed by name, whole,
    # after the server's wildcard deny; every other write of the server stays denied by it.
    bundled = (resources.agents_dir() / f"{agents.PRIVATE_WORKER}.md").read_text()
    rendered = opencode_definitions.render_private(bundled, config.DEFAULT_TRACKER_TOOLS[provider])
    assert _allowed(_rules_in(rendered), tool) is allowed


def test_the_planner_gets_no_create_tool() -> None:
    bundled = (resources.agents_dir() / f"{agents.PLANNER}.md").read_text()
    rendered = opencode_definitions.render_private(
        bundled,
        config.DEFAULT_TRACKER_TOOLS["github"],
        f"agents/{agents.PLANNER}.md",
    )
    assert not _allowed(_rules_in(rendered), "github_issue_write")


@pytest.mark.parametrize(
    "tool",
    [
        "github_create_pull_request",
        "github_update_pull_request",
        "github_pull_request_read",
        "github_get_pull_request_reviews",
        "github_add_reply_to_pull_request_comment",
    ],
)
@pytest.mark.parametrize("agent", ["canopy-worker", agents.PRIVATE_WORKER])
def test_workers_keep_the_pr_tools_they_work_with(agent: str, tool: str) -> None:
    assert _allowed(_rules(agent), tool)


@pytest.mark.parametrize("agent", ["canopy-worker", agents.PRIVATE_WORKER])
def test_workers_may_read_a_pr_and_its_ci_with_gh(agent: str) -> None:
    """A resumed worker reads the review comments it was pointed at, and a fix-ci one the failing checks; the private
    one still cannot reach the ticket."""
    rules = _rules(agent, "bash")
    for command in (
        "gh pr view",
        "gh pr view 12 --comments",
        "gh pr view agent/PROJ-1-x --json reviews",
        "gh pr checks 12",
        "gh pr diff 12",
        "gh run view 123 --log-failed",
    ):
        assert _allowed(rules, command), command
    if agent == agents.PRIVATE_WORKER:
        for refused in ("gh", "gh issue view 12", "gh issue comment 12 --body x", "gh pr comment 12 --body x"):
            assert not _allowed(rules, refused), refused


@pytest.mark.parametrize("agent", ["canopy-worker", agents.PRIVATE_WORKER])
def test_workers_may_edit_their_pr_with_gh(agent: str) -> None:
    """`gh pr edit` writes to a PR, as the PR update tool both keep does; the private one still cannot edit the
    ticket."""
    rules = _rules(agent, "bash")
    for command in ("gh pr edit", "gh pr edit 12 --title 'PROJ-1: x'", "gh pr edit agent/PROJ-1-x --body-file body.md"):
        assert _allowed(rules, command), command
    if agent == agents.PRIVATE_WORKER:
        for refused in ("gh issue edit 12 --title x", "gh pr comment 12 --body x", "gh pr editx"):
            assert not _allowed(rules, refused), refused


@pytest.mark.parametrize("agent", ["canopy-worker", agents.PRIVATE_WORKER])
def test_workers_may_search_their_memory_and_run_no_other_canopy_command(agent: str) -> None:
    """The memory digests name `canopy memory search` (DESIGN §28); the loop's other commands stay the overseer's."""
    rules = _rules(agent, "bash")
    assert _allowed(rules, "canopy memory search retry backoff")
    for refused in ("canopy decide", "canopy memory forget 3", "canopy memory search", "canopy reply chore:x hi"):
        assert not _allowed(rules, refused), refused


@pytest.mark.parametrize(
    "tool",
    [
        "github_add_issue_comment",
        "github_issue_read",
        "github_issue_write",
        "atlassian_getJiraIssue",
        "atlassian_editJiraIssue",
        "atlassian_addCommentToJiraIssue",
    ],
)
def test_the_worker_keeps_the_ticket_tools_it_works_with(tool: str) -> None:
    assert _allowed(_rules("canopy-worker"), tool)


@pytest.mark.parametrize(
    "tool",
    [
        "github_add_issue_comment",
        "github_add_reply_to_pull_request_comment",
        "github_add_comment_to_pending_review",
        "github_pull_request_review_write",
        "github_issue_write",
        "github_update_pull_request",
        "github_create_or_update_file",
        "atlassian_addCommentToJiraIssue",
        "atlassian_editJiraIssue",
        "linear_create_comment",
    ],
)
def test_the_reviewer_posts_nothing(tool: str) -> None:
    # Its result line is the whole review; nothing of it reaches the PR or the ticket (DESIGN §21, D114).
    assert not _allowed(_rules("canopy-reviewer"), tool)


@pytest.mark.parametrize(
    "tool",
    ["github_pull_request_read", "github_issue_read", "github_get_pull_request_reviews", "atlassian_getJiraIssue"],
)
def test_the_reviewer_keeps_its_read_tools(tool: str) -> None:
    assert _allowed(_rules("canopy-reviewer"), tool)


#: The agents example chores come with, copies of `canopy-chore` that `canopy chore install` puts in the workspace, and
#: commands their prompts run.
CHORE_AGENTS = {
    "canopy-introspect": (
        "canopy health --json --days 7",
        "canopy spend --json --days 28",
        "canopy decisions 12",
        "canopy show run:4",
        "canopy show chore:canopy-health",
        "canopy config show --json",
        "canopy agents --json",
        "canopy chore history canopy-health",
    ),
    "canopy-memory-tickets": (
        "canopy memory lessons --json",
        "canopy memory proposals --json",
        "canopy memory list --json",
        "canopy chore history memory-tickets",
    ),
}


@pytest.mark.parametrize("agent", sorted(CHORE_AGENTS))
def test_an_example_chores_agent_is_canopy_chore_with_a_shell_for_its_prompts_commands(agent: str) -> None:
    """Everything but bash is `canopy-chore`'s (DESIGN §19), so it can write nothing `canopy-chore` could not."""
    definition = (resources.example_chores_dir() / "agents" / f"{agent}.md").read_text()
    assert _outside_bash(definition) == _outside_bash((resources.agents_dir() / "canopy-chore.md").read_text())
    rules = _rules_in(definition, "bash")
    for command in CHORE_AGENTS[agent]:
        assert _allowed(rules, command), command
    for refused in (
        "canopy memory forget 3",
        "canopy memory promote 3",
        "canopy decide PROJ-1 wait --rationale x",
        "canopy reply chore:x hi",
        "canopy dismiss chore:x id",
        "canopy chore try x",
        "canopy show PROJ-1",
        "opencode run --agent canopy-worker x",
        "gh issue create",
        "rm -rf .canopy",
    ):
        assert not _allowed(rules, refused), refused


def _outside_bash(definition: str) -> list[str]:
    """The definition's frontmatter lines but its description, its comments, and its `bash` rules."""
    kept: list[str] = []
    in_bash = False
    for line in definition.split("---")[1].splitlines():
        if line.lstrip().startswith("#") or line.startswith("description:"):
            continue
        if line.startswith("  ") and not line.startswith("   "):
            in_bash = line.strip().partition(":")[0] == "bash"
        if not in_bash:
            kept.append(line)
    return kept


@pytest.mark.parametrize(
    ("tool", "allowed"),
    [
        ("atlassian_getJiraIssue", True),
        ("atlassian_listJiraIssueComments", True),
        ("atlassian_addCommentToJiraIssue", False),
        ("atlassian_editJiraIssue", False),
        ("atlassian_transitionJiraIssue", False),
        ("atlassian_createJiraIssue", False),
        ("atlassian_someWriteToolNoPatternNames", False),
        ("github_add_issue_comment", False),
        ("github_create_pull_request", False),
        ("github_issue_write", False),
        ("github_pull_request_read", True),
    ],
)
def test_the_planner_reads_the_ticket_and_writes_nothing(canopy_env: CanopyEnv, tool: str, *, allowed: bool) -> None:
    # Rendered with the tracker's server and read tools: every other tool of the server is denied by its wildcard, so
    # a write tool no pattern names fails closed (DESIGN §25, TRUST_MODEL T6).
    path = f"agents/{agents.PLANNER}.md"
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[path].decode()
    assert _allowed(_rules_in(rendered), tool) is allowed


#: A chore's one tool of canopy's, its own history (DESIGN §19), as the runtime names it.
CHORE_HISTORY = history.tool_name()


@pytest.mark.parametrize("provider", ["github", "jira"])
def test_a_chore_may_call_its_history_tool_and_has_no_shell(canopy_env: CanopyEnv, provider: str) -> None:
    """The shipped chore reads its history through its tool alone: its shell is gone (ROADMAP M48, Stage 1b)."""
    _set_provider(canopy_env, provider)
    ruleset = _ruleset(canopy_env, agents.CHORE)
    assert _opencode_action(ruleset, CHORE_HISTORY, "*") == "allow"
    assert _opencode_disabled(ruleset, "bash")
    assert _opencode_action(ruleset, "bash", "canopy chore history build-health") == "deny"


@pytest.mark.parametrize("provider", ["github", "jira"])
@pytest.mark.parametrize("agent", sorted(set(runtime_definitions.agent_names()) - {agents.CHORE}))
def test_no_other_agent_may_call_a_chores_history_tool(canopy_env: CanopyEnv, agent: str, provider: str) -> None:
    _set_provider(canopy_env, provider)
    assert _opencode_disabled(_ruleset(canopy_env, agent), CHORE_HISTORY)


#: canopy's read-only git tools, the reviewer's and the planner's (DESIGN §27), as the runtime names them.
GIT_TOOLS = git_tools.tool_names()
#: The agents that read git through them, having no shell.
GIT_READERS = {agents.REVIEWER, agents.PLANNER}


@pytest.mark.parametrize("provider", ["github", "jira"])
@pytest.mark.parametrize("agent", sorted(GIT_READERS))
def test_the_reviewer_and_the_planner_may_call_canopys_git_tools_and_have_no_shell(
    canopy_env: CanopyEnv,
    agent: str,
    provider: str,
) -> None:
    """Each tool by its exact name, whatever pattern before it denies, such as `*merge*` (#1130)."""
    _set_provider(canopy_env, provider)
    ruleset = _ruleset(canopy_env, agent)
    assert [_opencode_action(ruleset, tool, "*") for tool in GIT_TOOLS] == ["allow"] * len(GIT_TOOLS)
    assert _opencode_disabled(ruleset, "bash")
    # Allowed by name, never by a pattern: a tool of the server it does not serve is no one's.
    assert _opencode_action(ruleset, "canopy_git_merge", "*") == "deny"


@pytest.mark.parametrize("provider", ["github", "jira"])
@pytest.mark.parametrize("agent", sorted(set(runtime_definitions.agent_names()) - GIT_READERS))
def test_no_other_agent_may_call_canopys_git_tools(canopy_env: CanopyEnv, agent: str, provider: str) -> None:
    _set_provider(canopy_env, provider)
    ruleset = _ruleset(canopy_env, agent)
    assert [tool for tool in GIT_TOOLS if not _opencode_disabled(ruleset, tool)] == []


@pytest.mark.parametrize("agent", sorted(CHORE_AGENTS))
def test_an_example_chores_agent_may_call_its_history_tool_too(agent: str) -> None:
    """Copied at install, it keeps its shell for its prompts' commands, and gets the tool every chore's prompt names."""
    definition = (resources.example_chores_dir() / "agents" / f"{agent}.md").read_text()
    assert _allowed(_rules_in(definition), CHORE_HISTORY)


def test_the_planner_has_no_shell_or_subagent_tools() -> None:
    frontmatter = (resources.agents_dir() / f"{agents.PLANNER}.md").read_text().split("---")[1]
    for tool in ("bash", "task", "external_directory"):
        assert f"\n  {tool}: deny\n" in frontmatter


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        # Relative to the project, as OpenCode matches it: `/` for a desk outside a checkout, else the checkout.
        (".canopy-new-plan.md", True),
        ("desks/PROJ-1/.canopy-new-plan.md", True),
        ("home/op/acme/desks/PROJ-1/.canopy-new-plan.md", True),
        ("desks/PROJ-1/.canopy-plan.md", False),
        ("desks/PROJ-1/api/src/app.py", False),
        ("desks/PROJ-1/.canopy-new-plan.md.bak", False),
        ("desks/PROJ-1/notes.md", False),
    ],
)
def test_the_planner_may_edit_only_its_plan_file(canopy_env: CanopyEnv, path: str, *, allowed: bool) -> None:
    # Evaluated as OpenCode 1.19 does: every key matches the permission's name as a wildcard, so `*edit*` is an edit
    # rule too, and the last rule matching both the name and the path wins (D021).
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[f"agents/{agents.PLANNER}.md"]
    ruleset = _opencode_ruleset(rendered.decode())
    assert _opencode_action(ruleset, "edit", path) == ("allow" if allowed else "deny")


def test_the_planner_keeps_its_edit_tool_and_loses_its_shell(canopy_env: CanopyEnv) -> None:
    # OpenCode leaves a tool out of the model's toolset when the last rule for its permission denies `*`
    # (`Permission.disabled`): a `*edit*` after the edit rules would take away the only way to write the plan.
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[f"agents/{agents.PLANNER}.md"]
    ruleset = _opencode_ruleset(rendered.decode())
    assert not _opencode_disabled(ruleset, "edit")
    # The file `_run` reads the plan from is the one the definition lets the planner write.
    assert _opencode_action(ruleset, "edit", f"desks/PROJ-1/{plans.WRITTEN}") == "allow"
    for permission in ("bash", "task", "webfetch"):
        assert _opencode_disabled(ruleset, permission)


def _opencode_ruleset(definition: str) -> list[tuple[str, str, str]]:
    """The definition's permission rules as OpenCode's `Permission.fromConfig` makes them, in order.

    Each is (permission, path pattern, action): a scalar is its permission's rule for `*`, and a table one rule per
    pattern. Only the frontmatter's two levels canopy writes are read, not YAML in general.
    """
    frontmatter = definition.split("---")[1]
    rules: list[tuple[str, str, str]] = []
    section = ""
    inside = False
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("permission:"):
            inside = True
            continue
        if not inside or not line.startswith("  "):
            inside = inside and line.startswith("  ")
            continue
        key, _, value = stripped.rpartition(":") if stripped.startswith('"') else stripped.partition(":")
        key, value = key.strip().strip('"'), value.strip()
        if line.startswith("    "):
            rules.append((section, key, value))
        elif value:
            rules.append((key, "*", value))
        else:
            section = key
    return rules


def _opencode_action(ruleset: Iterable[tuple[str, str, str]], permission: str, path: str) -> str:
    # OpenCode's `Wildcard.match` is a whole-string match where `*` crosses `/`, as fnmatch's does.
    matching = [
        a for p, pattern, a in ruleset if fnmatch.fnmatchcase(permission, p) and fnmatch.fnmatchcase(path, pattern)
    ]
    return matching[-1] if matching else "allow"


def _opencode_disabled(ruleset: Iterable[tuple[str, str, str]], permission: str) -> bool:
    matching = [(pattern, a) for p, pattern, a in ruleset if fnmatch.fnmatchcase(permission, p)]
    return bool(matching) and matching[-1] == ("*", "deny")


def test_the_overseer_definition_carries_its_prompt_and_the_trackers_skill(canopy_env: CanopyEnv) -> None:
    # The prompt is the agent's system prompt, cached across ticks; the tick's message is the state block (DESIGN §6).
    snapshot = definitions.ensure(canopy_env.state_dir, config.load(canopy_env.root))
    text = (snapshot / "agents" / "canopy-overseer.md").read_text()
    bundled = (resources.agents_dir() / "canopy-overseer.md").read_text()
    head = opencode_definitions.render_temperature(bundled, "canopy-overseer", 0.1).split(PROMPT_MARKER)[0]
    head = opencode_definitions.render_overseer_reads(head, config.DEFAULT_TRACKER_TOOLS["jira"], "jira")
    # With the skill in its body, it has nothing to load (`"*": deny` among its skill rules, below).
    head = head.replace(SKILL_MARKER, f'{SKILL_MARKER}    "*": deny\n', 1)
    assert text.startswith(head)
    body = text.removeprefix(head)
    prompt = prompts.render_overseer(config.load(canopy_env.root)).strip("\n")
    assert body.startswith(
        f"{prompt}\n\nThe skill `tracker-jira` follows, given here so that you need not load it.\n\n",
    )
    skill = (resources.skills_dir() / "tracker-jira" / "SKILL.md").read_text()
    assert body.endswith(skill.split("\n---\n", 1)[1].strip() + "\n")
    assert "name: tracker-jira" not in body
    assert "no prompt supplied" not in body
    # The skill stays a skill too, for the workers.
    assert (snapshot / "skills" / "tracker-jira" / "SKILL.md").read_text() == skill


def test_an_overseer_override_makes_a_snapshot_of_its_own(canopy_env: CanopyEnv) -> None:
    cfg = config.load(canopy_env.root)
    shipped = definitions.ensure(canopy_env.state_dir, cfg)
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "overseer.md").write_text("# my overseer\n\nDecide my way.\n")
    snapshot = definitions.ensure(canopy_env.state_dir, cfg)
    assert snapshot != shipped
    text = (snapshot / "agents" / "canopy-overseer.md").read_text()
    assert "\n---\n\n# my overseer\n\nDecide my way.\n\nThe skill `tracker-jira` follows" in text
    assert "# canopy overseer" not in text
    # The snapshot a run may be loading is never changed.
    assert "# canopy overseer" in (shipped / "agents" / "canopy-overseer.md").read_text()


def test_an_overseer_override_canopy_cannot_read_refuses_the_snapshot(canopy_env: CanopyEnv) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "overseer.md").write_bytes(b"\xff\xfe not UTF-8")
    with pytest.raises(definitions.DefinitionsError, match="cannot read the overseer prompt"):
        definitions.ensure(canopy_env.state_dir, config.load(canopy_env.root))


JIRA_CLI_READS = ("jira issue list *", "jira issue view *")


def test_the_overseer_may_run_the_commands_config_allows_it_and_its_snapshot_says_so(canopy_env: CanopyEnv) -> None:
    before = config.load(canopy_env.root, canopy_env.user_file)
    canopy_env.configure(canopy_env.user_file, {"runtime": {"allow_bash": {"overseer": list(JIRA_CLI_READS)}}})
    cfg = config.load(canopy_env.root, canopy_env.user_file)
    rendered = definitions.sources(cfg)
    rules = _rules_in(rendered["agents/canopy-overseer.md"].decode(), "bash")
    assert rules[-2:] == [(pattern, "allow") for pattern in JIRA_CLI_READS]
    for allowed in ("jira issue list -q 'project = PROJ'", "jira issue view PROJ-1 --plain", "canopy decisions"):
        assert _allowed(rules, allowed), allowed
    for refused in ("jira issue create", "sh -c 'jira issue list'", "treehouse get", "rm -rf /"):
        assert not _allowed(rules, refused), refused
    # Only the overseer's definition changes, and so the snapshot's digest: a run loading the old one keeps it (D040).
    shipped = definitions.sources(before)
    assert [rel for rel in rendered if rendered[rel] != shipped[rel]] == ["agents/canopy-overseer.md"]
    assert definitions.digest(cfg) != definitions.digest(before)
    canopy_env.configure(canopy_env.user_file, {"runtime": {"allow_bash": {"overseer": []}}})
    assert definitions.digest(config.load(canopy_env.root, canopy_env.user_file)) == definitions.digest(before)


@pytest.mark.parametrize("agent", runtime_definitions.agent_names())
def test_each_agent_definition_as_rendered(
    canopy_env: CanopyEnv,
    markdown_snapshot: SnapshotAssertion,
    agent: str,
) -> None:
    # What each agent runs on, as a run loads it: its rules, and the overseer's whole prompt and tracker skill.
    files = definitions.sources(config.load(canopy_env.root))
    assert files[f"agents/{agent}.md"].decode() == markdown_snapshot


#: GitHub's MCP tools, as its server v2.0.2 lists them on its default toolsets, in OpenCode's `<server>_<tool>` form.
GITHUB_TOOLS = tuple(
    f"github_{tool}"
    for tool in (
        "get_me",
        "get_team_members",
        "get_teams",
        "ui_get",
        "assign_copilot_to_issue",
        "request_copilot_review",
        "add_issue_comment",
        "get_label",
        "issue_read",
        "issue_write",
        "list_issue_fields",
        "list_issue_types",
        "list_issues",
        "search_issues",
        "sub_issue_write",
        "update_issue_comment",
        "add_comment_to_pending_review",
        "add_reply_to_pull_request_comment",
        "create_pull_request",
        "list_pull_requests",
        "merge_pull_request",
        "pull_request_read",
        "pull_request_review_write",
        "search_pull_requests",
        "update_pull_request",
        "update_pull_request_branch",
        "create_branch",
        "create_or_update_file",
        "create_repository",
        "delete_file",
        "fork_repository",
        "get_commit",
        "get_file_contents",
        "get_latest_release",
        "get_release_by_tag",
        "get_tag",
        "list_branches",
        "list_commits",
        "list_releases",
        "list_repository_collaborators",
        "list_tags",
        "push_files",
        "search_code",
        "search_commits",
        "search_repositories",
        "search_users",
    )
)
#: The ones no canopy prompt asks for: teams, users, UI data, releases, tags, repository search and creation, forks,
#: collaborators, and Copilot.
UNASKED_GITHUB_TOOLS = (
    "github_get_teams",
    "github_get_team_members",
    "github_search_users",
    "github_ui_get",
    "github_list_releases",
    "github_get_latest_release",
    "github_get_release_by_tag",
    "github_list_tags",
    "github_get_tag",
    "github_search_repositories",
    "github_list_repository_collaborators",
    "github_create_repository",
    "github_fork_repository",
    "github_assign_copilot_to_issue",
    "github_request_copilot_review",
)
#: The overseer's reads of GitHub: PRs, with their checks, reviews, and merge state; branches; and the signed-in user.
OVERSEER_GITHUB_READS = {
    "github_pull_request_read",
    "github_list_pull_requests",
    "github_search_pull_requests",
    "github_list_branches",
    "github_get_me",
}
#: Its reads of GitHub's issues, which are the tickets only when the tracker is GitHub.
GITHUB_ISSUE_READS = {"github_issue_read", "github_list_issues", "github_search_issues"}


def _ruleset(canopy_env: CanopyEnv, agent: str) -> list[tuple[str, str, str]]:
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[f"agents/{agent}.md"]
    return _opencode_ruleset(rendered.decode())


@pytest.mark.parametrize("agent", sorted(set(runtime_definitions.agent_names()) - {agents.CHORE}))
def test_no_agent_is_sent_the_github_tools_no_prompt_asks_for(canopy_env: CanopyEnv, agent: str) -> None:
    # OpenCode leaves a tool its rules deny whole out of the request (MEASUREMENTS 2026-10-19 F42), which is what this
    # cuts: each schema is sent on every call.
    ruleset = _ruleset(canopy_env, agent)
    assert [tool for tool in UNASKED_GITHUB_TOOLS if not _opencode_disabled(ruleset, tool)] == []


def test_a_chore_keeps_githubs_reads_and_loses_copilot(canopy_env: CanopyEnv) -> None:
    # A chore's prompt is the operator's, and may ask for any read, such as the tags since a release; Copilot writes.
    ruleset = _ruleset(canopy_env, agents.CHORE)
    for tool in ("github_list_tags", "github_get_latest_release", "github_get_teams", "github_search_repositories"):
        assert not _opencode_disabled(ruleset, tool), tool
    assert _opencode_disabled(ruleset, "github_request_copilot_review")
    assert _opencode_disabled(ruleset, "github_assign_copilot_to_issue")


@pytest.mark.parametrize(("provider", "issues"), [("jira", False), ("github", True)])
def test_the_overseer_is_sent_only_the_github_reads_it_makes(
    canopy_env: CanopyEnv,
    provider: str,
    *,
    issues: bool,
) -> None:
    # Every write is denied (TRUST_MODEL T6), and every read its prompt has no use for: GitHub's issue reads too, but
    # when the issues are the tickets.
    _set_provider(canopy_env, provider)
    ruleset = _ruleset(canopy_env, agents.OVERSEER)
    expected = OVERSEER_GITHUB_READS | (GITHUB_ISSUE_READS if issues else set())
    assert {tool for tool in GITHUB_TOOLS if not _opencode_disabled(ruleset, tool)} == expected


def _set_provider(canopy_env: CanopyEnv, provider: str) -> None:
    canopy_env.write_shared(canopy_env.shared_file.read_text().replace('provider = "jira"', f'provider = "{provider}"'))


#: Tools of Atlassian's server that write to Jira, and the `execute` ones that run another by name, read or write.
JIRA_WRITES = (
    "addCommentToJiraIssue",
    "addWorklogToJiraIssue",
    "createIssueLink",
    "createJiraIssue",
    "editJiraIssue",
    "transitionJiraIssue",
    "execute",
    "executeJiraTool",
)


def test_the_overseer_may_call_exactly_the_jira_read_tools(canopy_env: CanopyEnv) -> None:
    # Allowed by name after the server's wildcard deny, so a write no pattern names fails closed (TRUST_MODEL T6).
    ruleset = _ruleset(canopy_env, agents.OVERSEER)
    jira = config.DEFAULT_TRACKER_TOOLS["jira"]
    reads = {f"{jira.server}_{read}" for read in jira.allowed}
    tools = (*reads, *(f"{jira.server}_{write}" for write in JIRA_WRITES), "atlassian_someWriteToolNoPatternNames")
    assert {tool for tool in tools if not _opencode_disabled(ruleset, tool)} == reads


@pytest.mark.parametrize(
    ("tool", "allowed"),
    [
        ("linear_list_issues", True),
        ("linear_get_issue", True),
        ("linear_create_issue", False),
        ("linear_update_issue", False),
        ("github_list_issues", False),
        ("github_issue_read", False),
        ("github_pull_request_read", True),
    ],
)
def test_the_overseer_keeps_a_trackers_read_that_a_github_pattern_matches(tool: str, *, allowed: bool) -> None:
    # GitHub's issue reads are denied before the tracker's rules, so a tracker's own `list_issues` is allowed again.
    bundled = (resources.agents_dir() / f"{agents.OVERSEER}.md").read_text()
    linear = agents.McpTools("linear", ("list_issues", "get_issue"))
    rendered = opencode_definitions.render_overseer_reads(bundled, linear, "linear")
    assert _opencode_disabled(_opencode_ruleset(rendered), tool) is not allowed


@pytest.mark.parametrize("provider", ["github", "jira"])
def test_no_tracker_read_tool_reopens_a_github_write(provider: str) -> None:
    # The tracker's rules sit above the denials by name (D021): GitHub's read tools hold the PR writes a private worker
    # needs, and an operator's `read_tools` may name anything.
    bundled = (resources.agents_dir() / f"{agents.OVERSEER}.md").read_text()
    writes = ("create_pull_request", "update_pull_request", "add_reply_to_pull_request_comment", "issue_write")
    for server in ("github", "atlassian"):
        tools = agents.McpTools(server, writes)
        ruleset = _opencode_ruleset(opencode_definitions.render_overseer_reads(bundled, tools, provider))
        for write in writes:
            assert _opencode_disabled(ruleset, f"{server}_{write}"), (server, write)


def test_with_no_tracker_tools_known_the_overseer_keeps_the_trackers_and_githubs_issue_reads() -> None:
    # Nothing is rendered: with no names to allow again, a pattern could take a read the overseer needs.
    bundled = (resources.agents_dir() / f"{agents.OVERSEER}.md").read_text()
    assert opencode_definitions.render_overseer_reads(bundled, None, "linear") == bundled
    ruleset = _opencode_ruleset(bundled)
    for tool in ("linear_list_issues", "linear_get_issue", *GITHUB_ISSUE_READS):
        assert not _opencode_disabled(ruleset, tool), tool


def test_the_reviewer_may_call_exactly_the_jira_read_tools(canopy_env: CanopyEnv) -> None:
    # It reads the ticket and posts nothing (DESIGN §21, TRUST_MODEL T6): Atlassian's `execute` tools, which run any
    # other by name, and a tool no pattern names fail closed under the server's wildcard deny.
    ruleset = _ruleset(canopy_env, agents.REVIEWER)
    jira = config.DEFAULT_TRACKER_TOOLS["jira"]
    reads = {f"{jira.server}_{read}" for read in jira.allowed}
    tools = (*reads, *(f"{jira.server}_{write}" for write in JIRA_WRITES), "atlassian_getConfluencePage")
    assert {tool for tool in tools if not _opencode_disabled(ruleset, tool)} == reads


@pytest.mark.parametrize(("provider", "issues"), [("jira", False), ("github", True)])
def test_the_reviewer_is_sent_githubs_issue_reads_only_when_they_are_the_tickets(
    canopy_env: CanopyEnv,
    provider: str,
    *,
    issues: bool,
) -> None:
    # It reads the PR, its discussion among it, with `pull_request_read`, and the ticket through the tracker's server.
    # On a GitHub tracker that server is the PR's too, so its GitHub tools stay as shipped.
    _set_provider(canopy_env, provider)
    sent = {tool for tool in GITHUB_TOOLS if not _opencode_disabled(_ruleset(canopy_env, agents.REVIEWER), tool)}
    shipped = _opencode_ruleset((resources.agents_dir() / f"{agents.REVIEWER}.md").read_text())
    expected = {tool for tool in GITHUB_TOOLS if not _opencode_disabled(shipped, tool)}
    assert sent == (expected if issues else expected - GITHUB_ISSUE_READS)
    assert {"github_pull_request_read", "github_get_commit", "github_list_commits"} <= sent
    # Nor what only filing or labelling an issue needs: it writes nothing.
    assert not {"github_list_issue_types", "github_list_issue_fields", "github_get_label"} & sent


@pytest.mark.parametrize(
    ("tool", "allowed"),
    [
        ("linear_list_issues", True),
        ("linear_get_issue", True),
        ("linear_create_issue", False),
        ("linear_add_comment", False),
        ("linear_save_comment", False),
        ("github_list_issues", False),
        ("github_pull_request_read", True),
    ],
)
def test_the_reviewer_keeps_a_trackers_reads_and_no_write_its_read_tools_name(tool: str, *, allowed: bool) -> None:
    # The tracker's rules sit above the reviewer's patterns (D021), so an operator's `read_tools` that names a write
    # reopens none they close, and the tracker's writes canopy knows are left out of the allows.
    bundled = (resources.agents_dir() / f"{agents.REVIEWER}.md").read_text()
    linear = agents.McpTools("linear", ("list_issues", "get_issue", "create_issue", "add_comment"), ("create_issue",))
    ruleset = _opencode_ruleset(opencode_definitions.render_reviewer_reads(bundled, linear, "linear"))
    assert _opencode_disabled(ruleset, tool) is not allowed


def test_with_no_tracker_tools_known_the_reviewer_is_rendered_as_shipped() -> None:
    # Nothing is rendered, as for the overseer: with no names to allow again, a pattern could take a read it needs.
    bundled = (resources.agents_dir() / f"{agents.REVIEWER}.md").read_text()
    assert opencode_definitions.render_reviewer_reads(bundled, None, "linear") == bundled


def test_the_chore_may_call_exactly_the_jira_read_tools(canopy_env: CanopyEnv) -> None:
    # As the reviewer: OpenCode sends none of the server's other tools, Confluence's among them, and a write no pattern
    # names fails closed under the wildcard deny (TRUST_MODEL T6).
    ruleset = _ruleset(canopy_env, agents.CHORE)
    jira = config.DEFAULT_TRACKER_TOOLS["jira"]
    reads = {f"{jira.server}_{read}" for read in jira.allowed}
    tools = (*reads, *(f"{jira.server}_{write}" for write in JIRA_WRITES), "atlassian_getConfluencePage")
    assert {tool for tool in tools if not _opencode_disabled(ruleset, tool)} == reads


@pytest.mark.parametrize("provider", ["jira", "github"])
def test_the_chore_is_sent_githubs_reads_whatever_the_tracker(canopy_env: CanopyEnv, provider: str) -> None:
    # Its prompt is the operator's, which may read GitHub's issues even when they are not the tickets.
    _set_provider(canopy_env, provider)
    sent = {tool for tool in GITHUB_TOOLS if not _opencode_disabled(_ruleset(canopy_env, agents.CHORE), tool)}
    shipped = _opencode_ruleset((resources.agents_dir() / f"{agents.CHORE}.md").read_text())
    assert sent == {tool for tool in GITHUB_TOOLS if not _opencode_disabled(shipped, tool)}
    assert sent >= GITHUB_ISSUE_READS


#: The tracker's tools each agent's prompt names, by provider: a run must be sent each.
JIRA = config.DEFAULT_TRACKER_TOOLS["jira"]
JIRA_READS = frozenset(f"{JIRA.server}_{read}" for read in JIRA.allowed)
PROMPT_TRACKER_TOOLS: dict[tuple[str, str], AbstractSet[str]] = {
    (agents.OVERSEER, "jira"): JIRA_READS,
    (agents.WORKER, "jira"): JIRA_READS
    | {
        f"atlassian_{tool}" for tool in ("addCommentToJiraIssue", "editJiraIssue", "createJiraIssue", "createIssueLink")
    },
    (agents.PRIVATE_WORKER, "jira"): JIRA_READS | {"atlassian_createJiraIssue"},
    (agents.REVIEWER, "jira"): JIRA_READS,
    (agents.PLANNER, "jira"): JIRA_READS,
    (agents.CHORE, "jira"): JIRA_READS,
    (agents.OVERSEER, "github"): GITHUB_ISSUE_READS,
    (agents.WORKER, "github"): GITHUB_ISSUE_READS | {"github_issue_write"},
    (agents.PRIVATE_WORKER, "github"): GITHUB_ISSUE_READS | {"github_issue_write"},
    (agents.REVIEWER, "github"): GITHUB_ISSUE_READS,
    (agents.PLANNER, "github"): GITHUB_ISSUE_READS,
    (agents.CHORE, "github"): GITHUB_ISSUE_READS,
}
#: GitHub's tools each agent's prompt names for its PRs, whatever the tracker.
PROMPT_GITHUB_TOOLS: dict[str, AbstractSet[str]] = {
    agents.OVERSEER: OVERSEER_GITHUB_READS,
    agents.WORKER: {"github_pull_request_read", "github_create_pull_request", "github_update_pull_request"},
    agents.PRIVATE_WORKER: {"github_pull_request_read", "github_create_pull_request", "github_update_pull_request"},
    agents.REVIEWER: {"github_pull_request_read", "github_get_commit", "github_list_commits"},
    agents.PLANNER: {"github_pull_request_read"},
    agents.CHORE: {"github_pull_request_read", "github_list_pull_requests", "github_get_commit", "github_list_tags"},
}


@pytest.mark.parametrize(("agent", "provider"), sorted(PROMPT_TRACKER_TOOLS))
def test_each_agent_is_sent_each_tool_its_prompt_names(canopy_env: CanopyEnv, agent: str, provider: str) -> None:
    # The rules leave out every tool no prompt asks for; a run that lost one its prompt names would fail on it, with
    # `tool not found`. On defaults, workers drafting their PR replies.
    _set_provider(canopy_env, provider)
    ruleset = _ruleset(canopy_env, agent)
    named = PROMPT_TRACKER_TOOLS[agent, provider] | PROMPT_GITHUB_TOOLS[agent]
    assert sorted(tool for tool in named if _opencode_disabled(ruleset, tool)) == []


#: GitHub's tools the planner may call when the tracker is GitHub: its reads of issues and PRs,
#: and the signed-in user. The code they read in their desks.
PLANNER_GITHUB_READS = {
    "github_get_me",
    "github_issue_read",
    "github_list_issues",
    "github_search_issues",
    "github_list_issue_types",
    "github_get_label",
    "github_pull_request_read",
    "github_list_pull_requests",
    "github_search_pull_requests",
}
#: The tools the private worker opens, updates, and replies on its PRs with, through GitHub's server.
GITHUB_PR_WRITES = ("create_pull_request", "update_pull_request", "add_reply_to_pull_request_comment")


def test_with_a_github_tracker_the_planner_reads_and_writes_nothing(canopy_env: CanopyEnv) -> None:
    # GitHub's server is the tracker's, the one the private worker's PRs go through too: of its tools, the planner gets
    # only the reads (DESIGN §25, TRUST_MODEL T6).
    canopy_env.configure(canopy_env.shared_file, {"tracker": {"provider": "github"}})
    path = f"agents/{agents.PLANNER}.md"
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[path].decode()
    rules = _rules_in(rendered)
    assert {tool for tool in GITHUB_TOOLS if _allowed(rules, tool)} == PLANNER_GITHUB_READS


def test_the_planner_gets_no_write_canopy_knows_from_an_operators_read_tools(canopy_env: CanopyEnv) -> None:
    # An operator's list as canopy's default for GitHub once was, the private worker's PR tools among the reads, and
    # its create tool too.
    canopy_env.configure(canopy_env.shared_file, {"tracker": {"provider": "github"}})
    read_tools = ["issue_read", *GITHUB_PR_WRITES, "issue_write"]
    canopy_env.configure(canopy_env.user_file, {"tracker": {"read_tools": read_tools}})
    # Its replies posted, so that the private worker keeps the reply tool: drafting them denies it.
    canopy_env.write_private('[trust]\nreview_replies = "post"\n')
    files = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))
    rules = _rules_in(files[f"agents/{agents.PLANNER}.md"].decode())
    assert [tool for tool in read_tools if _allowed(rules, f"github_{tool}")] == ["issue_read"]
    private = _rules_in(files[f"agents/{agents.PRIVATE_WORKER}.md"].decode())
    assert [tool for tool in read_tools if _allowed(private, f"github_{tool}")] == read_tools


@pytest.mark.parametrize("agent", [agents.PLANNER, agents.PRIVATE_WORKER])
def test_an_operators_read_tools_leave_the_private_worker_its_pr_tools(canopy_env: CanopyEnv, agent: str) -> None:
    # `tracker.read_tools` names the reads; the PR tools are the provider's, as its create tools are.
    canopy_env.configure(canopy_env.shared_file, {"tracker": {"provider": "github"}})
    canopy_env.configure(canopy_env.user_file, {"tracker": {"read_tools": ["issue_read"]}})
    canopy_env.write_private('[trust]\nreview_replies = "post"\n')
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[f"agents/{agent}.md"].decode()
    rules = _rules_in(rendered)
    assert _allowed(rules, "github_issue_read")
    assert not _allowed(rules, "github_list_issues")
    for tool in GITHUB_PR_WRITES:
        assert _allowed(rules, f"github_{tool}") is (agent == agents.PRIVATE_WORKER), tool


def test_the_overseer_has_no_todo_list_and_no_skill_tool_with_the_trackers_skill_in_its_body() -> None:
    # The prompt has it load the tracker's skill by name only where canopy ships none, so the skill tool stays then.
    bundled = (resources.agents_dir() / f"{agents.OVERSEER}.md").read_text()
    with_skill = _opencode_ruleset(opencode_definitions.render_overseer(bundled, "Decide.\n", "The skill."))
    without = _opencode_ruleset(opencode_definitions.render_overseer(bundled, "Decide.\n", None))
    assert _opencode_disabled(with_skill, "todowrite")
    assert _opencode_disabled(without, "todowrite")
    assert _opencode_disabled(with_skill, "skill")
    assert not _opencode_disabled(without, "skill")


@pytest.mark.parametrize(
    ("agent", "provider", "tracker_posts", "issue_comments"),
    [
        ("canopy-worker", "jira", False, True),
        ("canopy-worker", "jira", True, False),
        (agents.PRIVATE_WORKER, "jira", False, False),
        # GitHub's server is the tracker's then, and the tracker's rules allow the private worker its PR tools by name:
        # the reply tool among them is denied after them.
        (agents.PRIVATE_WORKER, "github", False, False),
    ],
)
def test_under_approve_workers_lose_the_tools_that_comment(
    canopy_env: CanopyEnv,
    agent: str,
    provider: str,
    *,
    tracker_posts: bool,
    issue_comments: bool,
) -> None:
    """Under `trust.review_replies = "approve"` a worker drafts its comments (DESIGN §29); denied by name in depth."""
    path = f"agents/{agent}.md"
    canopy_env.configure(canopy_env.shared_file, {"tracker": {"provider": provider}})
    canopy_env.write_private('[trust]\nreview_replies = "post"\n')
    before = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[path].decode()
    assert _allowed(_rules_in(before), "github_add_reply_to_pull_request_comment")
    # The private worker's bash already denies every `gh` command but those that read a PR.
    assert _allowed(_rules_in(before, "bash"), "gh pr comment 7 --body x") is (agent == "canopy-worker")
    tracker = '\n[connect.sources.issues]\nkind = "tracker"\npost_cmd = "canopy-post-github"\n'
    canopy_env.write_private('[trust]\nreview_replies = "approve"\n' + (tracker if tracker_posts else ""))
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[path].decode()
    tools, bash = _rules_in(rendered), _rules_in(rendered, "bash")
    assert not _allowed(tools, "github_add_reply_to_pull_request_comment")
    assert not _allowed(tools, "github_add_comment_to_pending_review")
    assert not _allowed(bash, "gh pr comment 7 --body x")
    assert _allowed(tools, "github_add_issue_comment") is issue_comments
    assert _allowed(bash, "gh issue comment 1 --body x") is issue_comments
    assert _allowed(tools, "github_create_pull_request")
    assert _allowed(tools, "github_update_pull_request")
    assert _allowed(bash, "git push origin HEAD:refs/heads/agent/PROJ-1-x")
