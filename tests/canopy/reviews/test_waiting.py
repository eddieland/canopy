"""A review's draft on the attention list (DESIGN §14, §34): a requested review done, a draft staged or unconfirmed."""

import json
from pathlib import Path

import pytest

from canopy.core import db, review_drafts, sql
from canopy.core.context import Context
from canopy.core.items import Item
from canopy.loop import attention
from canopy.reviews import waiting
from tests.canopy.helpers import present, tick_reads, waits
from tests.canopy.review_helpers import THEIRS
from tests.canopy.scenario_helpers import Scenario

ITEM = f"{attention.PR_PREFIX}{THEIRS}"


def listed(ctx: Context) -> list[Item]:
    return [i for i in attention.listed(ctx) if i.reason in waiting.REASONS]


def hash_of(scenario: Scenario, run_id: int) -> str:
    draft = present(review_drafts.of_review(scenario.conn, run_id))
    return review_drafts.newest(scenario.conn, draft.id).hash


def test_a_requested_review_waits_on_the_operator_until_they_stage_it_and_then_until_a_read_settles_it(
    scenario: Scenario,
    requested: int,
    github_state: Path,
    ctx: Context,
) -> None:
    scenario.tick(*waits("PROJ-1", rationale="its PR is out for review"))
    [item] = listed(ctx)
    assert (item.ticket_key, item.reason, item.repo) == (ITEM, waiting.WAITING_REASON, None)
    assert item.detail == (
        f"review:{requested}, which you asked for, is done: its draft of {THEIRS} waits on you to publish or stage it "
        f"(`canopy review draft {requested}`), or discard it (`canopy review discard {requested}`)"
    )
    # The harness's alone: the overseer is never shown it to record.
    assert attention.for_overseer(scenario.conn) == []
    scenario.operator("review", "publish", str(requested), hash_of(scenario, requested))
    # Staged, the item is gone at once, without a tick; the next tick raises the staged one.
    assert listed(ctx) == []
    scenario.tick(*waits("PROJ-1", rationale="its PR is out for review"))
    [staged] = listed(ctx)
    assert (staged.ticket_key, staged.reason) == (ITEM, waiting.UNSETTLED_REASON)
    assert staged.detail.startswith(f"review:{requested}'s draft is in the review you staged on {THEIRS}")
    # Still pending on GitHub, it stays; submitted there, the read settles it, and nothing waits.
    tick_reads(ctx)
    assert [i.reason for i in listed(ctx)] == [waiting.UNSETTLED_REASON]
    state = json.loads(github_state.read_text())
    for line in state["prs"][THEIRS]["reviews"]:
        if line["item"] == "review":
            line["state"] = "commented"
    github_state.write_text(json.dumps(state))
    tick_reads(ctx)
    assert listed(ctx) == []
    assert waiting.items(scenario.conn) == []


def test_a_post_of_unknown_outcome_waits_until_a_read_says_nothing_posted_and_the_draft_waits_again(
    scenario: Scenario,
    requested: int,
    github_state: Path,
    ctx: Context,
) -> None:
    github_state.write_text(json.dumps({"prs": {THEIRS: {}}, "post": "unknown", "posted": False}))
    scenario.operator("review", "publish", str(requested), hash_of(scenario, requested), "--submit", code=1)
    [item] = waiting.items(scenario.conn)
    assert (item.pr, item.reason) == (THEIRS, waiting.UNSETTLED_REASON)
    assert item.detail.startswith(f"review:{requested}'s draft may have been posted on {THEIRS}")
    tick_reads(ctx)
    assert [i.reason for i in waiting.items(scenario.conn)] == [waiting.WAITING_REASON]


def test_a_draft_emptied_of_all_it_would_post_waits_on_nobody(scenario: Scenario, requested: int) -> None:
    run = str(requested)
    scenario.operator("dismiss", f"review:{requested}", "1", "2")
    assert waiting.items(scenario.conn) == []
    scenario.operator("review", "edit", run, "--body", "--text", "One thing.")
    assert [i.reason for i in waiting.items(scenario.conn)] == [waiting.WAITING_REASON]
    scenario.operator("review", "edit", run, "--body", "--text", "")
    assert waiting.items(scenario.conn) == []


def test_a_review_canopy_found_by_its_query_waits_on_nobody(reviewed: int, scenario: Scenario) -> None:
    del reviewed
    assert waiting.items(scenario.conn) == []


@pytest.mark.parametrize("gone", ["held", "merged"])
def test_a_requested_review_of_a_pr_a_ticket_holds_or_seen_merged_waits_on_nobody(
    scenario: Scenario,
    requested: int,
    gone: str,
) -> None:
    del requested
    conn = scenario.conn
    assert len(waiting.items(conn)) == 1
    if gone == "held":
        db.set_unit(conn, "PROJ-2", str(scenario.env.root), "repo", pr_url=THEIRS)
    else:
        merged = {"repository": "acme/api", "number": 8, "base_ref": "main", "state": "merged", "draft": 0}
        sql.execute(conn, sql.insert("observed_prs", url=THEIRS, observed_at=db.now(), **merged))
    assert waiting.items(conn) == []


def test_a_discarded_draft_waits_on_nobody(scenario: Scenario, requested: int) -> None:
    assert [i.reason for i in waiting.items(scenario.conn)] == [waiting.WAITING_REASON]
    scenario.operator("review", "discard", str(requested))
    assert waiting.items(scenario.conn) == []


def test_a_requested_review_of_a_pr_never_read_waits_until_a_tick_reads_it_merged(
    scenario: Scenario,
    requested: int,
    github_state: Path,
    ctx: Context,
) -> None:
    del requested
    # Its request ended with the review, before any read saw the PR: only its draft keeps the PR read.
    github_state.write_text(json.dumps({"prs": {THEIRS: {"pr": {"state": "merged"}}}}))
    assert [i.reason for i in waiting.items(scenario.conn)] == [waiting.WAITING_REASON]
    assert waiting.unread_prs(scenario.conn) == [THEIRS]
    tick_reads(ctx)
    assert waiting.items(scenario.conn) == []
    # Seen merged, it is read no more.
    assert waiting.unread_prs(scenario.conn) == []
