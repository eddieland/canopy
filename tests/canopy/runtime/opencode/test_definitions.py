"""canopy's agent definitions in OpenCode's format: what is rendered into them, and a file that cannot take it."""

from collections.abc import Callable
from dataclasses import replace

import pytest

from canopy.infra import resources
from canopy.runtime import agents
from canopy.runtime.opencode import definitions

PROMPT_MARKER = "<!-- canopy: overseer prompt -->\n"
SKILL_MARKER = "    # canopy: skill rule\n"
READS_MARKER = "  # canopy: tracker reads\n"
TEMPERATURE_AGENTS = [agents.REVIEWER, agents.OVERSEER]


def test_the_bundled_files_are_the_agents_and_skills_by_their_place_in_a_config_directory() -> None:
    files = definitions.bundled()
    for name in definitions.agent_names():
        assert files[f"agents/{name}.md"] == (resources.agents_dir() / f"{name}.md").read_bytes()
    for skill in resources.skills_dir().iterdir():
        assert files[f"skills/{skill.name}/SKILL.md"] == (skill / "SKILL.md").read_bytes()
    assert agents.WORKER in definitions.agent_names()
    assert agents.OVERSEER in definitions.agent_names()


#: Rules that render nothing but the overseer's prompt; a test replaces what it renders.
PLAIN = agents.Rules(
    tracker_tools=None,
    rebase=False,
    worker_drafts=agents.Drafts(approve=False, ticket_comments=True),
    private_drafts=agents.Drafts(approve=False, ticket_comments=False),
    temperatures={},
    overseer_prompt="Decide.\n",
    tracker_provider="no-such-tracker",
    bash_allows={},
)


def test_render_writes_the_rules_into_the_agents_it_names() -> None:
    files = definitions.bundled()
    rendered = definitions.render(
        files,
        replace(
            PLAIN,
            tracker_tools=agents.McpTools("tracker", ("read",)),
            rebase=True,
            worker_drafts=agents.Drafts(approve=True, ticket_comments=True),
            temperatures={agents.REVIEWER: 0.3, agents.OVERSEER: None},
        ),
    )
    text = {name: rendered[f"agents/{name}.md"].decode() for name in definitions.agent_names()}
    assert '  "tracker_*": deny\n  "tracker_read": allow\n' in text[agents.PRIVATE_WORKER]
    assert '  "tracker_read": allow\n' in text[agents.PLANNER]
    # The overseer reads it too, and denies GitHub's issue reads, which are no tracker's but GitHub's.
    assert (
        f'{READS_MARKER}  "*issue_read*": deny\n  "*list_issues*": deny\n  "*search_issues*": deny\n'
        '  "tracker_*": deny\n  "tracker_read": allow\n'
    ) in text[agents.OVERSEER]
    # So does the reviewer, ahead of its patterns.
    assert (
        f'{READS_MARKER}  "*issue_read*": deny\n  "*list_issues*": deny\n  "*search_issues*": deny\n'
        '  "tracker_*": deny\n  "tracker_read": allow\n'
    ) in text[agents.REVIEWER]
    assert "--force-with-lease" in text[agents.WORKER]
    assert '"*reply_to_pull_request_comment*": deny' in text[agents.WORKER]
    assert '"*reply_to_pull_request_comment*": deny' not in text[agents.PRIVATE_WORKER]
    # And the chore, keeping GitHub's issue reads: its prompt is the operator's.
    assert f'{READS_MARKER}  "tracker_*": deny\n  "tracker_read": allow\n' in text[agents.CHORE]
    assert "\ntemperature: 0.3\n" in text[agents.REVIEWER]
    assert "\ntemperature:" not in text[agents.OVERSEER]
    assert text[agents.OVERSEER].endswith("---\n\nDecide.\n")
    # The input is left as it was.
    assert files == definitions.bundled()


def test_the_overseer_gets_the_trackers_skill_when_canopy_ships_one_and_no_skill_tool() -> None:
    # With the skill in its body there is nothing left to load, and OpenCode sends no tool a rule denies whole.
    files = {
        "agents/canopy-overseer.md": f"---\npermission:\n{SKILL_MARKER}{READS_MARKER}---\n{PROMPT_MARKER}".encode(),
        "skills/tracker-jira/SKILL.md": b"---\nname: tracker-jira\n---\nUse JQL.\n",
    }
    overseer = definitions.render(files, replace(PLAIN, tracker_provider="jira"))["agents/canopy-overseer.md"].decode()
    skill = "The skill `tracker-jira` follows, given here so that you need not load it.\n\nUse JQL.\n"
    assert overseer == f'---\npermission:\n{SKILL_MARKER}    "*": deny\n{READS_MARKER}---\nDecide.\n\n{skill}'


@pytest.mark.parametrize("agent", TEMPERATURE_AGENTS)
def test_a_definition_without_its_temperature_line_is_refused(agent: str) -> None:
    bundled = (resources.agents_dir() / f"{agent}.md").read_text()
    with pytest.raises(agents.DefinitionsError, match="no line"):
        definitions.render_temperature(bundled.replace("# canopy: temperature\n", ""), agent, 0.1)


def test_a_worker_definition_without_its_rebase_line_is_refused() -> None:
    bundled = (resources.agents_dir() / "canopy-worker.md").read_text()
    with pytest.raises(agents.DefinitionsError, match="no line"):
        definitions.render_rebase(bundled.replace("    # canopy: rebase rules\n", ""), "canopy-worker", rebase=False)


def test_the_overseer_prompt_stands_alone_without_a_skill_for_its_tracker_and_keeps_its_skill_tool() -> None:
    # The prompt has it load the tracker's skill by name, if one is installed, so the skill tool stays.
    head = f"---\npermission:\n{SKILL_MARKER}---\n\n{PROMPT_MARKER}"
    assert definitions.render_overseer(f"{head}stub\n", "# canopy overseer\n\nDecide.\n", None) == (
        f"---\npermission:\n{SKILL_MARKER}---\n\n# canopy overseer\n\nDecide.\n"
    )


@pytest.mark.parametrize("marker", [PROMPT_MARKER, SKILL_MARKER])
def test_an_overseer_definition_without_a_marked_line_is_refused(marker: str) -> None:
    bundled = (resources.agents_dir() / "canopy-overseer.md").read_text()
    with pytest.raises(agents.DefinitionsError, match="no line"):
        definitions.render_overseer(bundled.replace(marker, ""), "# canopy overseer\n", None)


@pytest.mark.parametrize("tools", [None, agents.McpTools("github", ("issue_read",))])
def test_an_overseer_definition_without_its_tracker_reads_line_is_refused(tools: agents.McpTools | None) -> None:
    bundled = (resources.agents_dir() / "canopy-overseer.md").read_text()
    with pytest.raises(agents.DefinitionsError, match="tracker reads"):
        definitions.render_overseer_reads(bundled.replace(READS_MARKER, ""), tools, "github")


#: The agents whose tracker reads are rendered as the reviewer's, and the function that renders them.
READERS: dict[str, Callable[[str, agents.McpTools | None, str], str]] = {
    agents.REVIEWER: definitions.render_reviewer_reads,
    agents.CHORE: definitions.render_chore_reads,
}


@pytest.mark.parametrize("agent", sorted(READERS))
@pytest.mark.parametrize("tools", [None, agents.McpTools("tracker", ("read",))])
def test_a_readers_definition_without_its_tracker_reads_line_is_refused(
    agent: str,
    tools: agents.McpTools | None,
) -> None:
    bundled = (resources.agents_dir() / f"{agent}.md").read_text()
    with pytest.raises(agents.DefinitionsError, match=rf"{agent}\.md has no line"):
        READERS[agent](bundled.replace(READS_MARKER, ""), tools, "jira")


@pytest.mark.parametrize("agent", sorted(READERS))
def test_a_github_tracker_leaves_a_readers_rules_as_shipped(agent: str) -> None:
    # The server is the one it reads PRs through; its patterns govern it.
    bundled = (resources.agents_dir() / f"{agent}.md").read_text()
    assert READERS[agent](bundled, agents.McpTools("github", ("issue_read",)), "github") == bundled


def test_the_chore_keeps_githubs_issue_reads_off_a_github_tracker() -> None:
    # Unlike the reviewer's: a chore's prompt is the operator's, and may read GitHub's issues whatever the tracker.
    bundled = (resources.agents_dir() / f"{agents.CHORE}.md").read_text()
    rendered = definitions.render_chore_reads(bundled, agents.McpTools("atlassian", ("getJiraIssue",)), "jira")
    rules = rendered.split(READS_MARKER, 1)[1].split("  # ", 1)[0]
    assert rules == '  "atlassian_*": deny\n  "atlassian_getJiraIssue": allow\n'


def test_a_github_tracker_gives_the_overseer_its_own_reads_of_github() -> None:
    # The provider's read tools there hold the PR writes a private worker needs; GitHub's issue reads stay.
    bundled = (resources.agents_dir() / "canopy-overseer.md").read_text()
    tools = agents.McpTools("gh", ("create_pull_request", "issue_read"))
    rendered = definitions.render_overseer_reads(bundled, tools, "github")
    rules = rendered.split(READS_MARKER, 1)[1].split("  # ", 1)[0]
    assert rules == (
        '  "gh_*": deny\n  "gh_get_me": allow\n  "gh_issue_read": allow\n  "gh_list_issues": allow\n'
        '  "gh_search_issues": allow\n  "gh_pull_request_read": allow\n  "gh_list_pull_requests": allow\n'
        '  "gh_search_pull_requests": allow\n  "gh_list_branches": allow\n'
    )


def test_a_worker_definition_without_its_reply_lines_is_refused() -> None:
    bundled = (resources.agents_dir() / "canopy-worker.md").read_text()
    with pytest.raises(agents.DefinitionsError, match="reply rules"):
        definitions.render_replies(
            bundled.replace("  # canopy: reply tools\n", ""),
            "canopy-worker",
            approve=False,
            ticket_comments=True,
        )


BASH_ALLOWS_MARKER = "    # canopy: bash allows\n"


def test_bash_allows_are_the_last_of_the_overseers_bash_rules() -> None:
    # The last matching rule wins (D021): each allow beats `"*": deny`, and no rule of canopy's comes after to beat it.
    allows = ("jira issue list *", "jira issue view *")
    rendered = definitions.render(definitions.bundled(), replace(PLAIN, bash_allows={agents.OVERSEER: allows}))
    text = rendered[f"agents/{agents.OVERSEER}.md"].decode()
    bash = text.split("\n  bash:\n", 1)[1].split("\n  todowrite:", 1)[0]
    rules = [line for line in bash.splitlines() if line.startswith('    "')]
    # The overseer has no shell of its own (DESIGN §27): only the operator's allows follow the deny.
    assert rules == [
        '    "*": deny',
        '    "jira issue list *": allow',
        '    "jira issue view *": allow',
    ]
    assert f'{BASH_ALLOWS_MARKER}    "jira issue list *": allow\n    "jira issue view *": allow\n  #' in text


def test_no_bash_allows_render_the_overseer_as_none_did() -> None:
    files = definitions.bundled()
    none = definitions.render(files, PLAIN)
    assert definitions.render(files, replace(PLAIN, bash_allows={agents.OVERSEER: ()})) == none
    assert f"{BASH_ALLOWS_MARKER}  #" in none[f"agents/{agents.OVERSEER}.md"].decode()


@pytest.mark.parametrize("agent", [agents.WORKER, agents.PRIVATE_WORKER, agents.PLANNER, agents.REVIEWER, agents.CHORE])
def test_no_other_shipped_agent_takes_bash_allows(agent: str) -> None:
    # A worker's shell runs every command but those it denies, which an allow could only undo; the rest have none.
    rules = replace(PLAIN, bash_allows={agent: ("jira issue list *",)})
    with pytest.raises(agents.DefinitionsError, match=rf"{agent}\.md has no line '# canopy: bash allows'"):
        definitions.render(definitions.bundled(), rules)


@pytest.mark.parametrize("allow", ['jira": allow\n    "*', "sh -c 'x'", "*", "jira issue list ", ""])
def test_a_bash_allow_canopy_would_not_render_is_refused(allow: str) -> None:
    rules = replace(PLAIN, bash_allows={agents.OVERSEER: (allow,)})
    with pytest.raises(agents.DefinitionsError, match="is not a bash rule canopy renders"):
        definitions.render(definitions.bundled(), rules)
