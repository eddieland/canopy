"""`canopy forget` (DESIGN §22): a ticket's branch and PRs forgotten, so its next implement starts over."""

import json
import sqlite3
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db
from canopy.core.vocab import RunStatus
from canopy.loop import attention
from tests.canopy.helpers import (
    KEY,
    QUESTION,
    InlineRunner,
    blocked_result,
    commit_and_push,
    context,
    dispatch_in_tick,
    last_run,
    operator,
    private_worker_does,
    unit_of,
    worker_does,
)
from tests.conftest import CanopyEnv, GitPool

LABEL = ("--label", "agent-ready-tester")
OLD = f"agent/{KEY}-work"
NEW = f"agent/{KEY}-again"
OLD_PR = "https://example.test/pr/1"
NEW_PR = "https://example.test/pr/2"


def done(branch: str, pr: str) -> str:
    return json.dumps({"status": "done", "branch": branch, "prs": {"repo": pr}, "summary": "did it"})


def work(conn: sqlite3.Connection, *args: str, runner: InlineRunner) -> sqlite3.Row:
    """Dispatch a run for KEY and run it in-process to its end."""
    assert dispatch_in_tick(conn, *args, runner=runner).code == 0
    assert main(["_run", str(last_run(conn)["id"])], runner=runner) == 0
    return last_run(conn)


def test_a_forgotten_ticket_starts_over_on_a_new_branch_and_its_runs_still_count(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = InlineRunner()
    with worker_does(*commit_and_push(OLD), result=done(OLD, OLD_PR)):
        assert work(conn, *LABEL, "--kind", "implement", "--slug", "work", runner=runner)["status"] == "done"
        assert unit_of(conn, KEY)["pr_url"] == OLD_PR
        # Before forgetting, a later implement continues the ticket's branch and names no other.
        assert dispatch_in_tick(conn, *LABEL, "--kind", "implement", "--slug", "again", runner=runner).code == 1
        assert "dispatch refused (bad_slug)" in capsys.readouterr().err

        assert operator("forget", KEY) == 0
        out = capsys.readouterr().out
        assert f"{KEY} is forgotten" in out
        assert f"canopy no longer tracks branch {OLD}, {OLD_PR}." in out
        assert "delete its branch on origin yourself" in out
        assert "its limit is" not in out  # one implement of two
        ticket = db.get_ticket(conn, KEY)
        assert ticket is not None
        assert (ticket.branch, ticket.phase, ticket.done) == (None, None, False)
        assert ticket.forgotten_run_id == last_run(conn)["id"]
        assert db.units(conn, KEY) == []
        # The overseer's state block and the attention list no longer see the run; `show` still does.
        assert KEY not in db.latest_runs(conn)
        assert main(["show", KEY]) == 0
        shown = capsys.readouterr().out
        assert "branch none yet" in shown
        assert "forgotten " in shown
        assert f"run:{last_run(conn)['id']}  implement  done" in shown

    # The next implement names a new branch.
    with worker_does(*commit_and_push(NEW), result=done(NEW, NEW_PR)):
        assert work(conn, *LABEL, "--kind", "implement", "--slug", "again", runner=runner)["branch"] == NEW
        ticket = db.get_ticket(conn, KEY)
        assert ticket is not None
        assert ticket.branch == NEW
        assert unit_of(conn, KEY)["pr_url"] == NEW_PR
        assert db.latest_runs(conn)[KEY]["branch"] == NEW

        # Both implements count toward the limit (D030): forgetting resets no guard.
        capsys.readouterr()
        assert dispatch_in_tick(conn, *LABEL, "--kind", "implement", runner=runner).code == 1
        assert "dispatch refused (attempt_limit)" in capsys.readouterr().err
        assert operator("forget", KEY) == 0
        assert "It has had 2 implement runs in repo, and its limit is 2" in capsys.readouterr().out
        assert dispatch_in_tick(conn, *LABEL, "--kind", "implement", "--slug", "third", runner=runner).code == 1
        assert "dispatch refused (attempt_limit)" in capsys.readouterr().err


def test_forgetting_a_private_ticket_leaves_its_old_question_waiting_on_nothing(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert operator("start", KEY) == 0
    with private_worker_does(*commit_and_push(OLD), result=blocked_result()):
        assert work(conn, "--kind", "implement", "--slug", "work", runner=InlineRunner())["status"] == "blocked"
        assert main(["reply", KEY, "Red, but not yet"]) == 0
        # A question, then an operator message the loop has not handled.
        assert conversation.latest_question(conn, KEY) is None
        question = db.insert_message(
            conn, "ticket", KEY, source="worker", kind="question", channel="run", body=QUESTION
        )
        assert conversation.latest_question(conn, KEY) is not None

        assert operator("forget", KEY) == 0
        assert conversation.latest_question(conn, KEY) is None
        assert conversation.awaiting(conn) == []
        ticket = db.get_ticket(conn, KEY)
        assert ticket is not None
        assert ticket.forgotten_message_id == question
        section = conversation.state_section(conn, ticket)
        assert section is not None
        assert (section["new_operator_messages"], section["awaiting_reply"]) == ([], None)
        assert conversation.prompt_conversation(conn, KEY) == "No messages yet."
        # The ticket stays started, and the conversation stays in the journal for `show`.
        record = conversation.start_of(conn, KEY)
        assert record is not None
        assert record["status"] == "started"
        # The report, the question, the reply, and the question after it.
        assert len(db.messages_of(conn, "ticket", KEY, 10)) == 4

        # A reply after forgetting answers nothing, and is what the next worker reads.
        assert main(["reply", KEY, "Start over: blue."]) == 0
        [reply] = db.messages_of(conn, "ticket", KEY, 10, after=question)
        assert reply["answers"] is None
        section = conversation.state_section(conn, ticket)
        assert section is not None
        new = section["new_operator_messages"]
        assert isinstance(new, list)
        assert [m["body"] for m in new] == ["Start over: blue."]
        assert "Start over: blue." in conversation.prompt_conversation(conn, KEY)
        assert QUESTION not in conversation.prompt_conversation(conn, KEY)


def test_forgetting_clears_the_attention_item_of_the_latest_run(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    failed = json.dumps({"status": "failed", "branch": OLD, "prs": {"repo": None}, "summary": "could not"})
    with worker_does(*commit_and_push(OLD), result=failed):
        assert work(conn, *LABEL, "--kind", "implement", "--slug", "work", runner=InlineRunner())
        assert [(i.ticket_key, i.reason) for i in attention.from_runs(conn)] == [(KEY, "worker_failed")]
        assert operator("forget", KEY) == 0
        assert attention.from_runs(conn) == []
        assert [i for i in attention.listed(context(canopy_env)) if i.reason == "worker_failed"] == []


def test_forget_refuses_an_unknown_ticket_a_running_run_a_split_parent_and_other_kinds(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert operator("forget", KEY) == 1
    assert f"forget refused (unknown): canopy has no record of {KEY}" in capsys.readouterr().err

    db.touch_ticket(conn, KEY, str(canopy_env.root))
    tick_id = db.start_tick(conn, dry_run=False)
    run_id = db.insert_run(
        conn, tick_id=tick_id, key=KEY, kind="implement", branch=OLD, slots=[], runs_dir=canopy_env.state_dir
    )
    assert operator("forget", KEY) == 1
    assert f"forget refused (running): run {run_id} (implement) is working {KEY}" in capsys.readouterr().err

    db.finish_ticket_run(conn, run_id, RunStatus.DONE, None, messages=[], event=None)
    db.record_split_children(conn, KEY, run_id, {"PROJ-2": "repo"})
    assert operator("forget", KEY) == 1
    assert "forget refused (split): a split made PROJ-2 from PROJ-1" in capsys.readouterr().err
    ticket = db.get_ticket(conn, KEY)
    assert ticket is not None
    assert (ticket.branch, ticket.forgotten_at) == (OLD, None)

    for ref in ("run:1", "chore:build-health", "api#4"):
        assert operator("forget", ref) == 1
        assert "forget refused (unsupported)" in capsys.readouterr().err
