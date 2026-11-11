"""Drafts (DESIGN §29): under `trust.review_replies = "approve"` a worker's comments are kept for the operator."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pydantic
import pytest

from canopy.core import db, replies
from canopy.core.vocab import DraftKind, DraftStance, DraftStatus, Reaction, ReplyMode, RunStatus
from canopy.runs import drafts, worker
from tests.canopy.helpers import APPROVE, DRAFTS_PR, KEY, TRACKER_POSTS, all_drafts, present, tracker_holds
from tests.canopy.scenario_helpers import dispatches, sends_drafts

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import JsonValue

    from tests.canopy.scenario_helpers import Ran, Scenario

PR = DRAFTS_PR
ISSUE = "https://github.com/acme/api/issues/1"
REPLY = "Renamed it.\n\n```python\nretries = 3\n```"
THREAD = {"on": "thread", "pr": PR, "comment": 501, "did": "changed", "text": REPLY}
#: KEY's run on its `work` branch, as each drafting run here is.
WORK = dispatches(slug="work")
#: Workers post their own replies, as before drafts (DESIGN §29); APPROVE has them draft replies for the operator.
POST = {"review_replies": "post"}
#: What the run's note says when its `result` tool took no result.
NO_RESULT = "the worker reported no result"
#: Drafts of the wrong shape, each with what the write behind the tool says of it, and a ticket's draft from a run
#: asked for none.
MISSHAPEN: list[tuple[JsonValue, str]] = [
    ("a reply", "it is not an object"),
    ({"on": "review", "pr": PR, "text": "x"}, "its `on` is not thread, pr, or ticket"),
    ({**THREAD, "comment": "501"}, "its `comment` is not a review comment's id"),
    ({**THREAD, "did": "maybe"}, "its `did` is not changed, declined, or answered"),
    ({"on": "ticket", "url": ISSUE, "text": "Done."}, "no_post: this run was asked for no ticket's draft"),
    ({**THREAD, "react": "thumbsup"}, "its `react` is not one of +1, -1, laugh, confused, heart, hooray, rocket, eyes"),
    (
        {"on": "pr", "pr": PR, "text": "Fixed CI.", "react": "+1"},
        "its `react` is on a draft that is not a thread's; only a review comment takes one",
    ),
]


@pytest.fixture(autouse=True)
def github_down(github_state: Path, scenario: Scenario) -> None:
    """GitHub cannot be reached, so the read after a run reads nothing and its drafts stay unchecked.

    The sources read the world once before it goes down, so a dispatch rests on a fresh read of the branches.
    """
    tracker_holds(scenario.conn)
    github_state.write_text(json.dumps({"down": True}))


def refused(conn: sqlite3.Connection, run: Ran) -> list[tuple[int, str]]:
    found = present(replies.run_replies(conn, run.id))
    return [(r.number, r.why) for r in drafts.refused_of(found)]


@pytest.mark.usefixtures("git_pool")
def test_under_post_a_workers_drafts_are_stored_nowhere(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=POST)
    # A run that posts its own comments is asked for no draft, so its tool refuses a result that carries one.
    run = scenario.run(WORK, worker=sends_drafts([THREAD]))
    assert (run.status, json.loads(run.row["result_json"])["harness"]) == (RunStatus.UNKNOWN, NO_RESULT)
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
        {**THREAD, "pr": "https://github.com/acme/web/pull/9"},
        {**THREAD, "text": "  "},
        {**THREAD, "text": "x" * 4001},
        {**THREAD, "text": "Done\u200b."},
        {**THREAD, "text": "Use token ghp_abcdefghijklmnopqrstuvwxyz0123456789."},
        {"on": "pr", "pr": PR, "text": "One."},
        {"on": "pr", "pr": PR, "text": "Two."},
        THREAD,
    ]
    run = scenario.run(WORK, worker=sends_drafts(entries))
    assert [(d.number, d.kind) for d in all_drafts(conn)] == [(6, DraftKind.PR), (8, DraftKind.THREAD)]
    assert refused(conn, run) == [
        (1, "not_ours: its `pr` is not one of this run's PRs"),
        (2, "its text is blank"),
        (3, "its text is 4001 characters, over 4000"),
        (4, "its text holds U+200B (ZERO WIDTH SPACE), a character that hides text"),
        (5, "its text looks like it holds a secret"),
        (7, f"a second draft for {PR}'s own comment; a PR takes one"),
    ]


@pytest.mark.parametrize("entry", [entry for entry, _ in MISSHAPEN], ids=[why for _, why in MISSHAPEN])
def test_the_tool_refuses_a_draft_of_the_wrong_shape(entry: JsonValue) -> None:
    """The run's tool holds each draft to its shape, so the worker is told while it can still send it again."""
    asked = worker.WORKER.input([replies.DRAFTS_GROUP])
    asked.model_validate({"status": "done", "drafts": [THREAD, {"on": "pr", "pr": PR, "text": "One."}]})
    with pytest.raises(pydantic.ValidationError, match="drafts"):
        asked.model_validate({"status": "done", "drafts": [entry]})


@pytest.mark.usefixtures("git_pool")
def test_behind_the_tool_a_draft_of_the_wrong_shape_is_refused_alone(scenario: Scenario) -> None:
    """The write checks each entry itself, whatever the tool let through: a bad one costs only itself."""
    conn = scenario.conn
    scenario.configures("private", trust=APPROVE)
    run = scenario.run(WORK, worker=sends_drafts([]))
    with db.transaction(conn):
        found = drafts.record_run(conn, run.id, drafts.Fields(drafts=[*(entry for entry, _ in MISSHAPEN), THREAD]))
    assert [(r.number, r.why) for r in found] == [(n, why) for n, (_, why) in enumerate(MISSHAPEN, start=1)]
    assert refused(conn, run) == [(r.number, r.why) for r in found]
    assert [(d.number, d.kind) for d in all_drafts(conn)] == [(len(MISSHAPEN) + 1, DraftKind.THREAD)]


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
def test_a_thread_draft_with_neither_words_nor_a_reaction_is_refused(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=APPROVE)
    entries = [
        {"on": "thread", "pr": PR, "comment": 502, "did": "changed"},
        {**THREAD, "text": "  ", "react": "eyes"},
    ]
    run = scenario.run(WORK, worker=sends_drafts(entries))
    assert all_drafts(conn) == []
    assert refused(conn, run) == [
        (1, "its text is not a string"),
        (2, "its text is blank"),
    ]


@pytest.mark.usefixtures("git_pool")
def test_a_run_drafts_at_most_thirty(scenario: Scenario) -> None:
    scenario.configures("private", trust=APPROVE)
    run = scenario.run(WORK, worker=sends_drafts([{**THREAD, "comment": 500 + n} for n in range(32)]))
    assert len(all_drafts(scenario.conn)) == 30
    assert refused(scenario.conn, run) == [(31, "over 30 drafts a run"), (32, "over 30 drafts a run")]


@pytest.mark.usefixtures("git_pool")
def test_drafts_that_are_not_a_list_are_refused(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=APPROVE)
    # The tool takes a list alone, so a worker that never sends one reported no result.
    run = scenario.run(WORK, worker=sends_drafts({"on": "thread"}))
    assert (run.status, json.loads(run.row["result_json"])["harness"]) == (RunStatus.UNKNOWN, NO_RESULT)
    assert all_drafts(conn) == []
    # Behind the tool, the write refuses it too.
    with db.transaction(conn):
        drafts.record_run(conn, run.id, drafts.Fields(drafts={"on": "thread"}))
    assert all_drafts(conn) == []
    assert refused(conn, run) == [(0, "`drafts` is not a list")]


@pytest.mark.usefixtures("git_pool")
def test_with_a_tracker_that_posts_a_ticket_draft_waits_at_once(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=APPROVE, connect=TRACKER_POSTS)
    ticket = {"on": "ticket", "url": ISSUE, "text": "Which base?"}
    run = scenario.run(
        WORK,
        worker=sends_drafts([{**ticket, "url": "http://x/1"}, ticket, {**ticket, "text": "Again?"}]),
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
    assert "on its PRs and its ticket goes in your result's `drafts`" in run.prompt


@pytest.mark.usefixtures("git_pool")
def test_under_approve_the_prompt_asks_for_drafts_and_posts_nothing(scenario: Scenario) -> None:
    scenario.configures("private", trust=APPROVE)
    text = scenario.run(WORK, worker=sends_drafts([])).prompt
    assert "Each comment you would otherwise have posted on its PRs goes in your result's `drafts`" in text
    assert "its PRs and its ticket" not in text
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
