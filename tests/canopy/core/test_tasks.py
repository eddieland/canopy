"""One-off tasks in the journal (DESIGN §36): their references, submissions, and what their runs report."""

import json

import pytest

from canopy.core import conversation, tasks
from canopy.core.vocab import TaskRunStatus
from tests.canopy.scenario_helpers import Scenario


def test_a_task_is_named_task_n() -> None:
    assert conversation.parse_ref("task:7") == conversation.Ref("task", "7")
    assert conversation.parse_ref("task:007") == conversation.Ref("task", "7")
    assert str(conversation.parse_ref("task:7")) == "task:7"
    for bad in ("task:0", "task:x", "task:"):
        with pytest.raises(conversation.Refused, match="not a reference"):
            conversation.parse_ref(bad)
    # A task takes `stop` and `show`; replies come with its conversation (ROADMAP M61, stage 2).
    conversation.check_verb(conversation.parse_ref("task:7"), "stop")
    with pytest.raises(conversation.Refused, match="which takes only stop, show"):
        conversation.check_verb(conversation.parse_ref("task:7"), "reply")


def test_a_tasks_branch_and_lease_are_named_by_its_number() -> None:
    assert tasks.branch_name("agent/", 3) == "agent/task/3"
    assert tasks.holder_key(3) == "task:3"


def test_a_runs_report_names_only_plain_prs_and_a_question_only_when_blocked() -> None:
    result = {
        "summary": "Sketched it.",
        "question": "Keep it?",
        "prs": ["https://example.test/pr/1", "javascript:alert(1)", 3],
    }
    assert tasks.run_messages(TaskRunStatus.DONE, json.dumps(result)) == [
        ("report", "Sketched it.\nhttps://example.test/pr/1"),
    ]
    assert tasks.run_messages(TaskRunStatus.BLOCKED, json.dumps(result))[1] == ("question", "Keep it?")
    assert tasks.run_messages(TaskRunStatus.CRASHED, json.dumps({"harness": "gone"})) == [("report", "gone")]
    assert tasks.run_messages(TaskRunStatus.TIMEOUT, None) == [("report", "ended timeout")]


def test_a_workspace_of_several_repositories_needs_the_tasks_named(ws_scenario: Scenario) -> None:
    refused = ws_scenario.operator("task", "submit", "Explore the cache.", code=1)
    assert "task submit refused (unknown_repo): --repo is required" in refused.err
    assert (
        "Submitted task:1 in web" in ws_scenario.operator("task", "submit", "Explore the cache.", "--repo", "web").out
    )
    assert [t.repo for t in tasks.every(ws_scenario.conn)] == ["web"]


def test_a_submission_or_a_stop_is_a_move_the_loop_wakes_for(scenario: Scenario) -> None:
    before = "2000-01-01T00:00:00.000Z"
    assert not tasks.moved_after(scenario.conn, before)
    scenario.operator("task", "submit", "Explore the cache.")
    assert tasks.moved_after(scenario.conn, before)
    scenario.time_passes(minutes=1)
    [task] = tasks.every(scenario.conn)
    assert not tasks.moved_after(scenario.conn, task.submitted_at)
    scenario.operator("stop", "task:1")
    assert tasks.moved_after(scenario.conn, task.submitted_at)
    assert tasks.queued(scenario.conn) == []
