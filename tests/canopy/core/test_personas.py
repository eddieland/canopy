"""The default persona (DESIGN §31): canopy's own voice, rendered into each planner, reviewer, and worker prompt below
the prompt's obligations, and a prompt override without `{{PERSONA}}` still serving the run."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from canopy.core import prompts
from canopy.core.config import load
from canopy.core.vocab import RunKind
from canopy.infra import resources
from tests.canopy.helpers import PRIVATE_PROMPT_VALUES, PROMPT_VALUES

if TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

    from canopy.core.config import Config
    from tests.conftest import CanopyEnv

#: Each prompt a persona reaches, by the id its snapshot is recorded under.
AGENTS = ["plan", "reviewer", "implement", "implement-private", "resume", "resume-private"]
#: The heading the persona's section opens with in every one of them.
PERSONA = "## Persona\n\n"
#: The values a plan's prompt needs beyond a worker's.
PLAN_VALUES = {
    "AUTHORIZATION": prompts.plan_authorization("PROJ-1", ["agent-ready-alice"], private=False),
    "PLAN_FILE": ".canopy-plan.md",
    "PLAN_OUT": ".canopy-new-plan.md",
    "MAX_PLAN_CHARS": "100,000",
}
#: The values the reviewer's prompt needs.
REVIEWER_VALUES = {
    "PR_URL": "https://example.test/pr/1",
    "SHA": "b" * 40,
    "CHECKOUT": "/state/reviews/1/checkout",
    "RUN_ID": "1",
    "TICKET": "PROJ-1",
    "TRACKER_PROVIDER": "github",
    "LOW_IMPACT": "None: never report `low`.",
    "ATTEMPT": "1",
    "MAX_ATTEMPTS": "3",
    "CONTEXT": "None.",
    "TIMEOUT_MINUTES": "30",
    "CONTRACT": "<the result contract>",
}


@pytest.mark.parametrize("agent", AGENTS)
def test_each_agent_renders_the_canopy_persona_after_its_obligations(
    canopy_env: CanopyEnv, markdown_snapshot: SnapshotAssertion, agent: str
) -> None:
    prompt = _render(load(canopy_env.root, canopy_env.user_file), agent)
    persona = prompts.persona()
    assert prompt.count(persona) == 1
    # The reviewer's obligations are what it does and the shape of its review; a worker's and the planner's are
    # their own section.
    obligations = "## What to do\n" if agent == "reviewer" else "## Obligations\n"
    start = prompt.index(obligations)
    assert start < prompt.index(PERSONA) < prompt.index(persona)
    # From the obligations to the end of the persona's section: what the persona follows, and the line that the
    # prompt comes first.
    end = prompt.index("\n## ", prompt.index(PERSONA) + len(PERSONA))
    assert prompt[start:end] == markdown_snapshot


def test_the_persona_is_the_shipped_file_less_its_surrounding_blank_lines() -> None:
    shipped = (resources.personas_dir() / f"{prompts.DEFAULT_PERSONA}.md").read_text(encoding="utf-8")
    assert prompts.persona() == shipped.strip()


@pytest.mark.parametrize(
    ("agent", "override", "rendered"),
    [
        (
            "implement",
            "Implement {{KEY}} if it carries {{LABELS}}.\n",
            "Implement PROJ-1 if it carries `agent-ready-alice`.\n",
        ),
        (
            "reviewer",
            "Review {{PR_URL}} at {{SHA}} in {{CHECKOUT}}, as an adversary.\n",
            f"Review https://example.test/pr/1 at {'b' * 40} in /state/reviews/1/checkout, as an adversary.\n",
        ),
    ],
)
def test_an_override_without_the_placeholder_still_serves_a_canopy_run(
    canopy_env: CanopyEnv, agent: str, override: str, rendered: str
) -> None:
    # Every run's persona is `canopy` until the operator can choose another, and an override that cannot carry one
    # keeps the voice it already holds.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir(parents=True)
    name = prompts.REVIEWER if agent == "reviewer" else prompts.WORKER[RunKind.IMPLEMENT]
    (overrides / name).write_text(override)
    assert _render(load(canopy_env.root, canopy_env.user_file), agent) == rendered


def _render(cfg: Config, agent: str) -> str:
    # `agent`'s prompt, rendered as a run renders it.
    if agent == "reviewer":
        return prompts.render_reviewer(cfg, REVIEWER_VALUES)
    kind, _, private = agent.partition("-")
    if kind == RunKind.PLAN:
        return prompts.render_worker(cfg, kind, {**PROMPT_VALUES, **PLAN_VALUES})
    if private:
        return prompts.render_worker(
            cfg, kind, {**PRIVATE_PROMPT_VALUES, "CONVERSATION": "No messages yet."}, private=True
        )
    return prompts.render_worker(cfg, kind, PROMPT_VALUES)
