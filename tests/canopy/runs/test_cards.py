"""A running worker's or planner's card: shown on its run while it runs, and kept once it ends (DESIGN §41)."""

import re
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


def test_canopy_status_shows_what_a_running_card_says_now_and_marks_it_stale(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    with_events(scenario.env, "canopy-worker")
    working = scenario.starts(worker=worker_does(["true"], tools=[calls(STATUS, **LATER)]))
    out = scenario.operator("status").out
    assert re.search(r"\n    now: pushing  card \d+s, 0 calls old\n", out), out
    scenario.time_passes(minutes=cards.STALE_MINUTES + 1)
    assert re.search(r"\n    now: pushing  card 1[01]m, 0 calls old  stale\n", scenario.operator("status").out)
    working.finishes()


def test_a_running_run_with_no_card_is_named_in_status_once_that_is_stale(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    with_events(scenario.env, "canopy-worker")
    working = scenario.starts(worker=worker_does(["true"]))
    assert "no card" not in scenario.operator("status").out
    scenario.time_passes(minutes=cards.STALE_MINUTES + 1)
    assert re.search(r"\n    no card, 1[01]m and 0 calls in\n", scenario.operator("status").out)
    working.finishes()


def test_show_prints_the_whole_card_while_it_runs_and_the_last_once_it_ends(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    with_events(scenario.env, "canopy-worker")
    working = scenario.starts(worker=worker_does(["true"], tools=[calls(STATUS, **LATER)]))
    whole = [
        "    The fix is in and its tests pass; pushing next.",
        "    now: pushing",
        "    done: fix the parser (tests pass: 42/42)",
        "    next: push",
        "    next: open the PR",
        "    stuck: CI is down; running the tests here instead",
    ]
    shown = scenario.operator("show", f"run:{working.id}").out.splitlines()
    [head] = [line for line in shown if line.startswith("  card, ")]
    assert shown[shown.index(head) + 1 :][: len(whole)] == whole
    ran = working.finishes()
    shown = scenario.operator("show", f"run:{ran.id}").out.splitlines()
    [head] = [line for line in shown if line.startswith("  last card, ")]
    assert head.endswith(", 2 calls before the run ended")  # the gate that held it, and `true`
    assert shown[shown.index(head) + 1 :][: len(whole)] == whole
