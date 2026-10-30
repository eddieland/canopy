"""The web UI's one-off tasks (DESIGN §36).

What `canopy task list` and `canopy show task:N` print, each run with its transcript, and the report it left, read from
the state directory as the CLI reads it.
"""

import json
from pathlib import Path

from canopy.core import conversation, db, pools, records
from canopy.core.context import Context
from canopy.core.vocab import PoolKind, RunStatus
from canopy.runs import tasks
from canopy.serve.backend import Backend
from canopy.serve.task_views import RUN_STANDINGS
from tests.canopy.helpers import present
from tests.canopy.web_helpers import client

TEXT = "Find out why the nightly export\x07 takes an hour, and say what would halve it."
REPORT = "# Nightly export\n\nThe <script>alert(1)</script> step\x1b[31m re-reads every row.\n"


def test_a_task_is_listed_with_where_it_stands_as_it_goes(backend: Backend) -> None:
    c = client(None, backend)
    # The mock's own tasks stay as they are, after the newest: this one.
    seeded = c.get("/api/tasks").json()
    with backend.open() as ctx:
        task = submit(ctx)
    [listed, *rest] = c.get("/api/tasks").json()
    assert rest == seeded
    assert (listed["id"], listed["repo"], listed["project"], listed["channel"]) == (task.id, "web", "ACME", "cli")
    # The operator's text as text, a control character a space.
    assert listed["text"] == TEXT.replace("\x07", " ")
    assert (listed["standing"], listed["latest"], listed["runs"]) == ("queued", None, 0)
    assert listed["branch"] == f"agent/task/{task.id}"

    with backend.open() as ctx:
        run_id = start(ctx, task)
    [listed, *_] = c.get("/api/tasks").json()
    assert (listed["standing"], listed["latest"]["id"], listed["latest"]["state"], listed["runs"]) == (
        "running",
        run_id,
        "running",
        1,
    )

    with backend.open() as ctx:
        end(ctx, run_id, RunStatus.BLOCKED, question="Is the 02:00 window fixed?")
        question = present(conversation.task_question(ctx.conn, task.id))
    [listed, *_] = c.get("/api/tasks").json()
    # The CLI words it as the run's `blocked`; the API says what it waits on.
    assert (listed["standing"], listed["question_id"]) == ("awaiting_reply", question.id)

    with backend.open() as ctx:
        conversation.reply(ctx.conn, conversation.parse_ref(f"task:{task.id}"), "Yes.", channel="web")
    [listed, *_] = c.get("/api/tasks").json()
    assert (listed["standing"], listed["question_id"]) == ("queued", None)

    with backend.open() as ctx:
        tasks.stop(ctx.conn, task.id)
    [listed, *_] = c.get("/api/tasks").json()
    assert listed["standing"] == "stopped"
    assert listed["stopped_at"] is not None


def test_every_run_status_is_a_standing_of_the_same_word() -> None:
    assert {str(s): w for s, w in RUN_STANDINGS.items()} == {str(s): str(s) for s in RunStatus}


def test_a_tasks_page_is_its_runs_conversation_and_tickets(backend: Backend) -> None:
    with backend.open() as ctx:
        task = submit(ctx)
        run_id = start(ctx, task)
        end(
            ctx,
            run_id,
            RunStatus.DONE,
            summary="Found it\x1b: the export re-reads every row.",
            prs=["https://github.com/acme/web/pull/9", "javascript:alert(1)"],
            head="a" * 40,
            tickets=["ACME-7"],
        )
    c = client(None, backend)
    page = c.get(f"/api/tasks/{task.id}").json()

    assert (page["task"]["id"], page["task"]["standing"]) == (task.id, "done")
    [run] = page["runs"]
    assert (run["id"], run["status"], run["state"], run["head"]) == (run_id, "done", "done", "a" * 40)
    assert run["summary"] == "Found it : the export re-reads every row."
    # Only a plain https:// URL is a PR.
    assert run["prs"] == ["https://github.com/acme/web/pull/9"]
    assert run["reported"] is False
    [report] = page["messages"]
    assert (report["source"], report["kind"], report["task_run_id"], report["run_id"]) == (
        "worker",
        "report",
        run_id,
        None,
    )
    assert "\x1b" not in report["body"]
    assert [(t["key"], t["run_id"]) for t in page["tickets"]] == [("ACME-7", run_id)]

    assert c.get("/api/tasks/99").status_code == 404
    assert c.get("/api/tasks/0").status_code == 422


def test_a_task_run_is_found_only_under_its_own_task_with_its_whole_result(backend: Backend) -> None:
    with backend.open() as ctx:
        task = submit(ctx)
        other = submit(ctx)
        run_id = start(ctx, task)
        end(ctx, run_id, RunStatus.BLOCKED, summary="Half way.\nThe rest waits.", question="Which\x07 window?")
    c = client(None, backend)
    found = c.get(f"/api/tasks/{task.id}/runs/{run_id}").json()

    assert (found["task_id"], found["run"]["id"], found["run"]["state"]) == (task.id, run_id, "blocked")
    assert (found["summary"], found["question"], found["note"]) == (
        "Half way.\nThe rest waits.",
        "Which  window?",
        None,
    )
    assert found["models"]["status"] == "no_session"
    assert found["model"] is None  # it asked for none, so the runtime's default served it
    with backend.open() as ctx:
        records.update(records.TaskRun).set(model="provider/model-a").where("id = ?", run_id).run(ctx.conn)
    assert c.get(f"/api/tasks/{task.id}/runs/{run_id}").json()["model"] == "provider/model-a"
    for path in ("", "/transcript", "/report"):
        assert c.get(f"/api/tasks/{other.id}/runs/{run_id}{path}").status_code == 404
        assert c.get(f"/api/tasks/{task.id}/runs/99{path}").status_code == 404


def test_a_task_runs_transcript_is_read_back_from_its_log(backend: Backend) -> None:
    with backend.open() as ctx:
        task = submit(ctx)
        run_id = start(ctx, task)
        end(ctx, run_id, RunStatus.DONE)
    c = client(None, backend)
    path = f"/api/tasks/{task.id}/runs/{run_id}/transcript"
    assert c.get(path).json()["status"] == "no_session"

    with backend.open() as ctx:
        # A mock run's log, with its session.
        mock_run = present(db.get_run(ctx.conn, 39))
        ctx.conn.execute(
            "UPDATE task_runs SET log_path = ?, session_id = ? WHERE id = ?",
            (mock_run["log_path"], mock_run["session_id"], run_id),
        )
    found = c.get(path).json()
    assert found["status"] == "read"
    assert found["entries"] == c.get("/api/runs/39/transcript").json()["entries"]


def test_a_task_runs_report_is_its_file_as_text_and_says_when_it_was_edited_or_is_gone(backend: Backend) -> None:
    with backend.open() as ctx:
        task = submit(ctx)
        run_id = start(ctx, task)
        end(ctx, run_id, RunStatus.DONE)
        written = tasks.keep_report(ctx.state_dir, task.id, run_id, REPORT)
        tasks.set_report(ctx.conn, run_id, written.sha256)
        path = tasks.report_path(ctx.state_dir, task.id, run_id)
        unreported = start(ctx, task, replied=True)
        end(ctx, unreported, RunStatus.DONE)
    c = client(None, backend)
    url = f"/api/tasks/{task.id}/runs/{run_id}/report"

    found = c.get(url).json()
    # Markup stays its characters; a control character is a space.
    assert found["text"] == REPORT.replace("\x1b", " ")
    # Its path from the workspace root, as a run's log path is shown, so a page never shows a machine's temp dir.
    shown = str(path.relative_to(backend.workspace.root))
    assert (found["path"], found["problem"], found["edited"]) == (shown, None, False)
    assert c.get(f"/api/tasks/{task.id}").json()["runs"][0]["reported"] is True

    path.write_text("# Edited by hand\n")
    assert (c.get(url).json()["text"], c.get(url).json()["edited"]) == ("# Edited by hand\n", True)
    path.unlink()
    path.symlink_to(Path(ctx.state_dir) / "elsewhere.md")
    assert (c.get(url).json()["text"], c.get(url).json()["problem"]) == (None, "not a regular file")
    path.unlink()
    assert c.get(url).json()["problem"] == "missing"

    # A run that left no report has none to read.
    assert c.get(f"/api/tasks/{task.id}/runs/{unreported}/report").status_code == 404


def submit(ctx: Context) -> records.Task:
    """Submit the operator's task, to run in `web` and file tickets in ACME."""
    return tasks.submit(ctx.conn, ctx.workspace, TEXT, repo="web", project="ACME", channel="cli")


def start(ctx: Context, task: records.Task, *, replied: bool = False) -> int:
    """Start a run of `task` as a tick does, after a reply to it when `replied`; return the run's id."""
    if replied:
        conversation.reply(ctx.conn, conversation.parse_ref(f"task:{task.id}"), "Go on.", channel="cli")
    lease = pools.Lease(
        path=ctx.workspace.root / "slot",
        lease_id=f"lease-{task.id}",
        lease_holder=tasks.holder(task.id),
        leased_at=db.now(),
        base_branch="main",
    )
    return present(
        tasks.insert_run(
            ctx.conn,
            task=task,
            tick_id=1,
            branch_name=tasks.branch(ctx.config.trust.branch_prefix, task.id),
            lease=lease,
            pool=PoolKind.TREEHOUSE,
            logs_dir=ctx.state_dir / "task-runs",
        ),
    )


def end(
    ctx: Context,
    run_id: int,
    status: RunStatus,
    *,
    summary: str = "Done.",
    question: str | None = None,
    prs: list[str] | None = None,
    head: str | None = None,
    tickets: list[str] | None = None,
) -> None:
    """Close run `run_id` as `_task` does, with a result saying `summary`, and `question` for a blocked one."""
    result: dict[str, object] = {"status": str(status), "summary": summary, "prs": prs or []}
    if question is not None:
        result["question"] = question
    assert tasks.close_run(ctx.conn, ctx.config, run_id, status, json.dumps(result), head=head, tickets=tickets or [])


def test_a_tasks_runs_name_the_models_that_served_them_so_the_runs_page_lists_them_by_model(backend: Backend) -> None:
    with backend.open() as ctx:
        records.insert(
            records.RunModel,
            run_table="task_runs",
            run_id=1,
            model="openai/gpt-5",
            replies=3,
            cost_usd=0.1,
        ).run(ctx.conn)
    c = client(None, backend)
    assert {t["id"]: t["latest"]["served"] for t in c.get("/api/tasks").json() if t["latest"]}[1] == ["openai/gpt-5"]
    page = c.get("/api/tasks/1").json()
    assert (page["task"]["latest"]["served"], [r["served"] for r in page["runs"]]) == (
        ["openai/gpt-5"],
        [["openai/gpt-5"]],
    )
    assert c.get("/api/tasks/1/runs/1").json()["run"]["served"] == ["openai/gpt-5"]
