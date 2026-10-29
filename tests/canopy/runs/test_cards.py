"""A running worker's or planner's card: shown on its run while it runs, and kept once it ends (DESIGN §41)."""

from collections.abc import Mapping

from canopy.core import cards
from canopy.core.vocab import RunKind
from tests.canopy.helpers import agent_runs, calls, planner_does, with_events, worker_does
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import GitPool

STATUS = cards.tool_name()
FIRST: Mapping[str, object] = {"summary": "Reading the ticket.", "now": "reading the code", "next": ["fix it"]}
LATER: Mapping[str, object] = {
    "summary": "The fix is in and its tests pass; pushing next.",
    "now": "pushing",
    "done": [{"step": "fix the parser", "proof": "tests pass: 42/42"}],
    "next": ["push", "open the PR"],
    "stuck": "CI is down; running the tests here instead",
}
#: A call the server refuses: it says nothing of what the agent does now.
REFUSED: Mapping[str, object] = {"summary": "No now."}


def test_a_worker_shows_its_card_while_it_runs_and_keeps_its_last_once_it_ends(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    with_events(scenario.env, "canopy-worker")
    said = (calls(STATUS, **FIRST), calls(STATUS, **LATER), calls(STATUS, **REFUSED))
    working = scenario.starts(worker=worker_does(["true"], tools=said))

    # Each call replaces the card; the refused one records nothing, and counts as a call since.
    standing = cards.of(working.row)
    assert standing.card == cards.Card.model_validate(LATER)
    assert standing.calls_since == 1

    ran = working.finishes()
    [made] = [[(t["name"], t["error"]) for t in run["tools"]] for run in agent_runs(scenario.agent_log)]
    assert made == [(STATUS, False), (STATUS, False), (STATUS, True)]
    kept = cards.of(ran.row)
    assert (kept.card, kept.at) == (standing.card, standing.at)
    # The worker's commands, the gate that held it among them, were calls since.
    assert kept.calls_since == 3


def test_a_planner_shows_its_card_while_it_runs(scenario: Scenario, git_pool: GitPool) -> None:
    planner = planner_does(plan="# Plan\n\nDo it.\n", tools=[calls(STATUS, **FIRST)])
    working = scenario.starts(dispatches(kind=RunKind.PLAN), worker=planner)
    assert cards.of(working.row).card == cards.Card.model_validate(FIRST)
    assert cards.of(working.finishes().row).card == cards.Card.model_validate(FIRST)


def test_a_worker_whose_events_are_not_printed_keeps_no_card(scenario: Scenario, git_pool: GitPool) -> None:
    working = scenario.starts(worker=worker_does(["true"], tools=[calls(STATUS, **FIRST)]))
    assert cards.of(working.row) == cards.Standing(None, None, 0)
    working.finishes()
