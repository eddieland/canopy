"""Trusted and untrusted reviewers (DESIGN §7, D089): the trusted list reaches the overseer and resume workers, and the
operator's reply on a public ticket is its go-ahead, carried in the state block and the resume worker's prompt."""

import json
import sqlite3
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db
from tests.canopy.helpers import InlineRunner, commit_and_push, in_tick, journal, worker_does
from tests.conftest import CanopyEnv, GitPool

KEY = "PROJ-1"
GO_AHEAD = "Use your best judgement on codebot's review: take the null check, skip the renames."


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


def trust(canopy_env: CanopyEnv, *reviewers: str) -> None:
    listed = ", ".join(json.dumps(r) for r in reviewers)
    canopy_env.write_user(canopy_env.user_file.read_text() + f"\n[trust]\ntrusted_reviewers = [{listed}]\n")


def reply(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, text: str) -> int:
    """Reply from the operator's shell, outside any tick, and return the message's id."""
    monkeypatch.delenv("CANOPY_TICK_ID", raising=False)
    assert main(["reply", KEY, text]) == 0
    return db.latest_message_id(conn)


def overseer_state(agent_log: Path) -> dict[str, object]:
    overseer = json.loads(agent_log.read_text().splitlines()[-1])
    state: dict[str, object] = json.loads(overseer["argv"][-1].split("```json\n", 1)[1].split("\n```", 1)[0])
    return state


def tickets_of(state: dict[str, object]) -> dict[str, dict[str, object]]:
    tickets = state["tickets"]
    assert isinstance(tickets, list)
    return {str(t["key"]): t for t in tickets}


def run_once(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, *args: str) -> sqlite3.Row:
    runner = InlineRunner()
    tick_id = in_tick(conn, monkeypatch)
    assert main(["dispatch", KEY, "--label", "agent-ready-tester", *args], runner=runner) == 0
    db.finish_tick(conn, tick_id, "ok", "test")
    monkeypatch.delenv("CANOPY_TICK_ID")
    run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
    assert main(["_run", str(run_id)], runner=runner) == 0
    run = db.get_run(conn, run_id)
    assert run is not None
    return run


def test_the_overseer_reads_the_trusted_list_and_a_public_tickets_operator_messages(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    agent_log: Path,
    treehouse_state: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust(canopy_env, "octocat", "canopy:review")
    db.touch_ticket(conn, KEY, str(canopy_env.repo))
    db.touch_ticket(conn, "PROJ-2", str(canopy_env.repo))
    message = reply(conn, monkeypatch, GO_AHEAD)

    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    assert main(["tick", "--dry-run"]) == 0
    state = overseer_state(agent_log)
    trusted = state["trust"]
    assert isinstance(trusted, dict)
    assert trusted["trusted_reviewers"] == ["octocat", "canopy:review"]
    tickets = tickets_of(state)
    # A public ticket: no `private` key, and its operator messages under `operator`.
    assert "private" not in tickets[KEY]
    operator = tickets[KEY]["operator"]
    assert isinstance(operator, dict)
    assert operator["message_cursor"] is None
    assert [(m["id"], m["body"]) for m in operator["new_operator_messages"]] == [(message, GO_AHEAD)]
    assert "operator" not in tickets["PROJ-2"]

    # Handled, the message moves the cursor past it, and the ticket has nothing new from the operator.
    assert main(["ticket", "set", KEY, "--cursor", f"message={message}"]) == 0
    ticket = db.get_ticket(conn, KEY)
    assert ticket is not None
    assert conversation.operator_section(conn, ticket) is None


def test_a_started_tickets_messages_stay_in_its_private_section(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["start", KEY]) == 0
    reply(conn, monkeypatch, GO_AHEAD)
    ticket = db.get_ticket(conn, KEY)
    assert ticket is not None
    assert conversation.operator_section(conn, ticket) is None
    private = conversation.state_section(conn, ticket)
    assert private is not None
    messages = private["new_operator_messages"]
    assert isinstance(messages, list)
    assert [m["body"] for m in messages] == [GO_AHEAD]


def test_a_public_resume_hears_the_operator_and_knows_whom_to_trust(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust(canopy_env, "octocat", "canopy:review")
    worker_does(monkeypatch, *commit_and_push("agent/PROJ-1-work"))
    implement = run_once(conn, monkeypatch, "--kind", "implement")
    assert implement["status"] == "done"
    implement_prompt = (canopy_env.state_dir / "runs" / f"{implement['id']}.prompt").read_text()
    assert GO_AHEAD not in implement_prompt

    message = reply(conn, monkeypatch, GO_AHEAD)
    context = f"Operator message {message} on review comments 1501 and 1502 by codebot[bot] on PR 1"
    resumed = run_once(conn, monkeypatch, "--kind", "resume", "--context", context, "--cursor", f"message={message}")
    assert (resumed["kind"], resumed["status"]) == ("resume", "done")
    prompt = (canopy_env.state_dir / "runs" / f"{resumed['id']}.prompt").read_text()
    assert f"Message {message}, the operator's reply, at " in prompt
    assert f"> {GO_AHEAD}" in prompt
    assert context in prompt
    assert "Trusted reviewers: `octocat`, canopy's own reviewer (a comment canopy's review run posted)." in prompt
    # The dispatch carried the message cursor, so the next tick does not read the go-ahead again.
    ticket = db.get_ticket(conn, KEY)
    assert ticket is not None
    assert int(ticket["last_message_id"]) == message
    assert conversation.operator_section(conn, ticket) is None


def test_with_nobody_trusted_the_resume_worker_is_told_so(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_does(monkeypatch, *commit_and_push("agent/PROJ-1-work"))
    run_once(conn, monkeypatch, "--kind", "implement")
    resumed = run_once(conn, monkeypatch, "--kind", "resume", "--context", "Address review comment 1501 by alice")
    prompt = (canopy_env.state_dir / "runs" / f"{resumed['id']}.prompt").read_text()
    assert "Trusted reviewers: none (every reviewer's feedback needs the operator's go-ahead)." in prompt
    assert "## Messages from the operator\n\nNo messages from the operator.\n" in prompt


def test_a_reply_on_a_public_ticket_needs_a_ticket_canopy_knows(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["reply", KEY, GO_AHEAD]) == 1
    assert "reply refused (unknown)" in capsys.readouterr().err
    db.touch_ticket(conn, KEY, str(canopy_env.repo))
    assert main(["reply", KEY, GO_AHEAD]) == 0
    assert f"Recorded message 1 on {KEY}." in capsys.readouterr().out
    # The same reply again is the same submission.
    assert main(["reply", KEY, GO_AHEAD]) == 0
    assert "already says this" in capsys.readouterr().out
