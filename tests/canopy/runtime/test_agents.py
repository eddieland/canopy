"""canopy's agent definitions in OpenCode's format: what is rendered into them, and a file that cannot take it."""

from dataclasses import replace

import pytest

from canopy.infra import resources
from canopy.runtime import agents

PROMPT_MARKER = "<!-- canopy: overseer prompt -->\n"
TEMPERATURE_AGENTS = [agents.REVIEWER, agents.OVERSEER, agents.PLAN_TRIAGE]


def test_the_bundled_files_are_the_agents_and_skills_by_their_place_in_a_config_directory() -> None:
    files = agents.bundled()
    for name in agents.agent_names():
        assert files[f"agents/{name}.md"] == (resources.agents_dir() / f"{name}.md").read_bytes()
    for skill in resources.skills_dir().iterdir():
        assert files[f"skills/{skill.name}/SKILL.md"] == (skill / "SKILL.md").read_bytes()
    assert agents.WORKER in agents.agent_names()
    assert agents.OVERSEER in agents.agent_names()


#: Rules that render nothing but the overseer's prompt; a test replaces what it renders.
PLAIN = agents.Rules(
    tracker_tools=None,
    rebase=False,
    worker_drafts=agents.Drafts(approve=False, ticket_comments=True),
    private_drafts=agents.Drafts(approve=False, ticket_comments=False),
    temperatures={},
    overseer_prompt="Decide.\n",
    tracker_provider="no-such-tracker",
)


def test_render_writes_the_rules_into_the_agents_it_names() -> None:
    files = agents.bundled()
    rendered = agents.render(
        files,
        replace(
            PLAIN,
            tracker_tools=agents.McpTools("tracker", ("read",)),
            rebase=True,
            worker_drafts=agents.Drafts(approve=True, ticket_comments=True),
            temperatures={agents.REVIEWER: 0.3, agents.OVERSEER: None},
        ),
    )
    text = {name: rendered[f"agents/{name}.md"].decode() for name in agents.agent_names()}
    assert '  "tracker_*": deny\n  "tracker_read": allow\n' in text[agents.PRIVATE_WORKER]
    assert '  "tracker_read": allow\n' in text[agents.PLANNER]
    assert "--force-with-lease" in text[agents.WORKER]
    assert '"*reply_to_pull_request_comment*": deny' in text[agents.WORKER]
    assert '"*reply_to_pull_request_comment*": deny' not in text[agents.PRIVATE_WORKER]
    assert "\ntemperature: 0.3\n" in text[agents.REVIEWER]
    assert "\ntemperature:" not in text[agents.OVERSEER]
    assert text[agents.OVERSEER].endswith("---\n\nDecide.\n")
    # What the rules do not name stays as shipped, and the input is left as it was.
    assert rendered[f"agents/{agents.SPLITTER}.md"] == files[f"agents/{agents.SPLITTER}.md"]
    assert files == agents.bundled()


def test_the_overseer_gets_the_trackers_skill_when_canopy_ships_one() -> None:
    files = {
        "agents/canopy-overseer.md": f"---\nx: y\n---\n{PROMPT_MARKER}".encode(),
        "skills/tracker-jira/SKILL.md": b"---\nname: tracker-jira\n---\nUse JQL.\n",
    }
    overseer = agents.render(files, replace(PLAIN, tracker_provider="jira"))["agents/canopy-overseer.md"].decode()
    skill = "The skill `tracker-jira` follows, given here so that you need not load it.\n\nUse JQL.\n"
    assert overseer == f"---\nx: y\n---\nDecide.\n\n{skill}"


@pytest.mark.parametrize("agent", TEMPERATURE_AGENTS)
def test_a_definition_without_its_temperature_line_is_refused(agent: str) -> None:
    bundled = (resources.agents_dir() / f"{agent}.md").read_text()
    with pytest.raises(agents.DefinitionsError, match="no line"):
        agents.render_temperature(bundled.replace("# canopy: temperature\n", ""), agent, 0.1)


def test_a_worker_definition_without_its_rebase_line_is_refused() -> None:
    bundled = (resources.agents_dir() / "canopy-worker.md").read_text()
    with pytest.raises(agents.DefinitionsError, match="no line"):
        agents.render_rebase(bundled.replace("    # canopy: rebase rules\n", ""), "canopy-worker", rebase=False)


def test_the_overseer_prompt_stands_alone_without_a_skill_for_its_tracker() -> None:
    head = f"---\ndescription: x\n---\n\n{PROMPT_MARKER}"
    assert agents.render_overseer(f"{head}stub\n", "# canopy overseer\n\nDecide.\n", None) == (
        "---\ndescription: x\n---\n\n# canopy overseer\n\nDecide.\n"
    )


def test_an_overseer_definition_without_its_marked_line_is_refused() -> None:
    bundled = (resources.agents_dir() / "canopy-overseer.md").read_text()
    with pytest.raises(agents.DefinitionsError, match="no line"):
        agents.render_overseer(bundled.replace(PROMPT_MARKER, ""), "# canopy overseer\n", None)


def test_a_worker_definition_without_its_reply_lines_is_refused() -> None:
    bundled = (resources.agents_dir() / "canopy-worker.md").read_text()
    with pytest.raises(agents.DefinitionsError, match="reply rules"):
        agents.render_replies(
            bundled.replace("  # canopy: reply tools\n", ""), "canopy-worker", approve=False, ticket_comments=True
        )
