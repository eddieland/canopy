"""Drafts (DESIGN §29): under `trust.review_replies = "approve"` a worker's comments are kept for the operator."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from canopy.core import drafts, replies
from canopy.core.vocab import DraftKind, DraftStance, DraftStatus, Reaction, ReplyMode
from tests.canopy.helpers import APPROVE, DRAFTS_PR, KEY, TRACKER_POSTS, all_drafts, present
from tests.canopy.scenario_helpers import dispatches, sends_drafts

if TYPE_CHECKING:
    from tests.canopy.scenario_helpers import Ran, Scenario

PR = DRAFTS_PR
ISSUE = "https://github.com/acme/api/issues/1"
REPLY = "Renamed it.\n\n```python\nretries = 3\n```"
THREAD = {"on": "thread", "pr": PR, "comment": 501, "did": "changed", "text": REPLY}
#: KEY's run on its `work` branch, as each drafting run here is.
WORK = dispatches(slug="work")
#: Workers post their own replies, as before drafts (DESIGN §29); APPROVE has them draft replies for the operator.
POST = {"review_replies": "post"}


def refused(conn: sqlite3.Connection, run: Ran) -> list[tuple[int, str]]:
    found = present(replies.run_replies(conn, run.id))
    return [(r.number, r.why) for r in drafts.refused_of(found)]


@pytest.mark.usefixtures("git_pool")
def test_under_post_a_workers_drafts_are_stored_nowhere(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=POST)
    run = scenario.run(WORK, worker=sends_drafts([THREAD]))
    assert run.status == "done"
    assert all_drafts(conn) == []
    assert present(replies.run_replies(conn, run.id)).mode is ReplyMode.POST
    assert "drafts" not in str(run.row["result_json"])


@pytest.mark.usefixtures("git_pool")
def test_under_approve_a_runs_drafts_are_kept_unchecked_with_its_text(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=APPROVE)
    run = scenario.run(WORK, worker=sends_drafts([THREAD, {"on": "pr", "pr": PR, "text": "Fixed the lint job."}]))
    reply, comment = all_drafts(conn)
    assert (reply.run_id, reply.number, reply.ticket_key, reply.kind) == (run.id, 1, KEY, DraftKind.THREAD)
    assert (reply.repo, reply.pr_url, reply.comment_id, reply.stance) == ("repo", PR, 501, DraftStance.CHANGED)
    assert reply.status is DraftStatus.UNCHECKED
    assert reply.basis == run.row["started_at"]
    assert drafts.text_of(conn, reply.id).body == REPLY
    assert (comment.number, comment.kind, comment.comment_id, comment.stance) == (2, DraftKind.PR, None, None)
    assert drafts.text_of(conn, comment.id).body == "Fixed the lint job."
    assert "drafts" not in str(run.row["result_json"])
    assert refused(conn, run) == []


@pytest.mark.usefixtures("git_pool")
def test_each_draft_is_refused_alone(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=APPROVE)
    entries = [
        "a reply",
        {"on": "review", "pr": PR, "text": "x"},
        {**THREAD, "pr": "https://github.com/acme/web/pull/9"},
        {**THREAD, "comment": "501"},
        {**THREAD, "did": "maybe"},
        {**THREAD, "text": "  "},
        {**THREAD, "text": "x" * 4001},
        {**THREAD, "text": "Done\u200b."},
        {**THREAD, "text": "Use token ghp_abcdefghijklmnopqrstuvwxyz0123456789."},
        {"on": "ticket", "url": ISSUE, "text": "Done."},
        {"on": "pr", "pr": PR, "text": "One."},
        {"on": "pr", "pr": PR, "text": "Two."},
        THREAD,
    ]
    run = scenario.run(WORK, worker=sends_drafts(entries))
    assert [(d.number, d.kind) for d in all_drafts(conn)] == [(11, DraftKind.PR), (13, DraftKind.THREAD)]
    assert refused(conn, run) == [
        (1, "it is not an object"),
        (2, "its `on` is not thread, pr, or ticket"),
        (3, "not_ours: its `pr` is not one of this run's PRs"),
        (4, "its `comment` is not a review comment's id"),
        (5, "its `did` is not changed, declined, or answered"),
        (6, "its text is blank"),
        (7, "its text is 4001 characters, over 4000"),
        (8, "its text holds U+200B (ZERO WIDTH SPACE), a character that hides text"),
        (9, "its text looks like it holds a secret"),
        (10, "no_post: this run was asked for no ticket's draft"),
        (12, f"a second draft for {PR}'s own comment; a PR takes one"),
    ]


@pytest.mark.usefixtures("git_pool")
def test_a_threads_draft_stages_a_reaction_beside_its_text_or_alone(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=APPROVE)
    alone = {"on": "thread", "pr": PR, "comment": 502, "did": "changed", "react": "rocket"}
    run = scenario.run(WORK, worker=sends_drafts([{**THREAD, "react": "+1"}, alone]))
    beside, only = (drafts.text_of(conn, d.id) for d in all_drafts(conn))
    assert (beside.body, beside.reaction) == (REPLY, Reaction.THUMBS_UP)
    assert (only.body, only.reaction) == ("", Reaction.ROCKET)
    assert refused(conn, run) == []


@pytest.mark.usefixtures("git_pool")
def test_a_reaction_github_does_not_offer_or_off_a_thread_is_refused(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=APPROVE)
    entries = [
        {**THREAD, "react": "thumbsup"},
        {"on": "pr", "pr": PR, "text": "Fixed CI.", "react": "+1"},
        {"on": "thread", "pr": PR, "comment": 502, "did": "changed"},
        {**THREAD, "text": "  ", "react": "eyes"},
    ]
    run = scenario.run(WORK, worker=sends_drafts(entries))
    assert all_drafts(conn) == []
    assert refused(conn, run) == [
        (1, "its `react` is not one of +1, -1, laugh, confused, heart, hooray, rocket, eyes"),
        (2, "its `react` is on a draft that is not a thread's; only a review comment takes one"),
        (3, "its text is not a string"),
        (4, "its text is blank"),
    ]


@pytest.mark.usefixtures("git_pool")
def test_a_run_drafts_at_most_thirty(scenario: Scenario) -> None:
    scenario.configures("private", trust=APPROVE)
    run = scenario.run(WORK, worker=sends_drafts([{**THREAD, "comment": 500 + n} for n in range(32)]))
    assert len(all_drafts(scenario.conn)) == 30
    assert refused(scenario.conn, run) == [(31, "over 30 drafts a run"), (32, "over 30 drafts a run")]


@pytest.mark.usefixtures("git_pool")
def test_drafts_that_are_not_a_list_are_refused(scenario: Scenario) -> None:
    scenario.configures("private", trust=APPROVE)
    run = scenario.run(WORK, worker=sends_drafts({"on": "thread"}))
    assert all_drafts(scenario.conn) == []
    assert refused(scenario.conn, run) == [(0, "`drafts` is not a list")]


@pytest.mark.usefixtures("git_pool")
def test_with_a_tracker_that_posts_a_ticket_draft_waits_at_once(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=APPROVE, connect=TRACKER_POSTS)
    ticket = {"on": "ticket", "url": ISSUE, "text": "Which base?"}
    run = scenario.run(
        WORK, worker=sends_drafts([{**ticket, "url": "http://x/1"}, ticket, {**ticket, "text": "Again?"}])
    )
    [draft] = all_drafts(conn)
    assert (draft.kind, draft.issue_url, draft.pr_url, draft.status) == (
        DraftKind.TICKET,
        ISSUE,
        None,
        DraftStatus.WAITING,
    )
    assert present(replies.run_replies(conn, run.id)).ticket_drafts is True
    assert refused(conn, run) == [
        (1, "its `url` is not the ticket's https:// URL"),
        (3, "a second draft for the ticket; a run takes one"),
    ]
    assert '"on":"ticket"' in run.prompt


@pytest.mark.usefixtures("git_pool")
def test_under_approve_the_prompt_asks_for_drafts_and_posts_nothing(scenario: Scenario) -> None:
    scenario.configures("private", trust=APPROVE)
    text = scenario.run(WORK, worker=sends_drafts([])).prompt
    assert 'That JSON object also carries `"drafts"`' in text
    assert '"on":"ticket"' not in text
    # Without a tracker that posts, the worker still comments on the ticket itself, marked.
    assert "- Comment on the ticket: what you did" in text
    assert "In every comment and reply you post, on the ticket, start it with `CANOPY:`" in text


@pytest.mark.usefixtures("git_pool")
def test_an_override_without_drafts_serves_under_post_and_is_refused_under_approve(scenario: Scenario) -> None:
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work on {{KEY}}, labels {{LABELS}}. Reply on the PR.\n")
    scenario.configures("private", trust=POST)
    # The run ends, so the next dispatch is refused for its prompt alone.
    assert (
        scenario.run(WORK, worker=sends_drafts([])).prompt
        == "Work on PROJ-1, labels `agent-ready-tester`. Reply on the PR.\n"
    )
    scenario.configures("private", trust=APPROVE)
    [(action, rationale)] = scenario.refuses(WORK)[-1:]
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{DRAFTS}}" in rationale


def test_the_drafts_fields_are_read_apart_from_the_result() -> None:
    line = json.dumps({"status": "done", "drafts": [THREAD]})
    assert present(drafts.parse(f"working\n{line}\n")).drafts == [THREAD]
    assert drafts.parse("no result") is None
