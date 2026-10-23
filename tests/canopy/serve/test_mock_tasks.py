"""The mock journal's one-off tasks (DESIGN §36): each state a task has, in attention, the spend, and the worktrees."""

import pytest

from canopy.core import db, task_tickets, tasks
from canopy.core.vocab import RunStatus
from canopy.serve import mock, mock_tasks
from canopy.serve.backend import Backend
from tests.canopy.web_helpers import client


def test_the_mock_holds_a_task_in_every_state_over_the_three_repositories(backend: Backend) -> None:
    with backend.open() as ctx:
        every = {t.id: t for t in tasks.every(ctx.conn)}
        latest = tasks.latest_runs(ctx.conn)
        assert {t.repo for t in every.values()} == {"api", "mobile", "web"}
        assert {r.status for r in latest.values()} == {
            RunStatus.DONE,
            RunStatus.FAILED,
            RunStatus.STOPPED,
            RunStatus.BLOCKED,
            RunStatus.RUNNING,
        }
        assert [t.id for t in tasks.queued(ctx.conn)] == [7]
        assert every[3].stopped_at is not None
        # Task 1 is done: pushed, a draft PR in its result, its report kept, and two tickets recorded against it.
        done = latest[1]
        assert done.head is not None
        assert mock_tasks.PR_97 in (done.result_json or "")
        found = tasks.latest_report(ctx.conn, ctx.workspace.state_dir, 1)
        assert found is not None
        assert found[1].startswith("# Checkout bundle")
        assert [t.key for t in task_tickets.of_task(ctx.conn, 1)] == ["ABC-120", "ABC-121"]
        # The running task's run holds the lease the pool shows on mobile's second slot.
        [running] = tasks.running(ctx.conn)
        assert (running.task_id, running.slot_path) == (
            mock_tasks.RUNNING_TASK,
            mock.slot_path(ctx.workspace.root, "mobile", 2),
        )
        assert all(db.parse_time(r.started_at).date().isoformat() == "2026-10-08" for r in latest.values())


def test_attention_and_spend_show_the_tasks(backend: Backend) -> None:
    c = client(None, backend)
    items = {(i["reason"], i["subject"]) for i in c.get("/api/attention").json()}
    assert ("awaiting_reply", "task:4") in items
    assert ("task_ticket_unrecorded", "task:5") in items
    totals = c.get("/api/spend/breakdown", params={"days": 7}).json()["totals"]
    assert totals["tasks"] == pytest.approx(4.51)
    [mobile] = [p for p in c.get("/api/worktrees").json() if p["repo"] == "mobile"]
    assert [w["state"] for w in mobile["worktrees"]] == ["working", "working"]
    assert mobile["worktrees"][1]["holder"] == "canopy:task:6"


def test_a_stop_clears_a_task_s_items(backend: Backend) -> None:
    with backend.open() as ctx:
        tasks.stop(ctx.conn, 4)
        tasks.stop(ctx.conn, 5)
        assert mock_tasks.attention(ctx.conn) == []


def test_task_1_s_run_left_its_session_s_events_for_its_transcript(backend: Backend) -> None:
    found = client(None, backend).get("/api/tasks/1/runs/1/transcript").json()
    assert (found["status"], found["session_id"]) == ("read", "ses_task1")
    steps = [e for e in found["entries"] if e["kind"] == "step"]
    # Its three model calls cost what its row says.
    assert sum(s["cost_usd"] for s in steps) == pytest.approx(2.12)
    assert len(steps) == 3
