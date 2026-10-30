"""Trusted and untrusted reviewers (DESIGN §7, D089).

The trusted list reaches the overseer and resume workers, and the operator's reply on a public ticket is its go-ahead,
carried in the state block and every public worker's prompt (D093).
"""

import json
from typing import cast

import pytest

from canopy.core import conversation, db
from canopy.core.vocab import ResumeReason, RunKind
from canopy.loop.state import OverseerState, TicketState
from tests.canopy.helpers import KEY, present, ticket_sets, waits, worker_does
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.conftest import GitPool

GO_AHEAD = "Use your best judgement on codebot's review: take the null check, skip the renames."


def trust(scenario: Scenario, *reviewers: str) -> None:
    scenario.configures(trust={"trusted_reviewers": list(reviewers)})


def reply(scenario: Scenario, text: str) -> int:
    """Reply from the operator's shell, outside any tick, and return the message's id."""
    scenario.operator("reply", KEY, text)
    return db.latest_message_id(scenario.conn)


def overseer_state(scenario: Scenario) -> OverseerState:
    return cast("OverseerState", scenario.state())


def tickets_of(state: OverseerState) -> dict[str, TicketState]:
    return {t["key"]: t for t in state["tickets"]}


def test_the_overseer_reads_the_trusted_list_and_a_public_tickets_operator_messages(scenario: Scenario) -> None:
    conn = scenario.conn
    trust(scenario, "octocat", "canopy:review")
    db.touch_ticket(conn, KEY, str(scenario.env.root))
    db.touch_ticket(conn, "PROJ-2", str(scenario.env.root))
    message = reply(scenario, GO_AHEAD)

    scenario.tick(*waits(KEY, "PROJ-2", rationale="next tick"), dry_run=True)
    state = overseer_state(scenario)
    assert state["trust"]["trusted_reviewers"] == ["octocat", "canopy:review"]
    tickets = tickets_of(state)
    # A public ticket: no `private` key, and its operator messages under `operator`.
    assert "private" not in tickets[KEY]
    operator = tickets[KEY]["operator"]
    assert "message_cursor" not in operator  # null, so the block leaves it out
    assert [(m["id"], m["body"]) for m in operator["new_operator_messages"]] == [(message, GO_AHEAD)]
    assert "operator" not in tickets["PROJ-2"]

    # Handled, the message moves the cursor past it, and the ticket has nothing new from the operator.
    scenario.overseer(ticket_sets(KEY, repo="repo", cursors={"message": str(message)}))
    ticket = present(db.get_ticket(conn, KEY))
    assert conversation.operator_section(conn, ticket, authorized=()) is None


def test_a_started_tickets_messages_stay_in_its_private_section(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.operator("start", KEY)
    reply(scenario, GO_AHEAD)
    ticket = present(db.get_ticket(conn, KEY))
    assert conversation.operator_section(conn, ticket, authorized=()) is None
    private = present(conversation.state_section(conn, ticket))
    assert [m["body"] for m in private["new_operator_messages"]] == [GO_AHEAD]


def test_a_public_resume_hears_the_operator_and_knows_whom_to_trust(scenario: Scenario, git_pool: GitPool) -> None:
    trust(scenario, "octocat", "canopy:review")
    implement = scenario.run(worker=pushes())
    assert implement.status == "done"
    assert GO_AHEAD not in implement.prompt

    message = reply(scenario, GO_AHEAD)
    context = f"Operator message {message} on review comments 1501 and 1502 by codebot[bot] on PR 1"
    resume = dispatches(
        kind=RunKind.RESUME,
        reasons=[ResumeReason.REPLY, ResumeReason.REVIEW],
        context=context,
        cursors={"message": str(message)},
    )
    resumed = scenario.run(resume, worker=pushes())
    assert (resumed.kind, resumed.status) == ("resume", "done")
    prompt = resumed.prompt
    assert f"Message {message}, the operator's reply, at " in prompt
    assert f"> {GO_AHEAD}" in prompt
    assert context in prompt
    assert (
        "Trusted reviewers: `octocat`, canopy's own reviewer (its findings come in this prompt, never on the PR)."
        in prompt
    )
    # The dispatch carried the message cursor, so the next tick does not read the go-ahead again.
    ticket = present(db.get_ticket(scenario.conn, KEY))
    assert ticket.last_message_id == message
    assert conversation.operator_section(scenario.conn, ticket, authorized=()) is None


def test_with_nobody_trusted_the_resume_worker_is_told_so(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.run(worker=pushes())
    resume = dispatches(
        kind=RunKind.RESUME,
        reasons=[ResumeReason.REVIEW],
        context="Address review comment 1501 by alice",
    )
    prompt = scenario.run(resume, worker=pushes()).prompt
    assert "Trusted reviewers: none (every reviewer's feedback needs the operator's go-ahead)." in prompt
    assert "## Messages from the operator" not in prompt


def test_a_reply_on_a_public_ticket_needs_a_ticket_canopy_knows(scenario: Scenario) -> None:
    assert "reply refused (unknown)" in scenario.operator("reply", KEY, GO_AHEAD, code=1).err
    db.touch_ticket(scenario.conn, KEY, str(scenario.env.root))
    assert f"Recorded message 1 on {KEY}." in scenario.operator("reply", KEY, GO_AHEAD).out
    # The same reply again is the same submission.
    assert "already says this" in scenario.operator("reply", KEY, GO_AHEAD).out


@pytest.mark.parametrize("kind", [RunKind.IMPLEMENT, RunKind.RESUME])
def test_every_public_worker_hears_the_operator_with_the_question_a_reply_answers(
    scenario: Scenario,
    git_pool: GitPool,
    kind: RunKind,
) -> None:
    # Not only a `resume` for the reply: a reply before the branch exists rides the next `implement` too (D093). The
    # question it answers comes with it, labeled as the earlier worker's.
    question = "Keep the v1 endpoint, or drop it?"
    blocked = scenario.run(
        worker=worker_does(result=json.dumps({"status": "blocked", "summary": "unclear", "question": question})),
    )
    asked = db.latest_message_id(scenario.conn)
    message = reply(scenario, "Keep it until the client migrates.")
    reasons = [ResumeReason.REPLY] if kind == RunKind.RESUME else []
    # A resume for the reply names it as what authorizes it (DESIGN §35).
    cursors = {"message": str(message)} if kind == RunKind.RESUME else None
    command = dispatches(kind=kind, reasons=reasons, context=f"Operator message {message}", cursors=cursors)
    run = scenario.run(command, worker=pushes())
    prompt = run.prompt
    assert prompt.startswith(f"# canopy worker: {kind}")
    section = prompt.split("## Messages from the operator\n\n", 1)[1].split("\n\nThe operator wrote these", 1)[0]
    assert f"Message {asked}, an earlier worker's question, run {blocked.id}" in section
    assert f"> {question}" in section
    assert f"Message {message}, the operator's reply to message {asked}" in section
    # The worker's report is on the tracker, where it reads it; only questions and the operator's messages are
    # here.
    assert "> unclear" not in section


@pytest.mark.parametrize("replied", [False, True])
def test_an_override_without_the_operator_messages_fails_closed_once_there_are_some(
    scenario: Scenario,
    git_pool: GitPool,
    replied: bool,  # noqa: FBT001  (a parametrized fixture)
) -> None:
    # An override written before D093 keeps serving tickets the operator never wrote to; from the first message on it
    # would drop what the operator said, so the dispatch is refused instead (D093).
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Implement {{KEY}} if it carries {{LABELS}}.\n{{DRAFTS}}\n")
    if not replied:
        assert scenario.run().prompt.startswith(f"Implement {KEY} if it carries ")
        return
    db.touch_ticket(scenario.conn, KEY, str(scenario.env.root))
    reply(scenario, GO_AHEAD)
    [(action, rationale)] = scenario.refuses(dispatches())
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{OPERATOR_MESSAGES}}" in rationale


def test_forgetting_a_ticket_leaves_its_operator_messages_behind(scenario: Scenario) -> None:
    db.touch_ticket(scenario.conn, KEY, str(scenario.env.root))
    reply(scenario, GO_AHEAD)
    assert conversation.has_operator_messages(scenario.conn, KEY)
    scenario.operator("forget", KEY)
    assert not conversation.has_operator_messages(scenario.conn, KEY)
    assert conversation.prompt_operator_messages(scenario.conn, KEY, authorized=()) is None
