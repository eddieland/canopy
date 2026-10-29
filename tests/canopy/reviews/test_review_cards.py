"""A running reviewer's card: shown on its review run while it runs, and kept once it ends (DESIGN §41)."""

import re

from canopy.core import cards
from tests.canopy.helpers import calls, with_events
from tests.canopy.review_helpers import CLEAN, head, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, reviews
from tests.conftest import CanopyEnv, GitPool

CARD = {
    "summary": "Read the diff; checking the retry loop's exit.",
    "now": "reading retry.py",
    "done": [{"step": "read the diff", "proof": "3 files, 40 lines"}],
    "next": ["check the tests", "write the findings"],
}


def test_a_reviewer_shows_its_card_while_it_runs_and_keeps_it(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    with_events(reviewing, "canopy-reviewer")
    reviewer = reviewer_reports(CLEAN, tools=[calls(cards.tool_name(), **CARD)])
    held = scenario.starts_review(reviews(head(git_pool)), reviewer=reviewer)
    standing = cards.of(held.row)
    assert (standing.card, standing.calls_since) == (cards.Card.model_validate(CARD), 0)
    assert held.row.tool_calls == 1
    status = scenario.operator("status").out
    assert re.search(r"\n  review  \S+  .*\n    now: reading retry\.py  card \d+[sm], 0 calls old\n", status), status
    shown = scenario.operator("review", "show", str(held.id)).out
    assert "\n    now: reading retry.py\n    done: read the diff (3 files, 40 lines)\n" in shown
    done = held.finishes()
    assert cards.of(done.row).card == standing.card
    assert "\n  last card, " in scenario.operator("review", "show", str(done.id)).out
