"""The operator's message to a running worker or planner: told by canopy's line, read through its tool (DESIGN §44)."""

import json
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import cards, conversation, db, run_inbox
from canopy.core.vocab import ResumeReason, RunKind, RunStatus
from canopy.runtime.report import Called
from tests.canopy.helpers import KEY, Script, agent_runs, calls, context, planner_does, with_events
from tests.canopy.scenario_helpers import Scenario, dispatches, fails, pushes, reads_messages
from tests.conftest import GitPool

MESSAGES = run_inbox.tool_name()
NARROWER = "Drop the web half of the ticket: only the parser, in this PR."


def test_a_running_worker_fetches_the_message_and_its_report_answers_it(scenario: Scenario, git_pool: GitPool) -> None:
    with_events(scenario.env, "canopy-worker")
    working = scenario.starts(worker=reads_messages(pushes()))
    ref = f"run:{working.id}"

    sent = scenario.operator("reply", ref, NARROWER).out
    [message] = run_inbox.sent_to(scenario.conn, "runs", working.id)
    assert sent == (
        f"Recorded message {message.id} to {ref}.\n"
        "Its agent hears that it waits on its next tool call, and reads it through canopy's tool.\n"
    )
    # It is the operator's on the run's ticket, answering nothing, and written where the run reads it.
    assert (message.subject_kind, message.subject_id, message.source) == ("ticket", KEY, "operator")
    assert (message.answers, message.delivered_at is not None, message.fetched_at) == (None, True, None)
    answers = cards.answers_dir(context(scenario.env).state_dir, str(working.id))
    # The mark the plugin reads names the newest message alone, never its words.
    assert json.loads((answers / run_inbox.MARK_FILE).read_text()) == {"newest": message.id}
    assert "parser" not in (answers / run_inbox.MARK_FILE).read_text()
    assert "nothing new recorded" in scenario.operator("reply", ref, NARROWER).out
    assert f"  #{message.id}  sent {message.at}, not fetched yet\n" in scenario.operator("show", ref).out

    ran = working.finishes()
    assert ran.status is RunStatus.DONE
    [run] = agent_runs(scenario.agent_log)
    [fetched] = [t for t in run["tools"] if t["name"] == MESSAGES]
    assert fetched["error"] is False
    assert fetched["text"].startswith("1 message from the operator to this run, oldest first.")
    assert f"Message {message.id}, from the operator, at {message.at}:\n> {NARROWER}" in fetched["text"]
    [message] = run_inbox.sent_to(scenario.conn, "runs", ran.id)
    assert message.fetched_at is not None
    assert f"  #{message.id}  sent {message.at}, fetched {message.fetched_at}\n    {NARROWER}\n" in (
        scenario.operator("show", ref).out
    )
    # Answered: the loop reads past it, and no resume is owed for it, though the next run's prompt still carries it.
    assert conversation.operator_messages_after(scenario.conn, KEY, 0) == []
    reply = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REPLY], cursors={"message": str(message.id)})
    [(action, _), *_] = scenario.refuses(reply)
    assert action == "refused:unauthorized"
    # The same words again, as a retry whose answer was lost, are the message recorded then, though the run has ended.
    again = scenario.operator("reply", ref, NARROWER).out
    assert again == f"Message {message.id} to {ref} already says this; nothing new recorded.\n"


@pytest.mark.parametrize(
    ("worker", "fetched"),
    [(pushes(), False), (reads_messages(fails()), True)],
    ids=["never-fetched", "fetched-then-failed"],
)
def test_a_message_its_run_did_not_answer_reaches_the_next_runs_prompt(
    scenario: Scenario,
    git_pool: GitPool,
    worker: Script,
    fetched: bool,  # noqa: FBT001  (a parameter)
) -> None:
    with_events(scenario.env, "canopy-worker")
    scenario.run(worker=pushes())
    working = scenario.starts(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW]), worker=worker)
    scenario.operator("reply", f"run:{working.id}", NARROWER)
    working.finishes()

    # A fetch alone answers nothing: it stays the operator's word to the ticket, and authorizes a resume for it.
    [message] = conversation.operator_messages_after(scenario.conn, KEY, 0)
    assert (message.fetched_at is not None) is fetched
    shown = scenario.operator("show", f"run:{working.id}").out
    assert f"  #{message.id}  sent {message.at}, {'fetched' if fetched else 'never fetched'}" in shown
    cursor = {"message": str(message.id)}
    resume = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REPLY], cursors=cursor))
    assert NARROWER in resume.prompt


def test_a_planner_takes_a_message_as_a_worker_does(scenario: Scenario, git_pool: GitPool) -> None:
    with_events(scenario.env, "canopy-planner")
    planner = planner_does(plan="# Plan\n\nDo it.\n", then_tools=[calls(MESSAGES)])
    working = scenario.starts(dispatches(kind=RunKind.PLAN), worker=planner)
    scenario.operator("reply", f"run:{working.id}", NARROWER)
    working.finishes()
    [message] = run_inbox.sent_to(scenario.conn, "runs", working.id)
    assert message.fetched_at is not None


def test_a_message_to_a_run_that_ended_is_refused_naming_its_tickets_reply(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    ran = scenario.run(worker=pushes())
    err = scenario.operator("reply", f"run:{ran.id}", NARROWER, code=1).err
    assert f"reply refused (ended): run:{ran.id} has ended (done)" in err
    assert f"reply to its ticket instead, `canopy reply {KEY}`" in err
    assert "(unknown)" in scenario.operator("reply", "run:99", NARROWER, code=1).err
    assert run_inbox.sent_to(scenario.conn, "runs", ran.id) == []


def test_an_empty_or_overlong_message_is_refused_and_a_run_takes_so_many(scenario: Scenario, git_pool: GitPool) -> None:
    working = scenario.starts()
    ref = f"run:{working.id}"
    assert "(bad_body)" in scenario.operator("reply", ref, "   \n", code=1).err
    overlong = "x" * (conversation.MAX_OPERATOR + 1)
    assert "(bad_body)" in scenario.operator("reply", ref, overlong, code=1).err
    for n in range(run_inbox.MAX_MESSAGES):
        scenario.operator("reply", ref, f"message {n}")
    assert "(too_many)" in scenario.operator("reply", ref, "one more", code=1).err
    assert "nothing new recorded" in scenario.operator("reply", ref, "message 0").out
    # A lone letter still answers a question, and the run asks none.
    assert "(no_question)" in scenario.operator("reply", ref, "A", code=1).err
    working.finishes()
    assert len(run_inbox.sent_to(scenario.conn, "runs", working.id)) == run_inbox.MAX_MESSAGES


def test_a_message_is_written_where_its_agent_reads_it_only_once_the_journal_holds_it(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """So no rollback, and no canopy that dies as it records one, leaves its agent a message the journal lacks."""
    working = scenario.starts()
    other = scenario.env.journal()
    seen: list[list[int]] = []
    write = cards.replace_file

    def committed(path: Path, name: str, data: Mapping[str, object]) -> bool:
        # Another connection sees only what is committed.
        seen.append([m.id for m in run_inbox.sent_to(other, "runs", working.id)])
        return write(path, name, data)

    with mock.patch.object(cards, "replace_file", autospec=True, side_effect=committed):
        scenario.operator("reply", f"run:{working.id}", NARROWER)
    [message] = run_inbox.sent_to(scenario.conn, "runs", working.id)
    assert seen == [[message.id], [message.id]]
    working.finishes()


def test_a_message_its_runs_directory_cannot_take_is_recorded_and_reaches_the_next_runs_prompt(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    with_events(scenario.env, "canopy-worker")
    scenario.run(worker=pushes())
    held = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW])
    working = scenario.starts(held, worker=reads_messages(pushes()))
    ref = f"run:{working.id}"
    full = OSError(28, "No space left on device")
    with mock.patch.object(cards, "replace_file", autospec=True, side_effect=full):
        sent = scenario.operator("reply", ref, NARROWER).out
    [message] = run_inbox.sent_to(scenario.conn, "runs", working.id)
    assert sent == (
        f"Recorded message {message.id} to {ref}.\n"
        "Its agent was not told of it, its run ending or its answers directory not written (the log says which): the "
        "ticket's next run reads it.\n"
    )
    assert message.delivered_at is None
    answers = cards.answers_dir(context(scenario.env).state_dir, str(working.id))
    assert not (answers / run_inbox.TEXTS_FILE).exists()

    working.finishes()
    # Its agent found none, so fetched none: the operator's word to the ticket, for the next run.
    [message] = conversation.operator_messages_after(scenario.conn, KEY, 0)
    assert message.fetched_at is None
    cursor = {"message": str(message.id)}
    resume = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REPLY], cursors=cursor))
    assert NARROWER in resume.prompt


def test_a_read_of_the_messages_that_fails_fetches_nothing(scenario: Scenario, git_pool: GitPool) -> None:
    with_events(scenario.env, "canopy-worker")
    working = scenario.starts(worker=reads_messages(pushes()))
    scenario.operator("reply", f"run:{working.id}", NARROWER)
    # What an unsandboxed agent could write there: the tool cannot read it, which is an error, not "no message".
    answers = cards.answers_dir(context(scenario.env).state_dir, str(working.id))
    (answers / run_inbox.TEXTS_FILE).write_text('{"messages": "mine"}')

    ran = working.finishes()
    [run] = agent_runs(scenario.agent_log)
    [called] = [t for t in run["tools"] if t["name"] == MESSAGES]
    assert called["error"] is True
    assert called["text"].startswith("messages refused: the operator's messages to this run cannot be read")
    [message] = run_inbox.sent_to(scenario.conn, "runs", ran.id)
    assert message.fetched_at is None
    assert [m.id for m in conversation.operator_messages_after(scenario.conn, KEY, 0)] == [message.id]


def test_a_fetch_is_a_completed_call_with_the_tools_input_started_after_the_message_was_written(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """One started in the very millisecond it was marked written may not have read it: left unfetched, the safe side."""
    working = scenario.starts()
    scenario.operator("reply", f"run:{working.id}", NARROWER)
    [message] = run_inbox.sent_to(scenario.conn, "runs", working.id)
    assert message.delivered_at is not None
    written = db.parse_time(message.delivered_at)
    later = written + timedelta(milliseconds=1)
    for call in (
        Called(MESSAGES, completed=True, input={}, started_at=written),
        Called(MESSAGES, completed=True, input={}, started_at=None),
        Called(MESSAGES, completed=False, input={}, started_at=later),
        Called(MESSAGES, completed=True, input={"since": 3}, started_at=later),
        Called(cards.tool_name(), completed=True, input={}, started_at=later),
    ):
        run_inbox.record_fetch(scenario.conn, "runs", working.id, call)
    [message] = run_inbox.sent_to(scenario.conn, "runs", working.id)
    assert message.fetched_at is None
    fetches = Called(MESSAGES, completed=True, input={}, started_at=later)
    run_inbox.record_fetch(scenario.conn, "runs", working.id, fetches)
    [message] = run_inbox.sent_to(scenario.conn, "runs", working.id)
    assert message.fetched_at == db.format_time(later)
    working.finishes()
