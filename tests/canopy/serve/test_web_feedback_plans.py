"""Feedback plans in the web API (DESIGN §32): the plan on its PR's threads, and approving it as `canopy plan`."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from canopy.core import db, feedback_items, feedback_plans
from canopy.core.vocab import PlanStatus
from tests.canopy.helpers import DRAFTS_PR, KEY, comment, context, present, waits
from tests.canopy.scenario_helpers import (
    ALICES_COMMENT,
    BOBS_COMMENT,
    FEEDBACK_PLANNED,
    FEEDBACK_TEXT,
    feedback_planned,
    github_shows,
    with_a_pr,
)
from tests.canopy.web_helpers import refused, signed_in_client

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient

    from tests.canopy.scenario_helpers import Scenario

PR = DRAFTS_PR
APPROVE = f"/api/tickets/{KEY}/feedback-plan"


def planned_client(scenario: Scenario, github_state: Path) -> tuple[TestClient, dict[str, str], int]:
    """A feedback plan waiting on alice's and bob's threads, and a browser signed in to the server over its journal."""
    with_a_pr(scenario)
    run_id = feedback_planned(scenario, github_state)
    c, write = signed_in_client(context(scenario.env))
    return c, write, run_id


def plan_of(c: TestClient) -> dict[str, Any]:
    response = c.get("/api/pull-request/threads", params={"url": PR})
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["feedback_plan"]
    return found


def waiting_of(c: TestClient) -> dict[str, Any] | None:
    """The waiting feedback plan the tickets list and the ticket's page name for `KEY`, the same on both."""
    listed = c.get("/api/tickets")
    assert listed.status_code == 200, listed.text
    [summary] = [t for t in listed.json() if t["key"] == KEY]
    page = c.get(f"/api/tickets/{KEY}")
    assert page.status_code == 200, page.text
    found: dict[str, Any] | None = summary["feedback_plan"]
    assert page.json()["ticket"]["feedback_plan"] == found
    return found


@pytest.mark.usefixtures("git_pool")
def test_a_prs_threads_carry_its_waiting_feedback_plan_each_item_on_its_thread(
    scenario: Scenario,
    github_state: Path,
) -> None:
    c, _, run_id = planned_client(scenario, github_state)
    plan = plan_of(c)
    assert (plan["ticket_key"], plan["run"], plan["status"], plan["changes"]) == (KEY, run_id, "waiting", [])
    assert (plan["text"], plan["problem"], plan["spent_run"], plan["approved_at"]) == (FEEDBACK_TEXT, None, None, None)
    assert [
        (i["number"], i["item_id"], i["thread_id"], i["author"], i["trusted"], i["proposal"], i["reply"])
        for i in plan["items"]
    ] == [
        (1, 501, "PRRT_1", "alice", True, "change", "Renamed."),
        (2, 502, "PRRT_2", "bob", False, "decline", "Kept, since the API needs it."),
    ]
    assert not any(i["left_out"] for i in plan["items"])
    # Each item carries what was said, as last read, where it is on its host, and the plan's first line on it: bob's
    # comment has no heading in FEEDBACK_TEXT, so no line.
    assert [(i["excerpt"], i["url"], i["rationale"]) for i in plan["items"]] == [
        ("Rename this.", f"{PR}#discussion_r501", "Rename it."),
        ("Drop this argument.", f"{PR}#discussion_r502", None),
    ]


def test_a_plans_rationales_are_the_first_line_under_each_items_heading() -> None:
    text = (
        "# Feedback plan: PROJ-1\n\n## Items\n\n### Item 501: change\n\n```\nnot this\n```\nRename it, as\tasked.\n"
        "More.\n\n### Item 502: leave\n\n#### Item 503: ask\n\nWhy?\n\n## Checks\n\nNone ran.\n### Item 504: decline\n"
        + "x" * 300
        + "\n"
    )
    assert feedback_plans.rationales(text) == {501: "Rename it, as asked.", 503: "Why?", 504: "x" * 199 + "…"}
    assert feedback_plans.first_line("\n  \n\x07one\x00 two\nthree") == "one two"
    assert feedback_plans.first_line("\n \t\n") is None


@pytest.mark.usefixtures("git_pool")
def test_a_failed_check_and_a_conflict_are_items_on_no_thread_the_check_by_its_name(
    scenario: Scenario,
    github_state: Path,
) -> None:
    with_a_pr(scenario)
    build = feedback_items.check_id(PR, "abc1234", "build")
    conflict = feedback_items.conflict_id(PR, "abc1234", "main")
    items = [{"id": build, "proposal": "change", "reply": "Fixed the build."}, {"id": conflict, "proposal": "change"}]
    feedback_planned(scenario, github_state, {**FEEDBACK_PLANNED, "items": items}, mergeable="conflicting")
    c, _ = signed_in_client(context(scenario.env))
    assert [
        (i["item"], i["item_id"], i["check"], i["thread_id"], i["author"], i["trusted"]) for i in plan_of(c)["items"]
    ] == [("check", build, "build", None, None, False), ("conflict", conflict, None, None, None, False)]


@pytest.mark.usefixtures("git_pool")
def test_a_prs_threads_carry_no_feedback_plan_with_none(scenario: Scenario, github_state: Path) -> None:
    with_a_pr(scenario)
    github_shows(github_state, ALICES_COMMENT)
    scenario.seen()
    scenario.tick(*waits(KEY), dry_run=True)
    c, _ = signed_in_client(context(scenario.env))
    assert plan_of(c) is None


@pytest.mark.usefixtures("git_pool")
def test_the_page_approves_a_feedback_plan_by_item_as_the_cli_does(scenario: Scenario, github_state: Path) -> None:
    c, write, _ = planned_client(scenario, github_state)
    plan_id = present(feedback_plans.current(scenario.conn, KEY)).id
    # Refused as `canopy plan` refuses it, by the same guards, and nothing approved.
    unknown = c.post(APPROVE, json={"items": [1, 9]}, headers=write)
    assert refused(unknown).startswith(f"bad_item: feedback plan {plan_id} of {KEY} has no item 9; it covers items")
    both = c.post(APPROVE, json={"items": [1], "leave": [2]}, headers=write)
    assert refused(both).startswith("bad_item: name the items to approve or those to leave out, not both")
    assert refused(c.post(APPROVE, json={"message": "  "}, headers=write)).startswith("bad_body: ")
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "9"}):
        inside = c.post(APPROVE, json={}, headers=write)
    assert refused(inside).startswith("inside_run: ")
    assert present(feedback_plans.current(scenario.conn, KEY)).status is PlanStatus.PROPOSED

    approved = c.post(APPROVE, json={"leave": [2], "message": "Keep the old name too."}, headers=write)
    assert approved.status_code == 200, approved.text
    done = approved.json()
    assert (done["plan"], done["ticket_key"]) == (plan_id, KEY)
    assert (done["addressed"], done["left"]) == ([{"number": 1, "item_id": 501}], [{"number": 2, "item_id": 502}])
    message = present(db.get_message(scenario.conn, done["message"]))
    assert (message.source, message.channel) == ("operator", "web")
    assert message.body == (
        f"Address item 1 (id 501) of feedback plan {plan_id}, as it proposes. Leave its item 2 (id 502) for the next "
        "plan: change nothing for it, and draft no reply to it.\n\nKeep the old name too."
    )
    plan = plan_of(c)
    assert (plan["status"], plan["approved_channel"], plan["approved_message"]) == ("approved", "web", message.id)
    assert [(i["number"], i["left_out"]) for i in plan["items"]] == [(1, False), (2, True)]
    # Approving it again as it is, with nothing new, is refused, as the CLI refuses it.
    again = c.post(APPROVE, json={"leave": [2]}, headers=write)
    assert (
        refused(again) == f"bad_plan: feedback plan {plan_id} of {KEY} is approved, and its file has not changed since"
    )


@pytest.mark.usefixtures("git_pool")
def test_a_stale_plan_says_what_changed_and_its_approval_is_refused_once(
    scenario: Scenario,
    github_state: Path,
) -> None:
    c, write, _ = planned_client(scenario, github_state)
    carol = comment(601, "PRRT_3", author="carol", body="And this.")
    github_shows(github_state, ALICES_COMMENT, BOBS_COMMENT, carol)
    scenario.seen()
    scenario.tick(*waits(KEY), dry_run=True)
    plan = plan_of(c)
    said = f"new comment 601 on {PR} by carol"
    assert (plan["status"], plan["changes"], plan["stale_shown"]) == ("stale", [said], False)
    # carol's thread is no item of this plan: the next plan's.
    assert [i["thread_id"] for i in plan["items"]] == ["PRRT_1", "PRRT_2"]

    first = refused(c.post(APPROVE, json={}, headers=write))
    assert first.startswith(f"stale: feedback plan {plan['id']} of {KEY} is stale: {said}. Approve it again")
    assert plan_of(c)["stale_shown"] is True
    approved = c.post(APPROVE, json={}, headers=write)
    assert approved.status_code == 200, approved.text
    assert approved.json()["left"] == []
    # Once approved it is not stale: what changed waits for the next plan.
    assert (plan_of(c)["status"], plan_of(c)["changes"]) == ("approved", [])


@pytest.mark.usefixtures("git_pool")
def test_a_tickets_summary_names_its_feedback_plan_while_it_waits(scenario: Scenario, github_state: Path) -> None:
    """The attention list tells a feedback plan's `plan_review` from a ticket plan's, and its answer, by this."""
    c, write, _ = planned_client(scenario, github_state)
    plan_id = present(feedback_plans.current(scenario.conn, KEY)).id
    assert waiting_of(c) == {"id": plan_id, "pr_urls": [PR], "items": 2, "stale": False}
    github_shows(github_state, ALICES_COMMENT, BOBS_COMMENT, comment(601, "PRRT_3", author="carol", body="And this."))
    scenario.seen()
    scenario.tick(*waits(KEY), dry_run=True)
    assert present(waiting_of(c))["stale"] is True
    # Approved, it waits on the operator no more: refused once as stale, then approved as it is.
    refused(c.post(APPROVE, json={}, headers=write))
    assert c.post(APPROVE, json={}, headers=write).status_code == 200
    assert waiting_of(c) is None


@pytest.mark.usefixtures("git_pool")
def test_a_feedback_plan_runs_page_names_the_plan_it_wrote_and_where_it_stands(
    scenario: Scenario,
    github_state: Path,
) -> None:
    """The run's page points to the PR's page, where the plan is approved; a run of another kind names none."""
    c, write, run_id = planned_client(scenario, github_state)
    plan_id = present(feedback_plans.current(scenario.conn, KEY)).id
    page = c.get(f"/api/runs/{run_id}")
    assert page.status_code == 200, page.text
    assert page.json()["feedback_plan"] == {"id": plan_id, "pr_urls": [PR], "status": "waiting"}
    assert c.post(APPROVE, json={}, headers=write).status_code == 200
    assert c.get(f"/api/runs/{run_id}").json()["feedback_plan"]["status"] == "approved"
    other = next(r["id"] for r in c.get("/api/runs").json() if r["id"] != run_id and r["ticket_key"] == KEY)
    assert c.get(f"/api/runs/{other}").json()["feedback_plan"] is None
