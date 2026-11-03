"""`canopy forget` (DESIGN §22): a ticket's branch and PRs forgotten, so its next implement starts over."""

import json
from pathlib import Path
from typing import Any

from canopy.core import connector_runs, conversation, db
from canopy.core.vocab import Decider, StartStatus
from canopy.loop import attention
from tests.canopy.helpers import (
    KEY,
    QUESTION,
    blocked_result,
    commit_and_push,
    context,
    present,
    private_worker_does,
    tracker_holds,
    unit_of,
    worker_does,
)
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import GitPool

OLD = f"agent/{KEY}-work"
NEW = f"agent/{KEY}-again"
OLD_PR = "https://example.test/pr/1"
NEW_PR = "https://example.test/pr/2"
#: A key the overseer named before its tools refused one no source returned, which no tracker holds (#1965).
STRAY = "PROJ-100-placeholder"
#: A tracker and a `vcs` source the fake connector plays, each under its own name.
SOURCES = {
    "sources": {
        "jira": {"kind": "tracker", "cmd": "connector jira", "timeout_minutes": 1},
        "github": {"kind": "vcs", "cmd": "connector github", "timeout_minutes": 1},
    },
}


def done(branch: str, pr: str) -> str:
    return json.dumps({"status": "done", "branch": branch, "prs": {"repo": pr}, "summary": "did it"})


def test_a_forgotten_ticket_starts_over_on_a_new_branch_and_its_runs_still_count(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    conn = scenario.conn
    first_run = scenario.run(
        dispatches(slug="work"),
        worker=worker_does(*commit_and_push(OLD), result=done(OLD, OLD_PR)),
    )
    assert first_run.status == "done"
    assert unit_of(conn, KEY).pr_url == OLD_PR
    # Before forgetting, a later implement continues the ticket's branch and names no other.
    [(action, _)] = scenario.refuses(dispatches(slug="again"))
    assert action == "refused:bad_slug"

    out = scenario.operator("forget", KEY).out
    assert f"{KEY} is forgotten" in out
    assert f"canopy no longer tracks branch {OLD}, {OLD_PR}." in out
    assert "delete its branch on origin yourself" in out
    assert "its limit is" not in out  # one implement of two
    ticket = present(db.get_ticket(conn, KEY))
    assert (ticket.branch, ticket.phase, ticket.done) == (None, None, False)
    assert ticket.forgotten_run_id == first_run.id
    assert db.units(conn, KEY) == []
    # The overseer's state block and the attention list no longer see the run; `show` still does.
    assert KEY not in db.latest_runs(conn)
    shown = scenario.operator("show", KEY).out
    assert "branch none yet" in shown
    assert "forgotten " in shown
    assert f"run:{first_run.id}  implement  done" in shown

    # The next implement names a new branch.
    again = scenario.run(dispatches(slug="again"), worker=worker_does(*commit_and_push(NEW), result=done(NEW, NEW_PR)))
    assert again.branch == NEW
    ticket = present(db.get_ticket(conn, KEY))
    assert ticket.branch == NEW
    assert unit_of(conn, KEY).pr_url == NEW_PR
    assert db.latest_runs(conn)[KEY].branch == NEW

    # Both implements count toward the limit (D030): forgetting resets no guard.
    [(action, _), _] = scenario.refuses(dispatches())
    assert action == "refused:attempt_limit"
    assert "It has had 2 implement runs in repo, and its limit is 2" in scenario.operator("forget", KEY).out
    [(action, _), _] = scenario.refuses(dispatches(slug="third"))
    assert action == "refused:attempt_limit"

    # Each forget is kept, with what it dropped; the ticket's own row holds the latest.
    first, second = db.forgets_of(conn, KEY)
    assert [(f.channel, f.branch, json.loads(present(f.prs))) for f in (first, second)] == [
        ("cli", OLD, [OLD_PR]),
        ("cli", NEW, [NEW_PR]),
    ]
    assert first.run_id is not None
    assert second.run_id == present(db.get_ticket(conn, KEY)).forgotten_run_id
    shown = scenario.operator("show", KEY).out
    assert f"via cli, dropping branch {OLD}, {OLD_PR}" in shown
    assert f"via cli, dropping branch {NEW}, {NEW_PR}" in shown
    # A third forget with nothing new since the second would drop nothing, so it is refused and recorded nowhere.
    assert "forget refused (already_forgotten)" in scenario.operator("forget", KEY, code=1).err
    assert len(db.forgets_of(conn, KEY)) == 2


def test_forgetting_a_private_ticket_leaves_its_old_question_waiting_on_nothing(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    conn = scenario.conn
    scenario.operator("start", KEY)
    worker = private_worker_does(*commit_and_push(OLD), result=blocked_result())
    assert scenario.run(dispatches(label=None, slug="work"), worker=worker).status == "blocked"
    scenario.operator("reply", KEY, "Red, but not yet")
    # A question, then an operator message the loop has not handled.
    assert conversation.latest_question(conn, KEY) is None
    question = db.insert_message(conn, "ticket", KEY, source="worker", kind="question", channel="run", body=QUESTION)
    assert conversation.latest_question(conn, KEY) is not None

    scenario.operator("forget", KEY)
    assert conversation.latest_question(conn, KEY) is None
    assert conversation.awaiting(conn) == []
    ticket = present(db.get_ticket(conn, KEY))
    assert ticket.forgotten_message_id == question
    section = present(conversation.state_section(conn, ticket))
    assert (section["new_operator_messages"], section["awaiting_reply"]) == ([], None)
    assert conversation.prompt_conversation(conn, KEY) is None
    # The ticket stays started, and the conversation stays in the journal for `show`.
    record = present(conversation.start_of(conn, KEY))
    assert record.status == StartStatus.STARTED
    # The report, the question, the reply, and the question after it.
    assert len(db.messages_of(conn, "ticket", KEY, 10)) == 4

    # A reply after forgetting answers nothing, and is what the next worker reads.
    scenario.operator("reply", KEY, "Start over: blue.")
    [reply] = db.messages_of(conn, "ticket", KEY, 10, after=question)
    assert reply.answers is None
    section = present(conversation.state_section(conn, ticket))
    new = section["new_operator_messages"]
    assert isinstance(new, list)
    assert [m["body"] for m in new] == ["Start over: blue."]
    prompt = present(conversation.prompt_conversation(conn, KEY))
    assert "Start over: blue." in prompt
    assert QUESTION not in prompt


def test_forgetting_clears_the_attention_item_of_the_latest_run(scenario: Scenario, git_pool: GitPool) -> None:
    failed = json.dumps({"status": "failed", "branch": OLD, "prs": {"repo": None}, "summary": "could not"})
    scenario.run(dispatches(slug="work"), worker=worker_does(*commit_and_push(OLD), result=failed))
    assert [(i.ticket_key, i.reason) for i in attention.from_runs(scenario.conn)] == [(KEY, "worker_failed")]
    scenario.operator("forget", KEY)
    assert attention.from_runs(scenario.conn) == []
    assert [i for i in attention.listed(context(scenario.env)) if i.reason == "worker_failed"] == []


def test_forget_refuses_an_unknown_ticket_a_running_run_and_other_kinds(scenario: Scenario, git_pool: GitPool) -> None:
    conn = scenario.conn
    refused = scenario.operator("forget", KEY, code=1)
    assert f"forget refused (unknown): canopy has no record of {KEY}" in refused.err

    working = scenario.starts()
    refused = scenario.operator("forget", KEY, code=1)
    assert f"forget refused (running): run {working.id} (implement) is working {KEY}" in refused.err

    working.finishes()
    ticket = present(db.get_ticket(conn, KEY))
    assert (ticket.branch, ticket.forgotten_at) == (OLD, None)

    for ref in ("run:1", "chore:build-health", "api#4"):
        assert "forget refused (unsupported)" in scenario.operator("forget", ref, code=1).err


def asked_for(state: Path) -> list[list[str]]:
    """The tickets each run of the `jira` source was asked for, in order."""
    log = state.parent / "connector.jsonl"
    runs: list[dict[str, Any]] = [json.loads(line) for line in log.read_text().splitlines()]
    return [[t["key"] for t in r["request"].get("tickets", [])] for r in runs if r["name"] == "jira"]


def test_forgetting_a_ticket_no_source_ever_observed_removes_it_and_its_decisions_stay(
    scenario: Scenario,
    connector_state: Path,
) -> None:
    """A key the overseer named from nowhere stops being asked for, failing the tracker, and waiting (#1965)."""
    scenario.configures("private", connect=SOURCES)
    # The tracker holds no such ticket: it reads none of it, and its query returns nothing.
    connector_state.write_text(json.dumps({"jira": {"end": {"tickets": [], "query": []}}}))
    scenario.seen(STRAY)
    ticked = scenario.tick()
    assert asked_for(connector_state)[-1] == [STRAY]
    [failed] = connector_runs.failures(scenario.conn, ticked.tick.id)
    assert failed.detail == f"jira (tracker) partial: did not read 1 ticket ({STRAY}) whole"
    [wait] = [d for d in ticked.decisions if d.ticket_key == STRAY]
    assert (wait.action, wait.decider) == ("wait", Decider.HARNESS)
    assert wait.rationale.startswith(f"stale: {STRAY} never observed")
    assert scenario.attention() == [(None, connector_runs.FAILED_REASON)]

    out = scenario.operator("forget", STRAY).out
    assert f"{STRAY} is forgotten whole: no source ever observed it" in out
    assert db.get_ticket(scenario.conn, STRAY) is None
    assert db.forgets_of(scenario.conn, STRAY) == []

    ticked = scenario.tick()
    assert asked_for(connector_state)[-1] == []
    assert connector_runs.failures(scenario.conn, ticked.tick.id) == []
    assert [d for d in ticked.decisions if d.ticket_key == STRAY] == []
    assert scenario.attention() == []
    # Its decisions stay, the evaluation corpus (D036).
    actions = [r[0] for r in scenario.conn.execute("SELECT action FROM decisions WHERE ticket_key = ?", (STRAY,))]
    assert actions == ["wait"]
    assert "forget refused (unknown)" in scenario.operator("forget", STRAY, code=1).err


def test_a_ticket_forgotten_before_with_nothing_else_is_removed_too(scenario: Scenario) -> None:
    """The forget an operator tried before this one dropped nothing, so it goes with the ticket."""
    scenario.seen(STRAY)
    with db.transaction(scenario.conn):
        db.forget_ticket(scenario.conn, STRAY, channel="cli", branch=None, prs=[])
    assert "forgotten whole" in scenario.operator("forget", STRAY).out
    assert db.get_ticket(scenario.conn, STRAY) is None


def test_a_ticket_with_anything_of_its_own_is_forgotten_not_removed(scenario: Scenario) -> None:
    """Started by the operator, or observed by a source: its row stays, and its forget is recorded."""
    scenario.operator("start", STRAY)
    out = scenario.operator("forget", STRAY).out
    assert f"{STRAY} is forgotten: its next implement" in out
    assert present(db.get_ticket(scenario.conn, STRAY)).forgotten_at is not None
    assert len(db.forgets_of(scenario.conn, STRAY)) == 1

    tracker_holds(scenario.conn, KEY)
    assert f"{KEY} is forgotten: its next implement" in scenario.operator("forget", KEY).out
    assert db.get_ticket(scenario.conn, KEY) is not None


def test_a_ticket_to_remove_that_another_record_names_is_refused_held(scenario: Scenario) -> None:
    """A row that references the ticket, such as a grant, keeps it, and nothing is changed."""
    scenario.seen(STRAY)
    scenario.operator("grant", STRAY, "plan")
    refused = scenario.operator("forget", STRAY, code=1)
    assert f"forget refused (held): no source ever observed {STRAY}" in refused.err
    assert db.get_ticket(scenario.conn, STRAY) is not None
