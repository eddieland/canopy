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
    assert re.search(r"\n  review  \S+  .*\n    now: reading retry\.py  card \d+s, 0 calls old\n", status), status
    shown = scenario.operator("review", "show", str(held.id)).out
    assert "\n    now: reading retry.py\n    done: read the diff (3 files, 40 lines)\n" in shown
    done = held.finishes()
    assert cards.of(done.row).card == standing.card
    assert "\n  last card, " in scenario.operator("review", "show", str(done.id)).out


def test_a_reviewers_steps_are_its_own_and_one_working_a_fifth_of_its_timeout_is_stuck(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    with_events(reviewing, "canopy-reviewer")
    steps = [
        {"title": "read the diff", "status": "done", "stage": "read"},
        {"title": "check the tests", "status": "working", "stage": "tests"},
        {"title": "write the findings", "status": "not_started"},
    ]
    reviewer = reviewer_reports(CLEAN, tools=[calls(cards.tool_name(), **CARD, steps=steps)])
    held = scenario.starts_review(reviews(head(git_pool)), reviewer=reviewer)
    [_, working, _] = cards.of(held.row).steps
    # The review's timeout is 20 minutes, so its working step is stuck after 4.
    assert working.stuck_at is not None
    assert working.stuck_at - working.since == cards.stuck_after(20)
    assert re.search(r"  steps 33% of 3, stage tests\n", scenario.operator("status").out)
    scenario.time_passes(minutes=5)
    assert re.search(r"  steps 33% of 3, stage tests, 1 stuck\n", scenario.operator("status").out)
    held.finishes()
