"""A running worker's or planner's card: shown on its run while it runs, and kept once it ends (DESIGN §41)."""

import json
import re
from collections.abc import Mapping
from typing import Any

from canopy.core import cards
from canopy.core.vocab import RunKind
from canopy.loop import readback
from tests.canopy.helpers import agent_runs, calls, context, planner_does, with_events, worker_does
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
    assert re.search(r"\n    now: pushing  card \d+[sm], 0 calls old\n", out), out
    scenario.time_passes(minutes=cards.STALE_MINUTES + 1)
    assert re.search(r"\n    now: pushing  card 1\dm, 0 calls old  stale\n", scenario.operator("status").out)
    working.finishes()


def test_a_running_run_with_no_card_is_named_in_status_once_that_is_stale(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    with_events(scenario.env, "canopy-worker")
    working = scenario.starts(worker=worker_does(["true"]))
    assert "no card" not in scenario.operator("status").out
    scenario.time_passes(minutes=cards.STALE_MINUTES + 1)
    assert re.search(r"\n    no card, 1\dm and 0 calls in\n", scenario.operator("status").out)
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


def test_a_card_with_steps_shows_how_much_is_done_and_the_stage_under_way(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    with_events(scenario.env, "canopy-worker")
    planned = {
        **FIRST,
        "steps": [
            {"title": "Add the endpoint", "status": "done", "stage": "api"},
            {"title": "Call it from the page", "status": "working", "stage": "web"},
            {"title": "Push", "status": "not_started"},
        ],
    }
    working = scenario.starts(worker=worker_does(["true"], tools=[calls(STATUS, **planned)]))
    assert re.search(
        r"\n    now: reading the code  33% done, stage web  card \d+[sm], 0 calls old\n",
        scenario.operator("status").out,
    )
    shown = scenario.operator("show", f"run:{working.id}").out
    assert (
        "\n    steps:  33% done, stage web\n      [x] Add the endpoint (api)\n      [>] Call it from the page (web)\n"
        in shown
    )
    assert "      [ ] Push\n" in shown
    working.finishes()


def test_the_report_a_chores_agent_reads_of_a_run_leaves_its_card_out(scenario: Scenario, git_pool: GitPool) -> None:
    """A card is the operator's alone (DESIGN §41): no agent reads another's."""
    with_events(scenario.env, "canopy-worker")
    working = scenario.starts(worker=worker_does(["true"], tools=[calls(STATUS, **LATER)]))
    reported = readback.read_run(context(scenario.env), readback.ShowRun(run=working.id))
    assert "pushing" not in reported
    assert "    now: pushing\n" in scenario.operator("show", f"run:{working.id}").out
    working.finishes()


ASKING: Mapping[str, Any] = {
    **FIRST,
    "question": {
        "ask": "Keep the old endpoint for the mobile app, or remove it?",
        "options": ["keep it, deprecated", "remove it now", "ask the mobile team"],
        "recommend": "A",
    },
}


def test_the_operator_answers_a_running_workers_question_by_letter(scenario: Scenario, git_pool: GitPool) -> None:
    with_events(scenario.env, "canopy-worker")
    working = scenario.starts(worker=worker_does(["true"], tools=[calls(STATUS, **ASKING)]))
    ref = f"run:{working.id}"
    status = scenario.operator("status").out
    assert re.search(rf"\n    asks you, \d+[sm]: Keep the old .+  canopy reply {ref} A-C \(recommends A\)\n", status)
    assert f"      waiting on you: canopy reply {ref} LETTER\n" in scenario.operator("show", ref).out

    answers = cards.answers_dir(context(scenario.env).state_dir, str(working.id))
    assert answers.is_dir()
    assert not (answers / cards.ANSWER_FILE).exists()

    assert "(bad_answer)" in scenario.operator("reply", ref, "D", code=1).err  # no option D
    answered = scenario.operator("reply", ref, " b ")
    assert answered.out.endswith("Answered B: remove it now.\nIts agent hears it on its next tool call.\n")
    written = json.loads((answers / cards.ANSWER_FILE).read_text())
    assert (written["ask"], written["letter"], written["option"]) == (ASKING["question"]["ask"], "B", "remove it now")
    assert "Nothing new recorded" in scenario.operator("reply", ref, "B").out
    assert cards.of(working.row).answer == "B"
    assert "asks you" not in scenario.operator("status").out
    assert "      answered B, " in scenario.operator("show", ref).out

    ran = working.finishes()
    # The run is told where its answers are, and they go with it.
    [run] = agent_runs(scenario.agent_log)
    assert run["env"][cards.ANSWERS_ENV] == str(answers)
    assert not answers.exists()
    assert "(ended)" in scenario.operator("reply", f"run:{ran.id}", "A", code=1).err
    assert cards.of(ran.row).answer == "B"


def test_a_run_whose_card_asks_nothing_refuses_an_answer(scenario: Scenario, git_pool: GitPool) -> None:
    with_events(scenario.env, "canopy-worker")
    working = scenario.starts(worker=worker_does(["true"], tools=[calls(STATUS, **FIRST)]))
    assert "(no_question)" in scenario.operator("reply", f"run:{working.id}", "A", code=1).err
    working.finishes()
