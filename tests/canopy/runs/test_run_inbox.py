"""The operator's message to a running worker or planner: told by canopy's line, read through its tool (DESIGN §44)."""

import json

import pytest

from canopy.core import cards, conversation, run_inbox
from canopy.core.vocab import ResumeReason, RunKind, RunStatus
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
    # A lone letter still answers a question, and the run asks none.
    assert "(no_question)" in scenario.operator("reply", ref, "A", code=1).err
    working.finishes()
    assert len(run_inbox.sent_to(scenario.conn, "runs", working.id)) == run_inbox.MAX_MESSAGES
