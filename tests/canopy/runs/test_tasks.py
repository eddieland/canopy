"""One-off tasks (DESIGN §36, ROADMAP M61 stage 1): submitted by the operator, started by a tick, run in a slot."""

import io
import json
import sqlite3
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import override
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli.main import main
from canopy.core import config, conversation, db, prompts, records, sql, tasks
from canopy.core.context import Context
from canopy.core.vocab import RunStatus
from canopy.infra import logs, resources
from canopy.runs import reconcile
from canopy.runs import tasks as task_starts
from tests.canopy.helpers import (
    DEAD_PID,
    InlineRunner,
    agent_runs,
    commit_and_push,
    context,
    in_run,
    in_tick,
    json_block,
    operator,
    pool_statuses,
    present,
    private_worker_does,
    running_run,
    with_rebase,
)
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import CanopyEnv, GitPool, git

#: The branch task 1 works on, under the test operator's `agent/` prefix.
BRANCH = "agent/task/1"
TEXT = "Find out why the build is slow, and push a fix if one is small."
DONE: dict[str, object] = {"status": "done", "summary": "found it", "branch": BRANCH, "prs": []}
#: What a task's run writes nothing to: every table a ticket's work is recorded in.
TICKETS_WORK = (
    sql.select("count(*)").from_("tickets"),
    sql.select("count(*)").from_("runs"),
    sql.select("count(*)").from_("run_slots"),
    sql.select("count(*)").from_("ticket_units"),
    sql.select("count(*)").from_("messages"),
    sql.select("count(*)").from_("starts"),
    sql.select("count(*)").from_("follow_ups"),
    sql.select("count(*)").from_("decisions").where("ticket_key IS NOT NULL"),
)


@dataclass
class DeadOnSpawn(InlineRunner):
    """Starts nothing, as `InlineRunner` does, and reports a pid no process has: a `_task` that died at once."""

    @override
    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        super().spawn(args, cwd=cwd, log_path=log_path)
        return DEAD_PID


def inline_context(env: CanopyEnv, runner: InlineRunner | None = None) -> Context:
    """The workspace's context as its config now stands, migrated, whose runner starts no detached process."""
    found = context(env, runner or InlineRunner())
    db.migrate(found.conn, resources.migrations_dir())
    return found


@pytest.fixture
def inline(canopy_env: CanopyEnv, git_pool: GitPool) -> Context:
    """The workspace's context over real git slots, whose runner starts no detached process: a test runs `_task`."""
    assert git_pool.slots
    return inline_context(canopy_env)


def submit(text: str = TEXT, *args: str, code: int = 0) -> None:
    assert operator("task", "submit", text, *args) == code


def start(ctx: Context) -> list[task_starts.Started]:
    """Start the queued tasks as a live tick does, in a tick of its own."""
    with in_tick(ctx.conn) as tick_id:
        return task_starts.start_queued(ctx, tick_id, logs.for_tick(tick_id))


def run_task(ctx: Context, run_id: int) -> records.TaskRun:
    """Do task run `run_id` in this process, as its detached `canopy _task` would, and return it closed."""
    assert main(["_task", str(run_id)], runner=InlineRunner()) == 0
    return present(tasks.get_run(ctx.conn, run_id))


def every_run(conn: sqlite3.Connection) -> list[records.TaskRun]:
    return records.fetch_all(conn, records.TaskRun, sql.select("*").from_("task_runs").order_by("id"))


def wait_for_task_run(conn: sqlite3.Connection, run_id: int, timeout: float = 30) -> records.TaskRun:
    """Wait for a detached task run to close its row."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = present(tasks.get_run(conn, run_id))
        if run.status is not RunStatus.RUNNING:
            return run
        time.sleep(0.05)
    raise AssertionError(f"task run {run_id} still running after {timeout}s")


# Submitting


@pytest.mark.usefixtures("canopy_env")
def test_a_task_is_submitted_queued_and_listed(capsys: pytest.CaptureFixture[str], conn: sqlite3.Connection) -> None:
    submit(TEXT, "--project", "PROJ")
    [task] = tasks.every(conn)
    assert (task.text, task.repo, task.project, task.channel, task.stopped_at) == (TEXT, "repo", "PROJ", "cli", None)
    assert tasks.queued(conn) == [task]
    assert "Submitted task:1, to run in repo on agent/task/1; the next tick starts it." in capsys.readouterr().out
    assert operator("task", "list") == 0
    assert "task:1  queued  repo" in capsys.readouterr().out


@pytest.mark.usefixtures("canopy_env")
def test_a_dash_reads_the_text_from_stdin(conn: sqlite3.Connection) -> None:
    with mock.patch.object(sys, "stdin", io.StringIO("Plan the tickets for the new importer.\n")):
        submit("-")
    assert [t.text for t in tasks.every(conn)] == ["Plan the tickets for the new importer."]


@pytest.mark.usefixtures("canopy_env")
@pytest.mark.parametrize(
    ("args", "said"),
    [
        (("   ",), "task submit refused (bad_body): the task's text is empty"),
        (("x" * (tasks.MAX_TEXT + 1),), "task submit refused (bad_body)"),
        (("look", "--repo", "web"), "task submit refused (unknown_repo): 'web' is not a repository"),
        (("look", "--project", "a b"), "task submit refused (bad_project)"),
    ],
)
def test_a_submission_canopy_cannot_use_is_refused(
    capsys: pytest.CaptureFixture[str],
    conn: sqlite3.Connection,
    args: tuple[str, ...],
    said: str,
) -> None:
    submit(*args, code=1)
    assert said in capsys.readouterr().err
    assert tasks.every(conn) == []


@pytest.mark.parametrize("variable", ["CANOPY_RUN_ID", "CANOPY_TICK_ID"])
def test_a_submission_inside_a_run_or_a_tick_is_refused(
    capsys: pytest.CaptureFixture[str],
    ctx: Context,
    variable: str,
) -> None:
    with mock.patch.dict("os.environ", {variable: "7"}):
        assert main(["task", "submit", "push to main"]) == 1
        with pytest.raises(conversation.Refused, match="inside_run"):
            tasks.submit(ctx.conn, ctx.workspace, "push to main", repo=None, project=None, channel="cli")
    assert "task submit refused (inside_run)" in capsys.readouterr().err
    assert tasks.every(ctx.conn) == []


def test_a_workspace_file_may_lower_max_tasks_but_not_raise_it(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.shared_file, {"capacity": {"max_tasks": 3}})
    assert config.load(canopy_env.root, canopy_env.user_file).capacity.max_tasks == 1
    canopy_env.configure(canopy_env.shared_file, {"capacity": {"max_tasks": 0}})
    assert config.load(canopy_env.root, canopy_env.user_file).capacity.max_tasks == 0


# Starting


def test_a_queued_task_starts_on_the_next_live_tick_and_not_a_dry_one(scenario: Scenario, git_pool: GitPool) -> None:
    submit()
    scenario.tick(dry_run=True)
    assert every_run(scenario.conn) == []
    with private_worker_does(*commit_and_push(BRANCH), result=DONE):
        scenario.tick()
        [run] = every_run(scenario.conn)
        run = wait_for_task_run(scenario.conn, run.id)
    assert (run.status, run.branch, run.head) == (RunStatus.DONE, BRANCH, git_pool.remote_head(BRANCH))
    # The overseer planned around the slot the task's run held, and saw nothing else of it.
    *_, overseer = [r for r in agent_runs(scenario.agent_log) if "canopy-overseer" in r["argv"]]
    block = json_block(overseer["argv"][-1])
    assert block["capacity"]["running"] == 1
    assert not [s for r in block["repositories"] for s in r["leased_slots"] if "task" in s["lease_holder"]]
    assert TEXT not in overseer["argv"][-1]


def test_a_task_waits_for_max_tasks_and_starts_once_a_slot_frees(inline: Context) -> None:
    submit("first")
    submit("second")
    [first] = start(inline)
    assert start(inline) == []
    assert [t.text for t in tasks.queued(inline.conn)] == ["second"]
    with private_worker_does(result={"status": "done", "summary": "nothing to change"}):
        run_task(inline, first.run_id)
    [second] = start(inline)
    assert second.task_id == 2


@pytest.mark.usefixtures("git_pool")
def test_a_task_waits_for_max_workers_counting_workers_and_starts_once_one_ends(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.user_file, {"capacity": {"max_workers": 1}})
    ctx = inline_context(canopy_env)
    worker = running_run(ctx, "PROJ-1")
    submit()
    assert start(ctx) == []
    db.finish_run(ctx.conn, "runs", worker, RunStatus.DONE, "{}")
    assert [s.task_id for s in start(ctx)] == [1]


def test_a_task_stopped_before_its_tick_never_starts(capsys: pytest.CaptureFixture[str], inline: Context) -> None:
    submit()
    assert operator("stop", "task:1") == 0
    assert "task:1 is stopped; it had not started, and nothing starts it now." in capsys.readouterr().out
    assert start(inline) == []
    [task] = tasks.every(inline.conn)
    assert task.stopped_at is not None
    assert operator("show", "task:1") == 0
    assert "task:1: stopped, in repo" in capsys.readouterr().out


# The run


def test_the_worker_is_the_private_one_and_its_prompt_carries_the_text(inline: Context, agent_log: Path) -> None:
    submit()
    [started] = start(inline)
    with private_worker_does(result=DONE):
        run_task(inline, started.run_id)
    [worker] = agent_runs(agent_log)
    assert worker["argv"][:3] == ["run", "--agent", "canopy-worker-private"]
    prompt = worker["argv"][-1]
    assert TEXT in prompt
    assert f"Push only to `{BRANCH}`" in prompt
    assert worker["env"]["CANOPY_RUN_ID"] == f"task-{started.run_id}"


def test_a_pushed_branch_is_recorded_with_its_head_and_the_slot_returned(
    capsys: pytest.CaptureFixture[str],
    inline: Context,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    submit()
    [started] = start(inline)
    assert "leased" in pool_statuses(treehouse_state)
    with private_worker_does(*commit_and_push(BRANCH, "task 1: the fix"), result=DONE):
        run = run_task(inline, started.run_id)
    assert (run.status, run.head) == (RunStatus.DONE, git_pool.remote_head(BRANCH))
    assert set(pool_statuses(treehouse_state)) == {"available"}
    assert operator("show", "task:1") == 0
    out = capsys.readouterr().out
    assert f"run {run.id}  done" in out
    assert f"{BRANCH}  head {present(run.head)[:12]}" in out
    assert "summary: found it" in out


def test_commits_the_worker_left_unpushed_are_pushed_once(inline: Context, git_pool: GitPool) -> None:
    submit()
    [started] = start(inline)
    commit = ["git", "commit", "--quiet", "--allow-empty", "-m", "task 1: not pushed"]
    with private_worker_does(commit, result=DONE):
        run = run_task(inline, started.run_id)
    assert run.status is RunStatus.DONE
    assert run.head is not None
    assert run.head == git_pool.remote_head(BRANCH)


def test_work_that_cannot_be_pushed_is_unpushed(inline: Context, git_pool: GitPool) -> None:
    submit()
    [started] = start(inline)
    git_pool.reject_pushes()
    commit = ["git", "commit", "--quiet", "--allow-empty", "-m", "task 1: refused"]
    with private_worker_does(commit, result=DONE):
        run = run_task(inline, started.run_id)
    assert run.status is RunStatus.UNPUSHED
    assert run.head is None
    assert "the push failed" in json.loads(present(run.result_json))["harness"]


def test_a_rewritten_branch_is_never_pushed_with_force_even_under_rebase(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    with_rebase(canopy_env)
    ctx = inline_context(canopy_env)
    # The task's branch is on origin from an earlier run, a commit past main.
    earlier = tmp_path / "earlier"
    git("clone", "--quiet", str(git_pool.origin), str(earlier), cwd=tmp_path)
    git("commit", "--quiet", "--allow-empty", "-m", "earlier run", cwd=earlier)
    git("push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=earlier)
    pushed = git_pool.remote_head(BRANCH)
    submit()
    [started] = start(ctx)
    # The worker rewrites the branch: it drops the earlier commit for another on main, and leaves it to canopy to push.
    rewrite = [
        ["git", "reset", "--quiet", "--hard", "origin/main"],
        ["git", "commit", "--quiet", "--allow-empty", "-m", "rewritten"],
    ]
    with private_worker_does(*rewrite, result=DONE):
        run = run_task(ctx, started.run_id)
    assert run.status is RunStatus.UNPUSHED
    assert git_pool.remote_head(BRANCH) == pushed
    assert run.head == pushed


def test_a_branch_the_worker_pushed_with_force_is_named_in_its_note(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    with_rebase(canopy_env)
    ctx = inline_context(canopy_env)
    earlier = tmp_path / "earlier"
    git("clone", "--quiet", str(git_pool.origin), str(earlier), cwd=tmp_path)
    git("commit", "--quiet", "--allow-empty", "-m", "earlier run", cwd=earlier)
    git("push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=earlier)
    pushed = present(git_pool.remote_head(BRANCH))
    submit()
    [started] = start(ctx)
    # The push `trust.rebase` lets the private worker's definition make, which a task's prompt forbids.
    forced = [
        ["git", "reset", "--quiet", "--hard", "origin/main"],
        ["git", "commit", "--quiet", "--allow-empty", "-m", "rewritten"],
        ["git", "push", "--quiet", "--force-with-lease", "origin", f"HEAD:refs/heads/{BRANCH}"],
    ]
    with private_worker_does(*forced, result=DONE):
        run = run_task(ctx, started.run_id)
    assert run.status is RunStatus.DONE
    assert run.head == git_pool.remote_head(BRANCH) != pushed
    note = json.loads(present(run.result_json))["harness"]
    assert note.startswith(f"{BRANCH} no longer holds {pushed[:12]}, its head when the run started: pushed with force")


def test_a_result_canopy_cannot_read_is_unknown(inline: Context) -> None:
    submit()
    [started] = start(inline)
    with private_worker_does(result={"status": "finished"}):
        run = run_task(inline, started.run_id)
    assert run.status is RunStatus.UNKNOWN


def test_no_row_a_task_writes_names_a_ticket(inline: Context) -> None:
    submit(TEXT, "--project", "PROJ")
    [started] = start(inline)
    with private_worker_does(*commit_and_push(BRANCH), result=DONE):
        run_task(inline, started.run_id)
    assert [sql.execute(inline.conn, query).fetchone()[0] for query in TICKETS_WORK] == [0] * len(TICKETS_WORK)


# Stopping, and a run whose process died


def test_stop_now_ends_a_running_task_and_returns_its_slot(
    capsys: pytest.CaptureFixture[str],
    inline: Context,
    treehouse_state: Path,
) -> None:
    submit()
    [started] = start(inline)
    assert operator("stop", "task:1") == 0
    out = capsys.readouterr().out
    assert f"Its run {started.run_id} is still working and will finish; --now ends it." in out
    assert present(tasks.get_run(inline.conn, started.run_id)).status is RunStatus.RUNNING
    assert operator("stop", "task:1", "--now") == 0
    assert f"Its run {started.run_id} was ended and its slot returned." in capsys.readouterr().out
    run = present(tasks.get_run(inline.conn, started.run_id))
    assert run.status is RunStatus.STOPPED
    assert set(pool_statuses(treehouse_state)) == {"available"}
    assert start(inline) == []


def test_a_stop_inside_a_run_is_refused(capsys: pytest.CaptureFixture[str], inline: Context) -> None:
    submit()
    with in_run(7):
        assert main(["stop", "task:1"]) == 1
    assert "stop refused (inside_run)" in capsys.readouterr().err
    assert [t.stopped_at for t in tasks.every(inline.conn)] == [None]


def test_reconcile_closes_a_task_run_whose_process_is_gone_and_returns_its_slot(
    canopy_env: CanopyEnv,
    inline: Context,
    treehouse_state: Path,
) -> None:
    submit()
    [started] = start(inline_context(canopy_env, DeadOnSpawn()))
    with in_tick(inline.conn) as tick_id:
        reconciled = reconcile.run(inline, logs.for_tick(tick_id))
    run = present(tasks.get_run(inline.conn, started.run_id))
    assert run.status is RunStatus.CRASHED
    assert json.loads(present(run.result_json)) == {"harness": "the task's process is gone"}
    assert set(pool_statuses(treehouse_state)) == {"available"}
    assert reconciled.capacity.running == 0


def test_a_running_task_holds_its_slot_through_reconcile(inline: Context, treehouse_state: Path) -> None:
    submit()
    start(inline)
    with in_tick(inline.conn) as tick_id:
        reconciled = reconcile.run(inline, logs.for_tick(tick_id))
    assert reconciled.capacity.running == 1
    assert "leased" in pool_statuses(treehouse_state)


# The prompt


def test_the_task_prompt(canopy_env: CanopyEnv, markdown_snapshot: SnapshotAssertion) -> None:
    values = {
        "TASK_ID": "1",
        "TASK": TEXT,
        "REPO": "repo",
        "SLOT": "/pool/1/repo",
        "BRANCH": BRANCH,
        "BASE": "main",
        "TIMEOUT_MINUTES": "45",
    }
    cfg = config.load(canopy_env.root, canopy_env.user_file)
    assert prompts.render_task(cfg, values) == markdown_snapshot
