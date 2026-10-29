"""The skills the mock's runtime finds (DESIGN §13), for the skills page of `python -m canopy.serve --mock`.

One from each place a skill comes from: the tracker's and the artifact store's, which canopy ships, in its definitions
snapshot; a release-notes skill in the workspace's root; the operator's own, in their home; and one the runtime carries
itself. The overseer has no skill tool, so is offered none; only the chore publishes, so only it gets the artifacts
skill; and the private worker's rules, as the operator's config wrote them, deny it the operator's own.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from canopy.runtime import definitions
from canopy.runtime.agents import CHORE, OVERSEER, PRIVATE_WORKER, AgentOffer, Offerings, SkillFile

if TYPE_CHECKING:
    from canopy.core.context import Context

#: The made-up digest the mock's definitions snapshot is named for.
_SNAPSHOT = "definitions-3f9c2a71"
_TRACKER = """# Jira for canopy agents

What is specific to Jira as canopy's tracker, through its MCP server.

## Keys

A ticket's key is its issue key, such as `ABC-102`. Search with JQL, and confirm each result still carries the queue
label before treating it as a candidate.

## Comments

Write a comment in Jira's own markup, not Markdown:

- `{code}` around code, not backticks.
- `[text|url]` for a link.
"""
_ARTIFACTS = """# Artifacts for canopy workers

An artifact is a page you publish for people to read and comment on: a report, a design, an HTML mock-up.

1. Publish it with the store's `publish` tool, once the page is done.
2. Name it in your report, so the operator finds it.
3. Answer its comments as you would a reviewer's.
"""
_RELEASE_NOTES = """# Release notes

When a change is one a user would notice, add a line to `CHANGELOG.md` under `Unreleased`, in the past tense, naming
the ticket: `Fixed the export's dates (ABC-102).`

Leave the changelog alone for a refactor, a test, or a build change.
"""
_TERSE = """# Terse

Say what you did and what is left, in that order, and stop. No preamble, no recap of the ticket, no closing offer.
"""
_WRITE_A_SKILL = """# Writing a skill

Where a skill of your own goes, what its front matter holds, and how to keep its description short enough to be read.
"""


def offerings(ctx: Context) -> Offerings:
    """What the mock's runtime offers each of canopy's agents: five skills, from each place one comes from.

    Returns:
        Its skills, sorted by name, and each agent's share of them.
    """
    root, snapshot = ctx.ws.root, ctx.ws.state_dir / _SNAPSHOT
    files = (
        SkillFile(
            "canopy-artifacts",
            "How canopy workers publish artifacts people comment on, and answer comments. Load before any artifact "
            "tool.",
            str(snapshot / "skills" / "canopy-artifacts" / "SKILL.md"),
            _ARTIFACTS,
        ),
        SkillFile(
            "release-notes",
            "When and how to add a line to the changelog. Load before opening a PR.",
            str(root / ".agents" / "skills" / "release-notes" / "SKILL.md"),
            _RELEASE_NOTES,
        ),
        SkillFile("terse", None, str(Path.home() / ".agents" / "skills" / "terse" / "SKILL.md"), _TERSE),
        SkillFile(
            "tracker-jira",
            "How canopy agents use Jira as the tracker via its MCP server. Load when the provider is jira.",
            str(snapshot / "skills" / "tracker-jira" / "SKILL.md"),
            _TRACKER,
        ),
        SkillFile("write-a-skill", "How to write a skill of your own.", "<built-in>", _WRITE_A_SKILL),
    )
    names = tuple(f.name for f in files)
    return Offerings(
        servers=("jira",),
        skills=names,
        skill_files=files,
        agents=tuple(_offer(agent, names) for agent in definitions.agent_names()),
    )


def _offer(agent: str, skills: tuple[str, ...]) -> AgentOffer:
    if agent == OVERSEER:
        return AgentOffer(agent, denied_skills=skills)
    denied = {"canopy-artifacts"} if agent != CHORE else set[str]()
    if agent == PRIVATE_WORKER:
        denied.add("terse")
    return AgentOffer(
        agent,
        skills=tuple(s for s in skills if s not in denied),
        denied_skills=tuple(s for s in skills if s in denied),
    )
