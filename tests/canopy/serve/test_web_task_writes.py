"""The operator's tasks through the web UI (DESIGN §36, TRUST_MODEL T1).

A submission, a reply, and a stop write through the functions the CLI's verbs call, with channel `web`, and its guards
refuse them as they refuse the CLI's.
"""

from pathlib import Path

import pytest

from canopy.core import tasks
from canopy.core.context import Context
from canopy.core.vocab import RunStatus
from canopy.infra import logs
from canopy.runs import tasks as task_starts
from tests.canopy.helpers import in_run, in_tick, inline_context, pool_statuses, present
from tests.canopy.web_helpers import refused, signed_in_client
from tests.conftest import CanopyEnv, GitPool

TEXT = "Find out why the build is slow, and push a fix if one is small."
#: A reply's form, with the submission id it drew.
REPLY = {"body": "Look at the cache step first.", "submission": "form-0001"}


def test_a_task_submitted_from_the_web_is_queued_as_the_operators_on_channel_web(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    submitted = c.post("/api/tasks", json={"text": f"  {TEXT}  ", "project": "PROJ"}, headers=headers)
    assert submitted.json() == {"id": 1, "repo": "repo", "branch": "agent/task/1", "no_capacity": False}
    [task] = tasks.every(ctx.conn)
    assert (task.text, task.repo, task.project, task.channel) == (TEXT, "repo", "PROJ", "web")
    assert tasks.queued(ctx.conn) == [task]


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ({"text": "   "}, "bad_body: the task's text is empty"),
        ({"text": "x" * (tasks.MAX_TEXT + 1)}, "bad_body"),
        ({"text": "look", "repo": "web"}, "unknown_repo: 'web' is not a repository"),
        ({"text": "look", "project": "a b"}, "bad_project"),
    ],
)
def test_a_submission_canopy_cannot_use_is_refused_as_the_cli_refuses_it(
    ctx: Context,
    body: dict[str, str],
    said: str,
) -> None:
    c, headers = signed_in_client(ctx)
    assert refused(c.post("/api/tasks", json=body, headers=headers)).startswith(said)
    assert tasks.every(ctx.conn) == []


def test_every_task_write_is_refused_inside_a_run(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.post("/api/tasks", json={"text": TEXT}, headers=headers).status_code == 200
    with in_run(7):
        assert refused(c.post("/api/tasks", json={"text": TEXT}, headers=headers)).startswith("inside_run")
        assert refused(c.post("/api/tasks/1/replies", json=REPLY, headers=headers)).startswith("inside_run")
        assert refused(c.post("/api/tasks/1/stop", json={"now": False}, headers=headers)).startswith("inside_run")
    [task] = tasks.every(ctx.conn)
    assert task.stopped_at is None
    assert tasks.messages_of(ctx.conn, 1) == []


def test_a_reply_from_the_web_is_the_operators_next_instruction_and_a_retry_records_nothing(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert refused(c.post("/api/tasks/9/replies", json=REPLY, headers=headers)) == "unknown: canopy has no task:9"
    assert c.post("/api/tasks", json={"text": TEXT}, headers=headers).status_code == 200
    blank = {**REPLY, "body": "  "}
    assert refused(c.post("/api/tasks/1/replies", json=blank, headers=headers)).startswith("bad_body")

    first = c.post("/api/tasks/1/replies", json=REPLY, headers=headers).json()
    again = c.post("/api/tasks/1/replies", json=REPLY, headers=headers).json()
    assert {k: v for k, v in first.items() if k != "message_id"} == {"answers": None, "new": True, "running_run": None}
    assert again == {**first, "new": False}
    [message] = tasks.messages_of(ctx.conn, 1)
    assert (message.source, message.kind, message.channel) == ("operator", "reply", "web")
    assert message.submission == "web:form-0001"


def test_a_stop_from_the_web_drops_a_queued_task_and_a_reply_to_it_is_refused(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert refused(c.post("/api/tasks/9/stop", json={"now": False}, headers=headers)) == (
        "unknown: canopy has no task:9"
    )
    assert c.post("/api/tasks", json={"text": TEXT}, headers=headers).status_code == 200

    stopped = c.post("/api/tasks/1/stop", json={"now": False}, headers=headers).json()
    assert stopped == {"already": False, "dropped": True, "running_run": None, "ended": False}
    assert tasks.queued(ctx.conn) == []
    again = c.post("/api/tasks/1/stop", json={"now": True}, headers=headers).json()
    assert again == {"already": True, "dropped": False, "running_run": None, "ended": False}
    assert refused(c.post("/api/tasks/1/replies", json=REPLY, headers=headers)).startswith("stopped")


def test_stop_now_from_the_web_ends_the_run_and_returns_its_slot_as_canopy_stop_now_does(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    assert git_pool.slots
    ctx = inline_context(canopy_env)
    c, headers = signed_in_client(ctx)
    assert c.post("/api/tasks", json={"text": TEXT}, headers=headers).status_code == 200
    with in_tick(ctx.conn) as tick_id:
        [started] = task_starts.start_queued(ctx, tick_id, logs.for_tick(tick_id))

    reply = c.post("/api/tasks/1/replies", json=REPLY, headers=headers).json()
    assert reply["running_run"] == started.run_id
    graceful = c.post("/api/tasks/1/stop", json={"now": False}, headers=headers).json()
    assert graceful == {"already": False, "dropped": False, "running_run": started.run_id, "ended": False}
    assert present(tasks.get_run(ctx.conn, started.run_id)).status is RunStatus.RUNNING

    now = c.post("/api/tasks/1/stop", json={"now": True}, headers=headers).json()
    assert now == {"already": True, "dropped": False, "running_run": started.run_id, "ended": True}
    run = present(tasks.get_run(ctx.conn, started.run_id))
    assert run.status is RunStatus.STOPPED
    assert "canopy stop --now" in str(run.result_json)
    assert set(pool_statuses(treehouse_state)) == {"available"}
