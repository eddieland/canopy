"""A running agent's status card (DESIGN §8, §27, ROADMAP M65): recorded from the call it prints, and shown.

The server's own tests, what it lists and refuses, are with the other servers' in `tests/canopy/loop/test_mcp.py`.
"""

import re
import sqlite3
import time
from collections.abc import Mapping
from pathlib import Path

import pytest

from canopy.core import cards, db, records
from canopy.core.vocab import RunKind
from canopy.runtime.report import Called as CalledTool
from tests.canopy.helpers import (
    BRANCH,
    Called,
    agent_runs,
    calls,
    commit_and_push,
    planner_does,
    with_events,
    worker_does,
)
from tests.canopy.review_helpers import CLEAN, PR, feature_commit, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, dispatches, reviews
from tests.conftest import GitPool

CARD: Mapping[str, object] = {
    "summary": "Adding the endpoint the ticket asks for.",
    "now": "writing the handler",
    "next": ["write its tests", "open the PR"],
}
LATER: Mapping[str, object] = {
    "summary": "Adding the endpoint the ticket asks for; the handler is written.",
    "now": "running the tests",
    "done": [{"what": "wrote the handler", "proof": "not pushed"}],
    "next": ["open the PR"],
    "stuck": "CI is down, so I run the tests here",
}
#: How long the test waits for `_run` or `_review` to record what its agent printed.
WAIT = 30


def says(*said: Mapping[str, object]) -> list[Called]:
    """The calls an agent makes of its `status` tool, one card each."""
    return [calls(cards.tool_name(), **card) for card in said]


def card_now(conn: sqlite3.Connection, table: cards.Table, run_id: int, now: object) -> records.RunCard:
    """The run's card once the run has recorded the one whose `now` is `now`, which its agent printed a moment ago."""
    deadline = time.monotonic() + WAIT
    while (card := cards.of_run(conn, table, run_id)) is None or card.now != now:
        assert time.monotonic() < deadline, f"no card saying {now!r} on {table} {run_id} after {WAIT}s: {card}"
        time.sleep(0.02)
    return card


@pytest.mark.usefixtures("git_pool")
def test_a_running_worker_shows_its_last_card_and_keeps_it_once_it_ends(scenario: Scenario) -> None:
    with_events(scenario.env, "canopy-worker")
    working = scenario.starts(worker=worker_does(*commit_and_push(BRANCH), tools=says(CARD, LATER)))
    card = card_now(scenario.conn, "runs", working.id, LATER["now"])
    # The second call replaced the first whole: nothing of the first is left.
    assert (card.summary, card.stuck, card.calls_since) == (LATER["summary"], LATER["stuck"], 0)
    status = scenario.operator("status").out
    assert re.search(r"\n    now: running the tests  \(card \d+s old, 0 tool calls since\)\n", status), status

    ran = working.finishes()
    card = cards.of_run(scenario.conn, "runs", ran.id)
    assert card is not None
    assert card.now == LATER["now"]
    # The gate the test held the worker at, then its commit and its push.
    assert card.calls_since == 3
    shown = scenario.operator("show", f"run:{ran.id}").out
    before, _, card_lines = shown.partition("\n\nCard, ")
    assert "now:" not in before
    assert re.fullmatch(r"\d+s old, 3 tool calls since:", card_lines.partition("\n")[0]), card_lines
    assert card_lines.partition("\n")[2].splitlines() == [
        "  summary: Adding the endpoint the ticket asks for; the handler is written.",
        "  now: running the tests",
        "  done:",
        "    - wrote the handler: not pushed",
        "  next:",
        "    - open the PR",
        "  stuck: CI is down, so I run the tests here",
    ]


@pytest.mark.usefixtures("git_pool")
def test_a_running_planner_shows_its_card(scenario: Scenario) -> None:
    planner = planner_does(plan="# Plan\n\n## repo\n\nAdd it.\n", tools=says(CARD))
    working = scenario.starts(dispatches(kind=RunKind.PLAN), worker=planner)
    assert card_now(scenario.conn, "runs", working.id, CARD["now"]).summary == CARD["summary"]
    ran = working.finishes()
    card = cards.of_run(scenario.conn, "runs", ran.id)
    assert card is not None
    assert (card.now, card.calls_since) == (CARD["now"], 2)  # the gate, and the command that writes its plan
    assert (
        "  now: writing the handler\n  next:\n    - write its tests\n" in scenario.operator("show", f"run:{ran.id}").out
    )


def test_a_running_reviewer_shows_its_card(scenario: Scenario, git_pool: GitPool, tmp_path: Path) -> None:
    # Reviews on for the loop's own PRs, the reviewer printing its events, and PROJ-1's unit having opened PR.
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer --format json {prompt}"
    scenario.configures(runtime={"review_cmd": template}, review={"agent_prs": True})
    db.set_unit(scenario.conn, "PROJ-1", str(scenario.env.root), "repo", pr_url=PR)
    sha = feature_commit(git_pool, tmp_path)
    reviewing = scenario.starts_review(reviews(sha), reviewer=reviewer_reports(CLEAN, tools=says(CARD)))
    card_now(scenario.conn, "review_runs", reviewing.id, CARD["now"])
    assert "    now: writing the handler  (card " in scenario.operator("status").out
    reviewed = reviewing.finishes()
    shown = scenario.operator("review", "show", str(reviewed.id)).out
    assert "\n\nCard, " in shown
    assert "  summary: Adding the endpoint the ticket asks for.\n  now: writing the handler\n" in shown


@pytest.mark.usefixtures("git_pool")
def test_an_invalid_card_is_a_tool_error_and_records_nothing(scenario: Scenario) -> None:
    with_events(scenario.env, "canopy-worker")
    ran = scenario.run(worker=worker_does(*commit_and_push(BRANCH), tools=says({**CARD, "now": "x" * 201})))
    [worker] = agent_runs(scenario.agent_log)
    [call] = worker["tools"]
    assert (call["name"], call["error"]) == (cards.tool_name(), True)
    assert cards.of_run(scenario.conn, "runs", ran.id) is None
    assert "Card, " not in scenario.operator("show", f"run:{ran.id}").out


def test_canopy_reads_a_card_only_from_a_completed_call_of_its_tool_that_validates() -> None:
    assert cards.card_of(CalledTool(cards.tool_name(), CARD)) == cards.Card.model_validate(CARD)
    # The server refuses what canopy then refuses again, so a call printed as completed records nothing either.
    assert cards.card_of(CalledTool(cards.tool_name(), {**CARD, "now": "two\nlines\u200b"})) is None
    assert cards.card_of(CalledTool("canopy_status", CARD)) is None
    assert cards.card_of(None) is None


def test_a_card_is_recorded_on_a_running_run_alone(conn: sqlite3.Connection) -> None:
    cards.record(conn, "runs", 99, cards.Card.model_validate(CARD))
    assert cards.of_run(conn, "runs", 99) is None


@pytest.mark.parametrize(("value", "served"), [("7", True), ("review-12", True), ("chore-2", False), ("", False)])
def test_the_tool_serves_a_workers_a_planners_and_a_reviews_run(value: str, served: bool) -> None:  # noqa: FBT001
    assert cards.serves(value) is served
