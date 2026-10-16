"""The snapshot agent runs load canopy's agents and skills from, and the guard against shadowing them (D040, D044)."""

import fnmatch
import os
import shutil
import time
from collections.abc import Iterable
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import config, definitions, plans
from canopy.infra import resources
from tests.conftest import CanopyEnv

PROMPT_MARKER = "<!-- canopy: overseer prompt -->\n"


def test_the_snapshot_holds_the_bundled_agents_and_skills(tmp_path: Path) -> None:
    snapshot = definitions.ensure(tmp_path)
    assert snapshot == tmp_path / "runtime" / definitions.digest()
    for name in definitions.agent_names():
        bundled = resources.agents_dir() / f"{name}.md"
        assert (snapshot / "agents" / f"{name}.md").read_text() == bundled.read_text()
    for skill in resources.skills_dir().iterdir():
        assert (snapshot / "skills" / skill.name / "SKILL.md").read_text() == (skill / "SKILL.md").read_text()
    assert "canopy-worker" in definitions.agent_names()
    assert "canopy-overseer" in definitions.agent_names()


@pytest.mark.parametrize("name", definitions.agent_names())
def test_no_agent_has_web_tools(name: str) -> None:
    # Fetched and searched pages are text anyone can shape (TRUST_MODEL T1, D077). Scalars, so a repository's config
    # cannot loosen them (D044).
    frontmatter = (resources.agents_dir() / f"{name}.md").read_text().split("---")[1]
    for tool in ("webfetch", "websearch", "codesearch"):
        assert f"\n  {tool}: deny\n" in frontmatter


def test_the_operator_skill_is_not_in_the_snapshot(tmp_path: Path) -> None:
    # It is for the operator's own sessions; an operator's copy of it in $HOME would clash with a second one here.
    snapshot = definitions.ensure(tmp_path)
    names = [p.name for p in (snapshot / "skills").iterdir()]
    assert "canopy" not in names
    assert names


def test_an_existing_snapshot_is_reused_as_is(tmp_path: Path) -> None:
    snapshot = definitions.ensure(tmp_path)
    # OpenCode writes into the directory it loads; that must not make canopy copy again.
    (snapshot / "node_modules").mkdir()
    assert definitions.ensure(tmp_path) == snapshot
    assert (snapshot / "node_modules").is_dir()
    assert [p.name for p in (tmp_path / "runtime").iterdir()] == [snapshot.name]


def test_losing_the_race_to_create_a_snapshot_uses_the_winners(tmp_path: Path) -> None:
    final = tmp_path / "runtime" / definitions.digest()
    real_rename = os.rename

    def another_process_wins(src: Path, dst: Path) -> None:
        shutil.copytree(src, final)
        (final / "winner").touch()
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
    stale_tmp = runtime / ".tmp-stale"
    stale_tmp.mkdir()
    hours_ago = time.time() - 2 * 3600
    os.utime(stale_tmp, (hours_ago, hours_ago))

    assert definitions.prune(tmp_path, current) == [stale_tmp, old]
    assert sorted(p.name for p in runtime.iterdir()) == sorted([current.name, fresh_tmp.name])


def test_prune_without_a_runtime_directory(tmp_path: Path) -> None:
    assert definitions.prune(tmp_path, tmp_path / "runtime" / "x") == []


@pytest.mark.parametrize(
    "rel",
    [
        ".opencode/agent/canopy-worker.md",
        ".opencode/agents/canopy-overseer.md",
        ".opencode/mode/canopy-worker.md",
        ".opencode/modes/canopy-worker.md",
    ],
)
def test_shadowing_finds_an_agent_file_with_a_canopy_name(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("---\ndescription: x\n---\n")
    assert definitions.shadowing(tmp_path) == [path]


@pytest.mark.parametrize(
    "rel",
    [".opencode/agent/my-helper.md", ".opencode/agent/team/canopy-worker.md", ".opencode/skill/canopy-worker/SKILL.md"],
)
def test_shadowing_ignores_other_agents_and_skills(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("---\ndescription: x\n---\n")
    assert definitions.shadowing(tmp_path) == []


@pytest.mark.parametrize(
    "rel", ["opencode.json", "opencode.jsonc", ".opencode/opencode.json", ".opencode/opencode.jsonc"]
)
def test_shadowing_finds_a_json_config_that_names_a_canopy_agent(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"agent": {"canopy-worker": {"permission": {"bash": {"*": "allow"}}}}}')
    assert definitions.shadowing(tmp_path) == [path]


def test_shadowing_accepts_a_json_config_that_does_not(tmp_path: Path) -> None:
    (tmp_path / "opencode.json").write_text('{"mcp": {"docs": {"type": "remote", "url": "https://example.test"}}}')
    assert definitions.shadowing(tmp_path) == []


def test_the_shadowing_message_names_the_files(tmp_path: Path) -> None:
    message = definitions.shadowing_message([tmp_path / "opencode.json"])
    assert str(tmp_path / "opencode.json") in message
    assert "D044" in message


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


@pytest.mark.parametrize("agent", ["canopy-worker", definitions.PRIVATE_WORKER])
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


@pytest.mark.parametrize("agent", ["canopy-worker", definitions.PRIVATE_WORKER])
def test_with_rebase_workers_may_push_with_a_lease_and_no_other_force(canopy_env: CanopyEnv, agent: str) -> None:
    """`trust.rebase` adds the one forced push the prompts name; every other force, and the rest, stay denied."""
    path = f"agents/{agent}.md"
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[path].decode()
    assert not _allowed(_rules_in(rendered, "bash"), LEASED_PUSH)
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[trust]\nrebase = true\n")
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


def test_a_worker_definition_without_its_rebase_line_is_refused() -> None:
    bundled = (resources.agents_dir() / "canopy-worker.md").read_text()
    with pytest.raises(definitions.DefinitionsError, match="no line"):
        definitions.render_rebase(bundled.replace("    # canopy: rebase rules\n", ""), "canopy-worker", rebase=False)


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
        "github_create_issue",
        "github_create_branch",
        "github_push_files",
        "github_delete_file",
        "github_fork_repository",
        "atlassian_transitionJiraIssue",
        "atlassian_createJiraIssue",
    ],
)
@pytest.mark.parametrize("agent", ["canopy-worker", definitions.PRIVATE_WORKER])
def test_workers_deny_dangerous_mcp_tools(agent: str, tool: str) -> None:
    assert not _allowed(_rules(agent), tool)


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
@pytest.mark.parametrize("agent", ["canopy-worker", definitions.PRIVATE_WORKER])
def test_workers_keep_the_pr_tools_they_work_with(agent: str, tool: str) -> None:
    assert _allowed(_rules(agent), tool)


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
    path = f"agents/{definitions.PLANNER}.md"
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[path].decode()
    assert _allowed(_rules_in(rendered), tool) is allowed


def test_the_planner_has_no_shell_or_subagent_tools() -> None:
    frontmatter = (resources.agents_dir() / f"{definitions.PLANNER}.md").read_text().split("---")[1]
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
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[
        f"agents/{definitions.PLANNER}.md"
    ]
    ruleset = _opencode_ruleset(rendered.decode())
    assert _opencode_action(ruleset, "edit", path) == ("allow" if allowed else "deny")


def test_the_planner_keeps_its_edit_tool_and_loses_its_shell(canopy_env: CanopyEnv) -> None:
    # OpenCode leaves a tool out of the model's toolset when the last rule for its permission denies `*`
    # (`Permission.disabled`): a `*edit*` after the edit rules would take away the only way to write the plan.
    rendered = definitions.sources(config.load(canopy_env.root, canopy_env.user_file))[
        f"agents/{definitions.PLANNER}.md"
    ]
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
    head = (resources.agents_dir() / "canopy-overseer.md").read_text().split(PROMPT_MARKER)[0]
    assert text.startswith(head)
    body = text.removeprefix(head)
    prompt = (resources.prompts_dir() / "overseer.md").read_text().strip("\n")
    assert body.startswith(
        f"{prompt}\n\nThe skill `tracker-jira` follows, given here so that you need not load it.\n\n"
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


def test_the_overseer_prompt_stands_alone_without_a_skill_for_its_tracker() -> None:
    head = f"---\ndescription: x\n---\n\n{PROMPT_MARKER}"
    assert definitions.render_overseer(f"{head}stub\n", "# canopy overseer\n\nDecide.\n", None) == (
        "---\ndescription: x\n---\n\n# canopy overseer\n\nDecide.\n"
    )


def test_an_overseer_definition_without_its_marked_line_is_refused() -> None:
    bundled = (resources.agents_dir() / "canopy-overseer.md").read_text()
    with pytest.raises(definitions.DefinitionsError, match="no line"):
        definitions.render_overseer(bundled.replace(PROMPT_MARKER, ""), "# canopy overseer\n", None)
