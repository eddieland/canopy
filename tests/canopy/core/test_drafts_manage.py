"""The operator's verbs on drafts (DESIGN §29, Sending): edit, drop, send, and settle, through `canopy draft`."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from canopy.core import drafts, drafts_manage
from canopy.core.vocab import DraftStatus
from canopy.infra import logs
from canopy.runs import drafted
from tests.canopy.helpers import (
    DRAFTS_PR,
    all_drafts,
    approving,
    comment,
    github_has,
    operator,
    present,
    reads,
    run_drafting,
    thread,
)

if TYPE_CHECKING:
    from canopy.core.context import Context
    from tests.conftest import CanopyEnv

PR = DRAFTS_PR
OLD = "2020-01-01T00:00:00Z"
ISSUE = "https://github.com/acme/api/issues/1"
TRACKER_POSTS = '\n[connect.sources.issues]\nkind = "tracker"\npost_cmd = "canopy-post-github"\n'


def drafted_run(canopy_env: CanopyEnv, conn: sqlite3.Connection, state: Path, entries: object, extra: str = "") -> int:
    """A run whose drafts `entries` were checked against a PR holding comments 501 and 502, on two threads."""
    approving(canopy_env, extra)
    github_has(state, {**comment(501), "time": OLD}, {**comment(502, "PRRT_2"), "time": OLD})
    run = run_drafting(conn, entries)
    return int(run["id"])


def hashed(conn: sqlite3.Connection, run_id: int, number: int) -> str:
    draft = drafts_manage.find(conn, run_id, number)
    return f"{number}@{drafts_manage.hash_of(drafts.text_of(conn, draft.id).body)}"


def state_of(path: Path) -> dict[str, Any]:
    found: dict[str, Any] = json.loads(path.read_text())
    return found


@pytest.mark.usefixtures("git_pool")
def test_drafts_sent_together_post_their_text_verbatim_as_one_review(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reply = "Renamed.\n\nSee `app.py`."
    entries = [thread(501, text=reply), thread(502, "answered", "Because."), {"on": "pr", "pr": PR, "text": "Done."}]
    run_id = drafted_run(canopy_env, conn, github_state, entries)
    capsys.readouterr()
    assert operator("draft", "send", f"run:{run_id}", *(hashed(conn, run_id, n) for n in (1, 2, 3))) == 0
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
    assert "Sent run" in capsys.readouterr().out
    # GitHub holds exactly the text, under the operator's login, with no mark.
    texts = [r["body"] for r in state_of(github_state)["prs"][PR]["reviews"] if r.get("author") == "me"]
    assert texts == [reply, "Because.", "Done."]


@pytest.mark.usefixtures("git_pool")
def test_a_second_send_posts_nothing(canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path) -> None:
    run_id = drafted_run(canopy_env, conn, github_state, [thread(501)])
    wanted = hashed(conn, run_id, 1)
    assert operator("draft", "send", f"run:{run_id}", wanted) == 0
    assert operator("draft", "send", f"run:{run_id}", wanted) == 0
    assert len(reads(github_state, "post")) == 1


@pytest.mark.usefixtures("git_pool")
def test_an_edit_since_the_operator_read_the_draft_refuses_the_send_stale(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = drafted_run(canopy_env, conn, github_state, [thread(501)])
    seen = hashed(conn, run_id, 1)
    assert operator("draft", "edit", f"run:{run_id}", "1", "--text", "Renamed it to `retries`.") == 0
    capsys.readouterr()
    assert operator("draft", "send", f"run:{run_id}", seen) == 1
    assert "send refused (stale)" in capsys.readouterr().err
    assert reads(github_state, "post") == []
    assert operator("draft", "send", f"run:{run_id}", hashed(conn, run_id, 1)) == 0
    [posted] = reads(github_state, "post")
    assert posted["replies"] == [{"comment": 501, "text": "Renamed it to `retries`."}]
    [draft] = all_drafts(conn)
    assert drafts.text_of(conn, draft.id).version == 2


@pytest.mark.usefixtures("git_pool")
def test_a_comment_since_the_draft_refuses_the_send_once_and_names_it(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = drafted_run(canopy_env, conn, github_state, [thread(501)])
    state = state_of(github_state)
    newer = {**comment(510, author="bob", body="Also the docstring."), "time": "2099-01-01T00:00:00Z"}
    state["prs"][PR]["reviews"].append(newer)
    github_state.write_text(json.dumps(state))
    wanted = hashed(conn, run_id, 1)
    capsys.readouterr()
    assert operator("draft", "send", f"run:{run_id}", wanted) == 1
    err = capsys.readouterr().err
    assert "send refused (thread_changed)" in err
    assert "comment 510 by bob: Also the docstring." in err
    assert reads(github_state, "post") == []
    [draft] = all_drafts(conn)
    assert draft.basis == "2099-01-01T00:00:00Z"
    # The operator has seen it: sending again posts.
    assert operator("draft", "send", f"run:{run_id}", wanted) == 0
    assert len(reads(github_state, "post")) == 1


@pytest.mark.usefixtures("git_pool")
def test_a_draft_that_waits_on_a_read_cannot_be_sent(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    approving(canopy_env)
    github_has(github_state, comment(501), down=True)
    run_id = int(run_drafting(conn, [thread(501)])["id"])
    capsys.readouterr()
    assert operator("draft", "send", f"run:{run_id}", hashed(conn, run_id, 1)) == 1
    assert "send refused (unchecked)" in capsys.readouterr().err
    assert reads(github_state, "post") == []


@pytest.mark.usefixtures("git_pool")
def test_the_draft_verbs_refuse_inside_a_run(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = drafted_run(canopy_env, conn, github_state, [thread(501)])
    capsys.readouterr()
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": str(run_id)}):
        assert operator("draft", "send", f"run:{run_id}", hashed(conn, run_id, 1)) == 1
        assert operator("draft", "edit", f"run:{run_id}", "1", "--text", "x") == 1
        assert operator("draft", "drop", f"run:{run_id}", "1") == 1
    err = capsys.readouterr().err
    assert err.count("(inside_run)") == 3
    assert reads(github_state, "post") == []


@pytest.mark.usefixtures("git_pool")
def test_a_dropped_draft_is_not_sent_until_the_drop_is_taken_back(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = drafted_run(canopy_env, conn, github_state, [thread(501)])
    wanted = hashed(conn, run_id, 1)
    assert operator("draft", "drop", f"run:{run_id}", "1") == 0
    capsys.readouterr()
    assert operator("draft", "send", f"run:{run_id}", wanted) == 1
    assert "send refused (dropped)" in capsys.readouterr().err
    assert operator("draft", "drop", f"run:{run_id}", "1", "--undo") == 0
    assert present(drafts.get(conn, all_drafts(conn)[0].id)).status is DraftStatus.WAITING
    assert operator("draft", "send", f"run:{run_id}", wanted) == 0


@pytest.mark.usefixtures("git_pool")
def test_a_refused_post_leaves_the_drafts_waiting_and_names_its_pending_review_for_the_next(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = drafted_run(canopy_env, conn, github_state, [thread(501)])
    state = state_of(github_state)
    github_state.write_text(json.dumps({**state, "post": "pending_left"}))
    wanted = hashed(conn, run_id, 1)
    capsys.readouterr()
    assert operator("draft", "send", f"run:{run_id}", wanted) == 1
    assert "was not sent: nothing was posted" in capsys.readouterr().out
    [draft] = all_drafts(conn)
    assert draft.status is DraftStatus.WAITING
    assert draft.pending_review is not None
    github_state.write_text(json.dumps({**state_of(github_state), "post": "ok"}))
    assert operator("draft", "send", f"run:{run_id}", wanted) == 0
    assert reads(github_state, "post")[-1]["delete_pending"] == draft.pending_review
    assert present(drafts.get(conn, draft.id)).pending_review is None


@pytest.mark.usefixtures("git_pool")
@pytest.mark.parametrize(("posted", "status"), [(True, DraftStatus.SENT), (False, DraftStatus.WAITING)])
def test_an_unconfirmed_send_is_settled_by_a_read_never_by_sending_again(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    github_state: Path,
    ctx: Context,
    capsys: pytest.CaptureFixture[str],
    *,
    posted: bool,
    status: DraftStatus,
) -> None:
    run_id = drafted_run(canopy_env, conn, github_state, [thread(501)])
    github_state.write_text(json.dumps({**state_of(github_state), "post": "unknown", "posted": posted}))
    wanted = hashed(conn, run_id, 1)
    capsys.readouterr()
    assert operator("draft", "send", f"run:{run_id}", wanted) == 1
    assert "may have been posted" in capsys.readouterr().out
    [draft] = all_drafts(conn)
    assert draft.status is DraftStatus.UNCONFIRMED
    assert draft.pending_review_id is not None
    assert operator("draft", "send", f"run:{run_id}", wanted) == 1
    assert "send refused (unconfirmed)" in capsys.readouterr().err
    assert len(reads(github_state, "post")) == 1
    drafted.reconcile(ctx, logs.for_tick(None))
    settled = present(drafts.get(conn, draft.id))
    assert settled.status is status
    if posted:
        assert settled.sent_review_id == draft.pending_review_id
        assert settled.sent_comment_id is not None


@pytest.mark.usefixtures("git_pool")
def test_a_tickets_draft_posts_through_the_trackers_command_and_is_settled_by_the_operator(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path
) -> None:
    ticket = {"on": "ticket", "url": ISSUE, "text": "Which base should this target?"}
    run_id = drafted_run(canopy_env, conn, github_state, [ticket], TRACKER_POSTS)
    assert operator("draft", "send", f"run:{run_id}", hashed(conn, run_id, 1)) == 0
    assert reads(github_state, "post") == [{"issue": ISSUE, "ticket": "PROJ-1", "body": ticket["text"]}]
    [draft] = all_drafts(conn)
    assert draft.status is DraftStatus.SENT
    assert draft.sent_url is not None

    second = int(
        run_drafting(conn, [ticket], "--label", "agent-ready-tester", "--kind", "resume", "--reason", "review")["id"]
    )
    github_state.write_text(json.dumps({**state_of(github_state), "post": "unknown", "posted": True}))
    assert operator("draft", "send", f"run:{second}", hashed(conn, second, 1)) == 1
    assert drafts_manage.find(conn, second, 1).status is DraftStatus.UNCONFIRMED
    assert operator("draft", "settle", f"run:{second}", "1", "--sent") == 0
    assert drafts_manage.find(conn, second, 1).status is DraftStatus.SENT


@pytest.mark.usefixtures("git_pool")
def test_list_and_show_print_each_draft_with_its_thread_and_hash(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = drafted_run(canopy_env, conn, github_state, [thread(501), thread(999)])
    capsys.readouterr()
    assert operator("draft", "list") == 0
    out = capsys.readouterr().out
    assert "Review replies: approve." in out
    assert f"run:{run_id} 1  waiting  a reply to comment 501 on {PR} (changed)" in out
    assert f"> alice at {OLD}: Rename this." in out
    assert f"hash {drafts_manage.hash_of('Renamed.')}:\n    Renamed." in out
    assert "comment 999" not in out
    assert operator("draft", "show", f"run:{run_id}") == 0
    out = capsys.readouterr().out
    assert f"2: unknown_thread: {PR} has no review comment 999" in out


@pytest.mark.usefixtures("git_pool")
def test_status_says_how_replies_go_and_how_many_drafts_wait(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert operator("status") == 0
    assert "Review replies" not in capsys.readouterr().out
    drafted_run(canopy_env, conn, github_state, [thread(501), thread(502)])
    capsys.readouterr()
    assert operator("status") == 0
    out = capsys.readouterr().out
    assert (
        "Review replies: approve, workers draft their comments for you; 2 drafts wait on you: `canopy draft list`"
        in out
    )
