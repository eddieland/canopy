"""The operator's verbs on drafts (DESIGN §29, Sending): edit, drop, send, and settle, through `canopy draft`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from canopy.core import drafts, drafts_manage, observe
from canopy.core.vocab import DraftStatus, ResumeReason, RunKind
from canopy.infra import logs, procs
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
)
from tests.canopy.scenario_helpers import dispatches, sends_drafts

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from canopy.core.config import Config
    from canopy.core.context import Context
    from tests.canopy.scenario_helpers import Scenario

PR = DRAFTS_PR
OLD = "2020-01-01T00:00:00Z"
ISSUE = "https://github.com/acme/api/issues/1"
#: A resume of KEY for its PR's review.
RESUME = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW])


def drafted_run(scenario: Scenario, state: Path, entries: object, connect: Mapping[str, object] | None = None) -> int:
    """A run whose drafts `entries` were checked against a PR holding comments 501 and 502, on two threads."""
    scenario.configures("private", trust=APPROVE, **({"connect": connect} if connect else {}))
    github_has(state, {**comment(501), "time": OLD}, {**comment(502, "PRRT_2"), "time": OLD})
    return scenario.run(dispatches(slug="work"), worker=sends_drafts(entries)).id


def hashed(conn: sqlite3.Connection, run_id: int, number: int) -> str:
    draft = drafts_manage.find(conn, run_id, number)
    return f"{number}@{drafts_manage.hash_of(drafts.text_of(conn, draft.id).body)}"


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
    scenario: Scenario, github_state: Path
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
    scenario: Scenario, github_state: Path
) -> None:
    run_id = drafted_run(scenario, github_state, [thread(501)])
    seen = hashed(scenario.conn, run_id, 1)
    read = observe.read

    def edited_meanwhile(
        conn: sqlite3.Connection, config: Config, runner: procs.Runner, prs: Collection[str], log: logs.TickAdapter
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
    assert draft.basis == "2099-01-01T00:00:00Z"
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
    scenario: Scenario, github_state: Path
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
    scenario: Scenario, github_state: Path, ctx: Context, *, posted: bool, status: DraftStatus
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
    drafted.reconcile(ctx, logs.for_tick(None))
    settled = present(drafts.get(conn, draft.id))
    assert settled.status is status
    if posted:
        assert settled.sent_review_id == draft.pending_review_id
        assert settled.sent_comment_id is not None


@pytest.mark.usefixtures("git_pool")
def test_a_tickets_draft_posts_through_the_trackers_command_and_is_settled_by_the_operator(
    scenario: Scenario, github_state: Path
) -> None:
    conn = scenario.conn
    ticket = {"on": "ticket", "url": ISSUE, "text": "Which base should this target?"}
    run_id = drafted_run(scenario, github_state, [ticket], TRACKER_POSTS)
    scenario.operator("draft", "send", f"run:{run_id}", hashed(conn, run_id, 1))
    assert reads(github_state, "post") == [{"issue": ISSUE, "ticket": "PROJ-1", "body": ticket["text"]}]
    [draft] = all_drafts(conn)
    assert draft.status is DraftStatus.SENT
    assert draft.sent_url is not None

    second = scenario.run(RESUME, worker=sends_drafts([ticket])).id
    github_state.write_text(json.dumps({**state_of(github_state), "post": "unknown", "posted": True}))
    scenario.operator("draft", "send", f"run:{second}", hashed(conn, second, 1), code=1)
    assert drafts_manage.find(conn, second, 1).status is DraftStatus.UNCONFIRMED
    scenario.operator("draft", "settle", f"run:{second}", "1", "--sent")
    assert drafts_manage.find(conn, second, 1).status is DraftStatus.SENT


@pytest.mark.usefixtures("git_pool")
def test_list_and_show_print_each_draft_with_its_thread_and_hash(scenario: Scenario, github_state: Path) -> None:
    run_id = drafted_run(scenario, github_state, [thread(501), thread(999)])
    out = scenario.operator("draft", "list").out
    assert "Review replies: approve." in out
    assert f"run:{run_id} 1  waiting  a reply to comment 501 on {PR} (changed)" in out
    assert f"> alice at {OLD}: Rename this." in out
    assert f"hash {drafts_manage.hash_of('Renamed.')}:\n    Renamed." in out
    assert "comment 999" not in out
    out = scenario.operator("draft", "show", f"run:{run_id}").out
    assert f"2: unknown_thread: {PR} has no review comment 999" in out


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
    text = scenario.run(RESUME, worker=sends_drafts([])).prompt
    assert (
        f"The operator already sent these through canopy, unmarked, as their own: {PR}: comments "
        f"{sent.sent_comment_id}, reviews {sent.sent_review_id}." in text
    )
