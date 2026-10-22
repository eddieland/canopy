"""The operator's verbs on drafts (DESIGN §29, Sending): edit, drop, send, stage, and settle, through `canopy draft`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from canopy.core import drafts, drafts_manage, observe
from canopy.core.vocab import DraftStatus, Reaction, ResumeReason, RunKind
from canopy.runs import drafted
from tests.canopy.helpers import (
    APPROVE,
    DRAFTS_PR,
    TRACKER_POSTS,
    all_drafts,
    comment,
    github_has,
    in_run,
    present,
    reads,
    thread,
    tick_reads,
)
from tests.canopy.scenario_helpers import dispatches, sends_drafts
from tests.conftest import executable

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from canopy.core.config import Config
    from canopy.core.context import Context
    from canopy.infra import logs, procs
    from tests.canopy.scenario_helpers import Scenario

PR = DRAFTS_PR
OLD = "2020-01-01T00:00:00Z"
ISSUE = "https://github.com/acme/api/issues/1"
#: A resume of KEY for a conflict on its PR: a reason no observation has to authorize, which the drafts do not need.
RESUME = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CONFLICT])


def drafted_run(scenario: Scenario, state: Path, entries: object, connect: Mapping[str, object] | None = None) -> int:
    """A run whose drafts `entries` were checked against a PR holding comments 501 and 502, on two threads."""
    scenario.configures("private", trust=APPROVE, **({"connect": connect} if connect else {}))
    github_has(state, {**comment(501), "time": OLD}, {**comment(502, "PRRT_2"), "time": OLD})
    return scenario.run(dispatches(slug="work"), worker=sends_drafts(entries)).id


def hashed(conn: sqlite3.Connection, run_id: int, number: int) -> str:
    draft = drafts_manage.find(conn, run_id, number)
    return f"{number}@{drafts_manage.hash_of_version(drafts.text_of(conn, draft.id))}"


def state_of(path: Path) -> dict[str, Any]:
    found: dict[str, Any] = json.loads(path.read_text())
    return found


@pytest.mark.usefixtures("git_pool")
def test_drafts_sent_together_post_their_text_verbatim_as_one_review(scenario: Scenario, github_state: Path) -> None:
    conn = scenario.conn
    reply = "Renamed.\n\nSee `app.py`."
    entries = [thread(501, text=reply), thread(502, "answered", "Because."), {"on": "pr", "pr": PR, "text": "Done."}]
    run_id = drafted_run(scenario, github_state, entries)
    sent = scenario.operator("draft", "send", f"run:{run_id}", *(hashed(conn, run_id, n) for n in (1, 2, 3)))
    [posted] = reads(github_state, "post")
    assert posted == {
        "pr": PR,
        "delete_pending": None,
        "body": "Done.",
        "replies": [{"comment": 501, "text": reply}, {"comment": 502, "text": "Because."}],
    }
    first, second, body = all_drafts(conn)
    assert {d.status for d in (first, second, body)} == {DraftStatus.SENT}
    assert first.sent_comment_id is not None
    assert first.sent_url == f"{PR}#discussion_r{first.sent_comment_id}"
    assert body.sent_comment_id is None
    assert body.sent_review_id == first.sent_review_id
    assert body.sent_url == f"{PR}#pullrequestreview-{body.sent_review_id}"
    assert first.sent_channel == "cli"
    assert "Sent run" in sent.out
    # GitHub holds exactly the text, under the operator's login, with no mark.
    texts = [r["body"] for r in state_of(github_state)["prs"][PR]["reviews"] if r.get("author") == "me"]
    assert texts == [reply, "Because.", "Done."]


@pytest.mark.usefixtures("git_pool")
def test_a_second_send_posts_nothing(scenario: Scenario, github_state: Path) -> None:
    run_id = drafted_run(scenario, github_state, [thread(501)])
    wanted = hashed(scenario.conn, run_id, 1)
    scenario.operator("draft", "send", f"run:{run_id}", wanted)
    scenario.operator("draft", "send", f"run:{run_id}", wanted)
    assert len(reads(github_state, "post")) == 1


@pytest.mark.usefixtures("git_pool")
def test_an_edit_since_the_operator_read_the_draft_refuses_the_send_stale(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    run_id = drafted_run(scenario, github_state, [thread(501)])
    seen = hashed(conn, run_id, 1)
    scenario.operator("draft", "edit", f"run:{run_id}", "1", "--text", "Renamed it to `retries`.")
    refused = scenario.operator("draft", "send", f"run:{run_id}", seen, code=1)
    assert "send refused (stale)" in refused.err
    assert reads(github_state, "post") == []
    scenario.operator("draft", "send", f"run:{run_id}", hashed(conn, run_id, 1))
    [posted] = reads(github_state, "post")
    assert posted["replies"] == [{"comment": 501, "text": "Renamed it to `retries`."}]
    [draft] = all_drafts(conn)
    assert drafts.text_of(conn, draft.id).version == 2


@pytest.mark.usefixtures("git_pool")
def test_an_edit_while_the_send_reads_the_pr_refuses_it_stale_and_posts_nothing(
    scenario: Scenario,
    github_state: Path,
) -> None:
    run_id = drafted_run(scenario, github_state, [thread(501)])
    seen = hashed(scenario.conn, run_id, 1)
    read = observe.read

    def edited_meanwhile(
        conn: sqlite3.Connection,
        config: Config,
        runner: procs.Runner,
        prs: Collection[str],
        log: logs.TickAdapter,
    ) -> observe.Read:
        # The operator edits in another tab while the send reads the PR again, after it checked the hash.
        found = read(conn, config, runner, prs, log)
        scenario.operator("draft", "edit", f"run:{run_id}", "1", "--text", "Not what was seen.")
        return found

    with mock.patch.object(observe, "read", autospec=True, side_effect=edited_meanwhile):
        refused = scenario.operator("draft", "send", f"run:{run_id}", seen, code=1)
    assert "send refused (stale)" in refused.err
    assert reads(github_state, "post") == []
    assert drafts_manage.find(scenario.conn, run_id, 1).status is DraftStatus.WAITING


@pytest.mark.usefixtures("git_pool")
def test_a_comment_since_the_draft_refuses_the_send_once_and_names_it(scenario: Scenario, github_state: Path) -> None:
    run_id = drafted_run(scenario, github_state, [thread(501)])
    state = state_of(github_state)
    newer = {**comment(510, author="bob", body="Also the docstring."), "time": "2099-01-01T00:00:00Z"}
    state["prs"][PR]["reviews"].append(newer)
    github_state.write_text(json.dumps(state))
    wanted = hashed(scenario.conn, run_id, 1)
    err = scenario.operator("draft", "send", f"run:{run_id}", wanted, code=1).err
    assert "send refused (thread_changed)" in err
    assert "comment 510 by bob: Also the docstring." in err
    assert reads(github_state, "post") == []
    [draft] = all_drafts(scenario.conn)
    assert draft.basis == "2099-01-01T00:00:00.000Z"
    # The operator has seen it: sending again posts.
    scenario.operator("draft", "send", f"run:{run_id}", wanted)
    assert len(reads(github_state, "post")) == 1


@pytest.mark.usefixtures("git_pool")
def test_a_draft_that_waits_on_a_read_cannot_be_sent(scenario: Scenario, github_state: Path) -> None:
    scenario.configures("private", trust=APPROVE)
    github_has(github_state, comment(501), down=True)
    run_id = scenario.run(dispatches(slug="work"), worker=sends_drafts([thread(501)])).id
    refused = scenario.operator("draft", "send", f"run:{run_id}", hashed(scenario.conn, run_id, 1), code=1)
    assert "send refused (unchecked)" in refused.err
    assert reads(github_state, "post") == []


@pytest.mark.usefixtures("git_pool")
def test_the_draft_verbs_refuse_inside_a_run(scenario: Scenario, github_state: Path) -> None:
    run_id = drafted_run(scenario, github_state, [thread(501)])
    wanted = hashed(scenario.conn, run_id, 1)
    with in_run(run_id):
        refusals = [
            scenario.operator("draft", "send", f"run:{run_id}", wanted, code=1),
            scenario.operator("draft", "edit", f"run:{run_id}", "1", "--text", "x", code=1),
            scenario.operator("draft", "drop", f"run:{run_id}", "1", code=1),
        ]
    assert ["(inside_run)" in refused.err for refused in refusals] == [True, True, True]
    assert reads(github_state, "post") == []


@pytest.mark.usefixtures("git_pool")
def test_a_dropped_draft_is_not_sent_until_the_drop_is_taken_back(scenario: Scenario, github_state: Path) -> None:
    conn = scenario.conn
    run_id = drafted_run(scenario, github_state, [thread(501)])
    wanted = hashed(conn, run_id, 1)
    scenario.operator("draft", "drop", f"run:{run_id}", "1")
    assert "send refused (dropped)" in scenario.operator("draft", "send", f"run:{run_id}", wanted, code=1).err
    scenario.operator("draft", "drop", f"run:{run_id}", "1", "--undo")
    assert present(drafts.get(conn, all_drafts(conn)[0].id)).status is DraftStatus.WAITING
    scenario.operator("draft", "send", f"run:{run_id}", wanted)


@pytest.mark.usefixtures("git_pool")
def test_a_refused_post_leaves_the_drafts_waiting_and_names_its_pending_review_for_the_next(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    run_id = drafted_run(scenario, github_state, [thread(501)])
    state = state_of(github_state)
    github_state.write_text(json.dumps({**state, "post": "pending_left"}))
    wanted = hashed(conn, run_id, 1)
    unsent = scenario.operator("draft", "send", f"run:{run_id}", wanted, code=1)
    assert "was not sent: nothing was posted" in unsent.out
    [draft] = all_drafts(conn)
    assert draft.status is DraftStatus.WAITING
    assert draft.pending_review is not None
    github_state.write_text(json.dumps({**state_of(github_state), "post": "ok"}))
    scenario.operator("draft", "send", f"run:{run_id}", wanted)
    assert reads(github_state, "post")[-1]["delete_pending"] == draft.pending_review
    assert present(drafts.get(conn, draft.id)).pending_review is None


@pytest.mark.usefixtures("git_pool")
@pytest.mark.parametrize(("posted", "status"), [(True, DraftStatus.SENT), (False, DraftStatus.WAITING)])
def test_an_unconfirmed_send_is_settled_by_a_read_never_by_sending_again(
    scenario: Scenario,
    github_state: Path,
    ctx: Context,
    *,
    posted: bool,
    status: DraftStatus,
) -> None:
    conn = scenario.conn
    run_id = drafted_run(scenario, github_state, [thread(501)])
    github_state.write_text(json.dumps({**state_of(github_state), "post": "unknown", "posted": posted}))
    wanted = hashed(conn, run_id, 1)
    assert "may have been posted" in scenario.operator("draft", "send", f"run:{run_id}", wanted, code=1).out
    [draft] = all_drafts(conn)
    assert draft.status is DraftStatus.UNCONFIRMED
    assert draft.pending_review_id is not None
    refused = scenario.operator("draft", "send", f"run:{run_id}", wanted, code=1)
    assert "send refused (unconfirmed)" in refused.err
    assert len(reads(github_state, "post")) == 1
    tick_reads(ctx)
    settled = present(drafts.get(conn, draft.id))
    assert settled.status is status
    if posted:
        assert settled.sent_review_id == draft.pending_review_id
        assert settled.sent_comment_id is not None


@pytest.mark.usefixtures("git_pool")
def test_a_tickets_draft_posts_through_the_trackers_command_and_is_settled_by_the_operator(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    ticket = {"on": "ticket", "url": ISSUE, "text": "Which base should this target?"}
    run_id = drafted_run(scenario, github_state, [ticket], TRACKER_POSTS)
    scenario.operator("draft", "send", f"run:{run_id}", hashed(conn, run_id, 1))
    assert reads(github_state, "post") == [{"issue": ISSUE, "ticket": "PROJ-1", "body": ticket["text"]}]
    [draft] = all_drafts(conn)
    assert draft.status is DraftStatus.SENT
    assert draft.sent_url is not None

    scenario.polls()
    second = scenario.run(RESUME, worker=sends_drafts([ticket])).id
    github_state.write_text(json.dumps({**state_of(github_state), "post": "unknown", "posted": True}))
    scenario.operator("draft", "send", f"run:{second}", hashed(conn, second, 1), code=1)
    assert drafts_manage.find(conn, second, 1).status is DraftStatus.UNCONFIRMED
    scenario.operator("draft", "settle", f"run:{second}", "1", "--sent")
    assert drafts_manage.find(conn, second, 1).status is DraftStatus.SENT


@pytest.mark.usefixtures("git_pool")
def test_list_and_show_print_each_draft_with_its_thread_and_hash(scenario: Scenario, github_state: Path) -> None:
    reply = "Renamed.\n\nThe old name stays an alias."
    run_id = drafted_run(scenario, github_state, [thread(501, text=reply), thread(999)])
    out = scenario.operator("draft", "list").out
    assert "Review replies: approve." in out
    assert f"run:{run_id} 1  waiting  a reply to comment 501 on {PR} (changed)" in out
    # The fake reader's times come back in the journal's own format.
    assert "> alice at 2020-01-01T00:00:00.000Z: Rename this." in out
    # Each line of a draft prints as a line, never as a named line feed.
    assert f"hash {drafts_manage.hash_of(reply, None)}:\n    Renamed.\n    \n    The old name stays an alias.\n" in out
    assert "comment 999" not in out
    out = scenario.operator("draft", "show", f"run:{run_id}").out
    assert f"2: unknown_thread: {PR} has no review comment 999" in out


@pytest.mark.usefixtures("git_pool")
def test_a_reaction_is_added_with_its_draft_and_one_alone_posts_no_comment(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    alone = {"on": "thread", "pr": PR, "comment": 502, "did": "answered", "react": "heart"}
    run_id = drafted_run(scenario, github_state, [{**thread(501), "react": "+1"}, alone])
    scenario.operator("draft", "send", f"run:{run_id}", hashed(conn, run_id, 1), hashed(conn, run_id, 2))
    [posted] = reads(github_state, "post")
    assert posted["replies"] == [
        {"comment": 501, "text": "Renamed.", "reaction": "+1"},
        {"comment": 502, "reaction": "heart"},
    ]
    assert state_of(github_state)["reactions"] == [
        {"pr": PR, "comment": 501, "reaction": "+1", "by": "me"},
        {"pr": PR, "comment": 502, "reaction": "heart", "by": "me"},
    ]
    beside, only = all_drafts(conn)
    assert (beside.status, beside.reacted) == (DraftStatus.SENT, Reaction.THUMBS_UP)
    assert beside.sent_comment_id is not None
    assert (only.status, only.reacted, only.sent_comment_id) == (DraftStatus.SENT, Reaction.HEART, None)
    assert only.sent_url == f"{PR}#discussion_r502"


@pytest.mark.usefixtures("git_pool")
def test_drafts_that_are_all_reactions_alone_open_no_review(scenario: Scenario, github_state: Path) -> None:
    conn = scenario.conn
    alone = {"on": "thread", "pr": PR, "comment": 501, "did": "changed", "react": "hooray"}
    run_id = drafted_run(scenario, github_state, [alone])
    wanted = hashed(conn, run_id, 1)
    assert f"hash {wanted.split('@')[1]}, the reaction hooray alone\n" in scenario.operator("draft", "list").out
    scenario.operator("draft", "send", f"run:{run_id}", wanted)
    [draft] = all_drafts(conn)
    assert (draft.status, draft.sent_review_id) == (DraftStatus.SENT, None)
    assert [r for r in state_of(github_state)["prs"][PR]["reviews"] if r.get("author") == "me"] == []


@pytest.mark.usefixtures("git_pool")
def test_the_operator_sets_changes_and_clears_a_reaction_and_each_is_a_new_hash(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    run_id = drafted_run(scenario, github_state, [thread(501), {"on": "pr", "pr": PR, "text": "Done."}])
    plain = hashed(conn, run_id, 1)
    scenario.operator("draft", "edit", f"run:{run_id}", "1", "--react", "eyes")
    version = drafts.text_of(conn, drafts_manage.find(conn, run_id, 1).id)
    assert (version.body, version.reaction, version.version) == ("Renamed.", Reaction.EYES, 2)
    assert "send refused (stale)" in scenario.operator("draft", "send", f"run:{run_id}", plain, code=1).err
    scenario.operator("draft", "edit", f"run:{run_id}", "1", "--text", "", "--react", "+1")
    version = drafts.text_of(conn, drafts_manage.find(conn, run_id, 1).id)
    assert (version.body, version.reaction) == ("", Reaction.THUMBS_UP)
    refused = scenario.operator("draft", "edit", f"run:{run_id}", "1", "--no-react", code=1)
    assert "edit refused (bad_text): its text is blank" in refused.err
    scenario.operator("draft", "edit", f"run:{run_id}", "1", "--text", "Renamed.", "--no-react")
    # Back to the run's own words, the draft is named as they were.
    assert hashed(conn, run_id, 1) == plain
    refused = scenario.operator("draft", "edit", f"run:{run_id}", "2", "--react", "+1", code=1)
    assert "edit refused (no_reaction)" in refused.err
    usage = scenario.operator("draft", "edit", f"run:{run_id}", "1", code=2)
    assert "or a reaction with --react or --no-react" in usage.err


@pytest.mark.usefixtures("git_pool")
def test_a_refused_reaction_posts_nothing_and_the_draft_waits(scenario: Scenario, github_state: Path) -> None:
    conn = scenario.conn
    run_id = drafted_run(scenario, github_state, [{**thread(501), "react": "+1"}])
    github_state.write_text(json.dumps({**state_of(github_state), "react": "refused"}))
    unsent = scenario.operator("draft", "send", f"run:{run_id}", hashed(conn, run_id, 1), code=1)
    assert "was not sent: nothing was posted" in unsent.out
    [draft] = all_drafts(conn)
    assert (draft.status, draft.reacted) == (DraftStatus.WAITING, None)
    assert "reactions" not in state_of(github_state)


@pytest.mark.usefixtures("git_pool")
def test_a_review_that_fails_after_its_reaction_keeps_the_reaction_and_sending_again_adds_none(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    run_id = drafted_run(scenario, github_state, [{**thread(501), "react": "+1"}])
    wanted = hashed(conn, run_id, 1)
    github_state.write_text(json.dumps({**state_of(github_state), "post": "pending_left"}))
    scenario.operator("draft", "send", f"run:{run_id}", wanted, code=1)
    [draft] = all_drafts(conn)
    assert (draft.status, draft.reacted) == (DraftStatus.WAITING, Reaction.THUMBS_UP)
    out = scenario.operator("draft", "list").out
    assert "+1 is on comment 501 already: a send that did not post the rest added it" in out
    assert f"hash {wanted.split('@')[1]}, with the reaction +1:\n    Renamed.\n" in out
    github_state.write_text(json.dumps({**state_of(github_state), "post": "ok"}))
    scenario.operator("draft", "send", f"run:{run_id}", wanted)
    assert present(drafts.get(conn, draft.id)).status is DraftStatus.SENT
    assert len(state_of(github_state)["reactions"]) == 1


@pytest.mark.usefixtures("git_pool")
def test_status_says_how_replies_go_and_how_many_drafts_wait(scenario: Scenario, github_state: Path) -> None:
    scenario.configures("private", trust={"review_replies": "post"})
    assert "Review replies" not in scenario.operator("status").out
    # Unset, replies are drafted for the operator.
    scenario.configures("private", trust={"review_replies": None})
    assert "Review replies: approve, workers draft their comments for you\n" in scenario.operator("status").out
    drafted_run(scenario, github_state, [thread(501), thread(502)])
    out = scenario.operator("status").out
    assert (
        "Review replies: approve, workers draft their comments for you; 2 drafts wait on you: `canopy draft list`"
        in out
    )


@pytest.mark.usefixtures("git_pool")
def test_the_next_resume_is_told_what_the_operator_sent(scenario: Scenario, github_state: Path) -> None:
    run_id = drafted_run(scenario, github_state, [thread(501)])
    scenario.operator("draft", "send", f"run:{run_id}", hashed(scenario.conn, run_id, 1))
    [sent] = all_drafts(scenario.conn)
    scenario.polls()
    text = scenario.run(RESUME, worker=sends_drafts([])).prompt
    assert (
        f"The operator already sent these through canopy, unmarked, as their own: {PR}: comments "
        f"{sent.sent_comment_id}, reviews {sent.sent_review_id}." in text
    )


def on_github(state: Path, review_id: int, *, then: str) -> None:
    """The operator acts on their staged review on GitHub: `submit` it, `delete` it, or take its first reply `out`."""
    found = state_of(state)
    lines: list[dict[str, Any]] = found["prs"][PR]["reviews"]
    mine = [line for line in lines if line.get("review") == review_id]
    match then:
        case "submit":
            next(line for line in lines if line["item"] == "review" and line["id"] == review_id)["state"] = "commented"
        case "delete":
            lines[:] = [line for line in lines if line["id"] != review_id and line not in mine]
        case "out":
            lines.remove(mine[0])
            next(line for line in lines if line["item"] == "review" and line["id"] == review_id)["state"] = "commented"
        case _:
            raise AssertionError(then)
    state.write_text(json.dumps(found))


@pytest.mark.usefixtures("git_pool")
def test_staged_drafts_wait_in_one_pending_review_until_the_operator_submits_it_on_github(
    scenario: Scenario,
    github_state: Path,
    ctx: Context,
) -> None:
    conn = scenario.conn
    entries = [thread(501), thread(502, "answered", "Because."), {"on": "pr", "pr": PR, "text": "Done."}]
    run_id = drafted_run(scenario, github_state, entries)
    staged = scenario.operator("draft", "stage", f"run:{run_id}", *(hashed(conn, run_id, n) for n in (1, 2, 3)))
    assert f"Staged run {run_id}'s drafts 1, 2, 3 in a review on {PR}; finish it at {PR}/files" in staged.out
    [posted] = reads(github_state, "post")
    assert posted == {
        "pr": PR,
        "delete_pending": None,
        "body": "Done.",
        "replies": [{"comment": 501, "text": "Renamed."}, {"comment": 502, "text": "Because."}],
        "submit": False,
    }
    first, second, body = all_drafts(conn)
    assert {d.status for d in (first, second, body)} == {DraftStatus.STAGED}
    review = first.pending_review_id
    assert review is not None
    assert first.sent_comment_id is not None
    # The loop knows the replies and the review as the operator's before they submit them.
    assert drafts.sent_by_pr(conn)[PR] == {
        "comments": [first.sent_comment_id, second.sent_comment_id],
        "reviews": [review],
    }
    assert "3 in the review you staged there" in drafted.waiting(conn)[0].detail
    assert "in the review you staged; submit or delete it" in scenario.operator("draft", "list").out
    refused = scenario.operator("draft", "edit", f"run:{run_id}", "1", "--text", "Other.", code=1)
    assert "edit refused (staged)" in refused.err

    tick_reads(ctx)
    assert {d.status for d in all_drafts(conn)} == {DraftStatus.STAGED}
    on_github(github_state, review, then="submit")
    tick_reads(ctx)
    first, second, body = all_drafts(conn)
    assert {d.status for d in (first, second, body)} == {DraftStatus.SENT}
    assert body.sent_review_id == review
    assert first.sent_url == f"{PR}#discussion_r{first.sent_comment_id}"
    assert drafted.waiting(conn) == []
    assert len(reads(github_state, "post")) == 1


@pytest.mark.usefixtures("git_pool")
def test_a_staged_review_deleted_on_github_leaves_its_drafts_waiting_to_send_again(
    scenario: Scenario,
    github_state: Path,
    ctx: Context,
) -> None:
    conn = scenario.conn
    run_id = drafted_run(scenario, github_state, [thread(501)])
    wanted = hashed(conn, run_id, 1)
    scenario.operator("draft", "stage", f"run:{run_id}", wanted)
    [draft] = all_drafts(conn)
    on_github(github_state, present(draft.pending_review_id), then="delete")
    tick_reads(ctx)
    [draft] = all_drafts(conn)
    assert draft.status is DraftStatus.WAITING
    assert draft.why == "the review you staged was deleted on GitHub"
    assert (draft.pending_review, draft.sent_comment_id) == (None, None)
    assert drafts.sent_by_pr(conn) == {}
    scenario.operator("draft", "send", f"run:{run_id}", wanted)
    assert reads(github_state, "post")[-1]["delete_pending"] is None
    assert all_drafts(conn)[0].status is DraftStatus.SENT


@pytest.mark.usefixtures("git_pool")
def test_a_reply_taken_out_of_the_staged_review_before_it_is_submitted_is_dropped(
    scenario: Scenario,
    github_state: Path,
    ctx: Context,
) -> None:
    conn = scenario.conn
    run_id = drafted_run(scenario, github_state, [thread(501), thread(502)])
    scenario.operator("draft", "stage", f"run:{run_id}", hashed(conn, run_id, 1), hashed(conn, run_id, 2))
    on_github(github_state, present(all_drafts(conn)[0].pending_review_id), then="out")
    tick_reads(ctx)
    first, second = all_drafts(conn)
    assert first.status is DraftStatus.DROPPED
    assert first.why == "taken out of the review you staged before you submitted it"
    assert second.status is DraftStatus.SENT
    assert drafts.sent_by_pr(conn)[PR]["comments"] == [second.sent_comment_id]


@pytest.mark.usefixtures("git_pool")
def test_nothing_else_is_sent_or_staged_on_a_pr_while_it_holds_a_staged_review(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    run_id = drafted_run(scenario, github_state, [thread(501), thread(502)])
    first = hashed(conn, run_id, 1)
    scenario.operator("draft", "stage", f"run:{run_id}", first)
    for verb, wanted in (("send", hashed(conn, run_id, 2)), ("stage", hashed(conn, run_id, 2)), ("send", first)):
        refused = scenario.operator("draft", verb, f"run:{run_id}", wanted, code=1)
        assert f"{verb} refused (staged)" in refused.err
        assert "submit or delete it on GitHub" in refused.err
    assert len(reads(github_state, "post")) == 1


@pytest.mark.usefixtures("git_pool")
def test_a_tickets_draft_is_not_staged(scenario: Scenario, github_state: Path) -> None:
    conn = scenario.conn
    ticket = {"on": "ticket", "url": ISSUE, "text": "Which base should this target?"}
    run_id = drafted_run(scenario, github_state, [ticket], TRACKER_POSTS)
    refused = scenario.operator("draft", "stage", f"run:{run_id}", hashed(conn, run_id, 1), code=1)
    assert "stage refused (not_pr)" in refused.err
    assert reads(github_state, "post") == []


@pytest.mark.usefixtures("git_pool")
def test_a_stage_adds_its_reactions_at_once_and_sends_a_reaction_alone(scenario: Scenario, github_state: Path) -> None:
    conn = scenario.conn
    run_id = drafted_run(scenario, github_state, [thread(501), thread(502)])
    scenario.operator("draft", "edit", f"run:{run_id}", "1", "--react", "+1")
    scenario.operator("draft", "edit", f"run:{run_id}", "2", "--text", "", "--react", "heart")
    staged = scenario.operator("draft", "stage", f"run:{run_id}", hashed(conn, run_id, 1), hashed(conn, run_id, 2))
    [posted] = reads(github_state, "post")
    assert posted["replies"] == [
        {"comment": 501, "text": "Renamed.", "reaction": "+1"},
        {"comment": 502, "reaction": "heart"},
    ]
    reactions = {(r["comment"], r["reaction"]) for r in state_of(github_state)["reactions"]}
    assert reactions == {(501, "+1"), (502, "heart")}
    reply, alone = all_drafts(conn)
    assert (reply.status, reply.reacted) == (DraftStatus.STAGED, "+1")
    assert (alone.status, alone.reacted) == (DraftStatus.SENT, "heart")
    assert alone.pending_review_id is None
    assert reply.pending_review_id is not None
    assert f"Run {run_id}'s draft 1 put +1 on comment 501 now, not in the review" in staged.out
    assert f"Run {run_id}'s draft 2 put heart on comment 502 now" in staged.out


@pytest.mark.usefixtures("git_pool")
def test_a_stage_that_names_no_id_for_a_reply_is_unconfirmed_not_staged(
    scenario: Scenario,
    github_state: Path,
    tmp_path: Path,
) -> None:
    conn = scenario.conn
    # A poster that opens the review and says it is staged, but names no comment for the reply.
    lines = [
        {"kind": "as", "login": "me"},
        {"kind": "pending", "review": "PRR_1", "id": 7001},
        {"kind": "end", "submitted": False, "staged": True},
    ]
    printed = "".join(f"print({json.dumps(json.dumps(line))})\n" for line in lines)
    poster = executable(tmp_path / "poster", f"#!/usr/bin/env python3\nimport sys\nsys.stdin.read()\n{printed}")
    vcs = {"sources": {"github": {"kind": "vcs", "cmd": "canopy-connect-github", "post_cmd": str(poster)}}}
    run_id = drafted_run(scenario, github_state, [thread(501)], vcs)
    scenario.operator("draft", "stage", f"run:{run_id}", hashed(conn, run_id, 1), code=1)
    [draft] = all_drafts(conn)
    assert draft.status is DraftStatus.UNCONFIRMED
    assert draft.pending_review_id == 7001
