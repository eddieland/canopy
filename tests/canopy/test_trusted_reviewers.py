"""Trusted and untrusted reviewers (DESIGN §7, D089): the trusted list reaches the overseer and resume workers, and the
operator's reply on a public ticket is its go-ahead, carried in the state block and every public worker's prompt
(D093)."""

import json
import os
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db
from canopy.core.vocab import TickStatus
from canopy.loop.state import OverseerState, TicketState
from tests.canopy.helpers import InlineRunner, commit_and_push, in_tick, worker_does
from tests.conftest import CanopyEnv, GitPool

KEY = "PROJ-1"
GO_AHEAD = "Use your best judgement on codebot's review: take the null check, skip the renames."


def trust(canopy_env: CanopyEnv, *reviewers: str) -> None:
    listed = ", ".join(json.dumps(r) for r in reviewers)
    canopy_env.write_user(canopy_env.user_file.read_text() + f"\n[trust]\ntrusted_reviewers = [{listed}]\n")


def reply(conn: sqlite3.Connection, text: str) -> int:
    """Reply from the operator's shell, outside any tick, and return the message's id."""
    with mock.patch.dict(os.environ):
        os.environ.pop("CANOPY_TICK_ID", None)
        assert main(["reply", KEY, text]) == 0
        return db.latest_message_id(conn)


def overseer_state(agent_log: Path) -> OverseerState:
    overseer = json.loads(agent_log.read_text().splitlines()[-1])
    state: OverseerState = json.loads(overseer["argv"][-1].split("```json\n", 1)[1].split("\n```", 1)[0])
    return state


def tickets_of(state: OverseerState) -> dict[str, TicketState]:
    return {t["key"]: t for t in state["tickets"]}


def run_once(conn: sqlite3.Connection, *args: str) -> sqlite3.Row:
    runner = InlineRunner()
    with in_tick(conn) as tick_id:
        assert main(["dispatch", KEY, "--repo", "repo", "--label", "agent-ready-tester", *args], runner=runner) == 0
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
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
) -> None:
    trust(canopy_env, "octocat", "canopy:review")
    db.touch_ticket(conn, KEY, str(canopy_env.root))
    db.touch_ticket(conn, "PROJ-2", str(canopy_env.root))
    message = reply(conn, GO_AHEAD)

    waits = [["canopy", "decide", key, "wait", "--rationale", "next tick"] for key in (KEY, "PROJ-2")]
    with mock.patch.dict(
        os.environ, {"FAKE_OVERSEER_COMMANDS": json.dumps(waits), "FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}
    ):
        assert main(["tick", "--dry-run"]) == 0
        state = overseer_state(agent_log)
        assert state["trust"]["trusted_reviewers"] == ["octocat", "canopy:review"]
        tickets = tickets_of(state)
        # A public ticket: no `private` key, and its operator messages under `operator`.
        assert "private" not in tickets[KEY]
        operator = tickets[KEY]["operator"]
        assert operator["message_cursor"] is None
        assert [(m["id"], m["body"]) for m in operator["new_operator_messages"]] == [(message, GO_AHEAD)]
        assert "operator" not in tickets["PROJ-2"]

        # Handled, the message moves the cursor past it, and the ticket has nothing new from the operator.
        assert main(["ticket", "set", KEY, "--repo", "repo", "--cursor", f"message={message}"]) == 0
        ticket = db.get_ticket(conn, KEY)
        assert ticket is not None
        assert conversation.operator_section(conn, ticket) is None


def test_a_started_tickets_messages_stay_in_its_private_section(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    assert main(["start", KEY]) == 0
    reply(conn, GO_AHEAD)
    ticket = db.get_ticket(conn, KEY)
    assert ticket is not None
    assert conversation.operator_section(conn, ticket) is None
    private = conversation.state_section(conn, ticket)
    assert private is not None
    assert [m["body"] for m in private["new_operator_messages"]] == [GO_AHEAD]


def test_a_public_resume_hears_the_operator_and_knows_whom_to_trust(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    trust(canopy_env, "octocat", "canopy:review")
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        implement = run_once(conn, "--kind", "implement")
        assert implement["status"] == "done"
        implement_prompt = (canopy_env.state_dir / "runs" / f"{implement['id']}.prompt").read_text()
        assert GO_AHEAD not in implement_prompt

        message = reply(conn, GO_AHEAD)
        context = f"Operator message {message} on review comments 1501 and 1502 by codebot[bot] on PR 1"
        resumed = run_once(conn, "--kind", "resume", "--context", context, "--cursor", f"message={message}")
        assert (resumed["kind"], resumed["status"]) == ("resume", "done")
        prompt = (canopy_env.state_dir / "runs" / f"{resumed['id']}.prompt").read_text()
        assert f"Message {message}, the operator's reply, at " in prompt
        assert f"> {GO_AHEAD}" in prompt
        assert context in prompt
        assert (
            "Trusted reviewers: `octocat`, canopy's own reviewer (its findings come in this prompt, never on the PR)."
            in prompt
        )
        # The dispatch carried the message cursor, so the next tick does not read the go-ahead again.
        ticket = db.get_ticket(conn, KEY)
        assert ticket is not None
        assert int(ticket["last_message_id"]) == message
        assert conversation.operator_section(conn, ticket) is None


def test_with_nobody_trusted_the_resume_worker_is_told_so(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        run_once(conn, "--kind", "implement")
        resumed = run_once(conn, "--kind", "resume", "--context", "Address review comment 1501 by alice")
        prompt = (canopy_env.state_dir / "runs" / f"{resumed['id']}.prompt").read_text()
        assert "Trusted reviewers: none (every reviewer's feedback needs the operator's go-ahead)." in prompt
        assert "## Messages from the operator\n\nNo messages from the operator.\n" in prompt


def test_a_reply_on_a_public_ticket_needs_a_ticket_canopy_knows(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["reply", KEY, GO_AHEAD]) == 1
    assert "reply refused (unknown)" in capsys.readouterr().err
    db.touch_ticket(conn, KEY, str(canopy_env.root))
    assert main(["reply", KEY, GO_AHEAD]) == 0
    assert f"Recorded message 1 on {KEY}." in capsys.readouterr().out
    # The same reply again is the same submission.
    assert main(["reply", KEY, GO_AHEAD]) == 0
    assert "already says this" in capsys.readouterr().out


@pytest.mark.parametrize(("kind", "heading"), [("implement", "implement"), ("fix-ci", "fix CI")])
def test_every_public_worker_hears_the_operator_with_the_question_a_reply_answers(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    conn: sqlite3.Connection,
    kind: str,
    heading: str,
) -> None:
    # Not only `resume`: a reply before the branch exists rides the next `implement`, and a `fix-ci` hears it too
    # (D093). The question it answers comes with it, labeled as the earlier worker's.
    question = "Keep the v1 endpoint, or drop it?"
    with worker_does(result=json.dumps({"status": "blocked", "summary": "unclear", "question": question})):
        blocked = run_once(conn, "--kind", "implement")
        asked = db.latest_message_id(conn)
        message = reply(conn, "Keep it until the client migrates.")
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        run = run_once(conn, "--kind", kind, "--context", f"Operator message {message}")
        prompt = (canopy_env.state_dir / "runs" / f"{run['id']}.prompt").read_text()
        assert prompt.startswith(f"# canopy worker: {heading}")
        section = prompt.split("## Messages from the operator\n\n", 1)[1].split("\n\nThe operator wrote these", 1)[0]
        assert f"Message {asked}, an earlier worker's question, run {blocked['id']}" in section
        assert f"> {question}" in section
        assert f"Message {message}, the operator's reply to message {asked}" in section
        # The worker's report is on the tracker, where it reads it; only questions and the operator's messages are
        # here.
        assert "> unclear" not in section


@pytest.mark.parametrize("replied", [False, True])
def test_an_override_without_the_operator_messages_fails_closed_once_there_are_some(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    conn: sqlite3.Connection,
    replied: bool,  # noqa: FBT001  (a parametrized fixture)
) -> None:
    # An override written before D093 keeps serving tickets the operator never wrote to; from the first message on it
    # would drop what the operator said, so the dispatch is refused instead (D093).
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Implement {{KEY}} if it carries {{LABELS}}.\n")
    if replied:
        db.touch_ticket(conn, KEY, str(canopy_env.root))
        reply(conn, GO_AHEAD)
    with in_tick(conn) as tick_id:
        code = main(
            ["dispatch", KEY, "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
            runner=InlineRunner(),
        )
        decisions = [(d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]
        if not replied:
            assert code == 0, decisions
            return
        assert code == 1
        [(action, rationale)] = decisions
        assert action == "refused:bad_prompt"
        assert "missing required placeholder {{OPERATOR_MESSAGES}}" in rationale


def test_forgetting_a_ticket_leaves_its_operator_messages_behind(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    db.touch_ticket(conn, KEY, str(canopy_env.root))
    reply(conn, GO_AHEAD)
    assert conversation.has_operator_messages(conn, KEY)
    assert main(["forget", KEY]) == 0
    assert not conversation.has_operator_messages(conn, KEY)
    assert conversation.prompt_operator_messages(conn, KEY) == "No messages from the operator."
