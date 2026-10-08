"""The snapshot agent runs load canopy's agents and skills from, and the guard against shadowing them (D040, D044)."""

import fnmatch
import os
import shutil
import time
from pathlib import Path

import pytest

from canopy.core import definitions
from canopy.infra import resources


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


def test_losing_the_race_to_create_a_snapshot_uses_the_winners(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = tmp_path / "runtime" / definitions.digest()
    real_rename = os.rename

    def another_process_wins(src: Path, dst: Path) -> None:
        shutil.copytree(src, final)
        (final / "winner").touch()
        real_rename(src, dst)  # refused: dst is a directory that is not empty

    monkeypatch.setattr(os, "rename", another_process_wins)
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


def _mcp_rules(agent: str) -> list[tuple[str, str]]:
    """The agent's top-level quoted permission rules, in order: OpenCode's patterns for MCP tool names."""
    frontmatter = (resources.agents_dir() / f"{agent}.md").read_text().split("---")[1]
    rules: list[tuple[str, str]] = []
    for line in frontmatter.splitlines():
        if line.startswith('  "'):
            pattern, action = line.strip().rsplit(":", 1)
            rules.append((pattern.strip('"'), action.strip()))
    return rules


def _allowed(rules: list[tuple[str, str]], tool: str) -> bool:
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
    assert not _allowed(_mcp_rules(agent), tool)


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
    assert _allowed(_mcp_rules(agent), tool)


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
    assert _allowed(_mcp_rules("canopy-worker"), tool)
