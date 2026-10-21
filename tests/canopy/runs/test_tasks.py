"""One-off tasks (DESIGN §36, ROADMAP M61 stage 1): submitted by the operator, started by a tick in code, and run."""

import json
import re
from contextlib import AbstractContextManager
from pathlib import Path

from syrupy.assertion import SnapshotAssertion

from canopy.core import records, tasks
from canopy.core.vocab import TaskRunStatus
from tests.canopy.helpers import (
    commit_and_push,
    in_run,
    pool_statuses,
    present,
    private_worker_does,
    scripted,
    waits,
    with_events,
)
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import CanopyEnv, GitPool, git

TEXT = "Find out why the cache misses on cold starts, and push a sketch of a fix."
BRANCH = "agent/task/1"
DONE: dict[str, object] = {"status": "done", "summary": "The cache key drops the region.", "branch": BRANCH, "prs": []}


def submits(scenario: Scenario, text: str = TEXT, *args: str) -> int:
    """The operator submits a task, and gets its number back."""
    out = scenario.operator("task", "submit", text, *args).out
    found = re.search(r"Submitted task:(\d+)", out)
    assert found is not None, out
    return int(found.group(1))


def pushes_task(branch: str = BRANCH, *, result: dict[str, object] | None = None) -> AbstractContextManager[None]:
    """The task's worker commits, pushes its branch, and reports it done."""
    return private_worker_does(*commit_and_push(branch, "task: a sketch"), result=result or DONE)


def task_runs(scenario: Scenario) -> list[records.TaskRun]:
    return tasks.runs_of(scenario.conn, 1)


def test_a_submitted_task_is_queued_and_shown(scenario: Scenario) -> None:
    number = submits(scenario, TEXT, "--project", "PROJ")
    assert number == 1
    task = present(tasks.get(scenario.conn, 1))
    assert (task.text, task.repo, task.project, task.channel) == (TEXT, "repo", "PROJ", "cli")
    assert "task:1  queued  repo" in scenario.operator("task", "list").out
    shown = scenario.operator("show", "task:1").out
    assert "task:1: queued, in repo" in shown
    assert f"branch {BRANCH}" in shown
    assert "none yet: the next tick starts it" in shown


def test_a_submission_inside_a_run_is_refused(scenario: Scenario) -> None:
    with in_run(5):
        refused = scenario.operator("task", "submit", TEXT, code=1)
        assert "task submit refused (inside_run)" in refused.err
        assert "refused (inside_run)" in scenario.operator("task", "list", code=1).err
        assert "refused (inside_run)" in scenario.operator("show", "task:1", code=1).err
    assert tasks.every(scenario.conn) == []


def test_a_submission_needs_text_and_a_plain_project(scenario: Scenario) -> None:
    assert "(bad_body)" in scenario.operator("task", "submit", "  ", code=1).err
    assert "(bad_project)" in scenario.operator("task", "submit", TEXT, "--project", "a/b", code=1).err
    assert "(unknown_repo)" in scenario.operator("task", "submit", TEXT, "--repo", "nope", code=1).err
    assert tasks.every(scenario.conn) == []


def test_the_next_tick_runs_a_task_its_dry_run_does_not(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    submits(scenario)
    dry = scenario.tick(dry_run=True)
    assert dry.tasks == []
    assert task_runs(scenario) == []
    ticked = scenario.tick(task=pushes_task())
    [run] = ticked.tasks
    assert (run.status, run.branch, run.repo) == (TaskRunStatus.DONE, BRANCH, "repo")
    assert run.head == git_pool.remote_head(BRANCH)
    assert run.lease_holder == "canopy:task:1"
    # The slot is back in the pool, and the overseer never saw the task: no decision of the tick names it.
    assert set(pool_statuses(treehouse_state)) == {"available"}
    assert all(d.ticket_key is None for d in ticked.decisions)
    # Its worker's prompt carries the operator's text, the branch canopy named, and its repository.
    prompt = (scenario.env.state_dir / "tasks" / "runs" / f"{run.id}.prompt").read_text()
    assert TEXT in prompt
    assert f"git push origin HEAD:refs/heads/{BRANCH}" in prompt


def test_a_task_runs_once(scenario: Scenario, git_pool: GitPool) -> None:
    submits(scenario)
    scenario.tick(task=pushes_task())
    again = scenario.tick()
    assert again.tasks == []
    assert len(task_runs(scenario)) == 1
    assert "task:1  done  repo" in scenario.operator("task", "list").out


def test_show_names_each_runs_branch_head_and_report(scenario: Scenario, git_pool: GitPool) -> None:
    submits(scenario)
    [run] = scenario.tick(task=pushes_task()).tasks
    shown = scenario.operator("show", "task:1").out
    assert f"task run {run.id}  done" in shown
    assert f"{BRANCH}: pushed at {git_pool.remote_head(BRANCH)}" in shown
    assert "worker report (task run 1)" in shown
    assert "The cache key drops the region." in shown


def test_a_blocked_run_asks_its_question_in_the_tasks_conversation(scenario: Scenario, git_pool: GitPool) -> None:
    submits(scenario)
    asked: dict[str, object] = {
        "status": "blocked",
        "summary": "Two ways in.",
        "question": "Fix it in the client or the server?",
    }
    [run] = scenario.tick(task=private_worker_does(result=asked)).tasks
    assert (run.status, run.head) == (TaskRunStatus.BLOCKED, None)
    said = [(m.kind, m.body, m.task_run_id, m.run_id) for m in tasks.messages_of(scenario.conn, 1, 10)]
    assert said == [
        ("report", "Two ways in.", run.id, None),
        ("question", "Fix it in the client or the server?", run.id, None),
    ]
    # Nothing a task writes names a ticket: no ticket, run, start, or ticket message.
    for table in ("tickets", "runs", "starts"):
        assert scenario.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0  # noqa: S608
    assert scenario.conn.execute("SELECT count(*) FROM messages WHERE subject_kind != 'task'").fetchone()[0] == 0


def test_a_run_that_pushes_nothing_is_no_failure(scenario: Scenario, git_pool: GitPool) -> None:
    submits(scenario)
    [run] = scenario.tick(task=private_worker_does(result={"status": "done", "summary": "Read only."})).tasks
    assert (run.status, run.head) == (TaskRunStatus.DONE, None)
    assert git_pool.remote_head(BRANCH) is None


def test_work_left_unpushed_is_pushed_once_or_the_run_is_unpushed(scenario: Scenario, git_pool: GitPool) -> None:
    submits(scenario)
    git_pool.reject_pushes()
    commits = [["git", "commit", "--quiet", "--allow-empty", "-m", "task: a sketch"]]
    [run] = scenario.tick(task=private_worker_does(*commits, result=DONE)).tasks
    assert run.status is TaskRunStatus.UNPUSHED
    assert f"commits on {BRANCH} are not on origin" in json.loads(present(run.result_json))["harness"]
    assert run.head is None


def test_a_tasks_branch_is_never_pushed_with_force_whatever_rebase_says(
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    scenario.configures(trust={"rebase": True})
    submits(scenario)
    # The branch is already on origin; the worker moves off it, commits, and leaves the push to canopy.
    seed = tmp_path / "seed"
    git("commit", "--quiet", "--allow-empty", "-m", "earlier", cwd=seed)
    git("push", "--quiet", str(git_pool.origin), f"HEAD:refs/heads/{BRANCH}", cwd=seed)
    earlier = git_pool.remote_head(BRANCH)
    rewrite = [
        ["git", "reset", "--quiet", "--hard", "origin/main"],
        ["git", "commit", "--quiet", "--allow-empty", "-m", "rewritten"],
    ]
    [run] = scenario.tick(task=private_worker_does(*rewrite, result=DONE)).tasks
    assert run.status is TaskRunStatus.UNPUSHED
    assert git_pool.remote_head(BRANCH) == earlier
    assert run.head == earlier


def test_max_tasks_holds_the_next_task_until_a_later_tick(scenario: Scenario, git_pool: GitPool) -> None:
    submits(scenario)
    submits(scenario, "Plan the tickets the cache needs.")
    first = scenario.tick(hold=True)
    [held] = first.tasking
    assert held.row.task_id == 1
    # The overseer plans around the slot the task holds, and sees nothing else of it.
    assert scenario.state()["capacity"]["running"] == 1
    assert "task" not in json.dumps(scenario.state()["tickets"])
    assert scenario.tick().tasks == []
    held.finishes()
    [second] = scenario.tick().tasks
    assert second.task_id == 2


def test_max_workers_counts_task_runs_with_worker_runs(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(capacity={"max_workers": 1})
    working = scenario.starts()
    submits(scenario)
    assert scenario.tick(*waits("PROJ-1")).tasks == []
    working.finishes()
    [run] = scenario.tick(*waits("PROJ-1"), hold=True).tasking
    # And a dispatch waits for the task run's slot in turn.
    [(action, reason)] = scenario.refuses(dispatches())
    assert (action, reason) == ("refused:capacity", "1 of 1 workers are running")
    run.finishes()


def test_max_tasks_of_zero_starts_none(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(capacity={"max_tasks": 0})
    submits(scenario)
    assert scenario.tick().tasks == []
    assert "task:1  queued" in scenario.operator("task", "list").out


def test_stopping_a_queued_task_drops_it(scenario: Scenario, git_pool: GitPool) -> None:
    submits(scenario)
    assert "is stopped before it ran" in scenario.operator("stop", "task:1").out
    assert scenario.tick().tasks == []
    assert "task:1  stopped" in scenario.operator("task", "list").out
    assert "was already stopped" in scenario.operator("stop", "task:1").out


def test_stopping_a_running_task_lets_its_run_finish_unless_now(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    submits(scenario)
    [held] = scenario.tick(hold=True).tasking
    said = scenario.operator("stop", "task:1").out
    assert f"Its task run {held.id} is still working and will finish" in said
    assert "stopped, its run finishing" in scenario.operator("task", "list").out
    ended = scenario.operator("stop", "task:1", "--now").out
    assert f"Its task run {held.id} was ended and its slot returned." in ended
    run = held.row
    assert run.status is TaskRunStatus.STOPPED
    assert "canopy stop --now" in json.loads(present(run.result_json))["harness"]
    assert set(pool_statuses(treehouse_state)) == {"available"}


def test_a_task_run_whose_process_died_is_crashed_by_the_next_tick(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    submits(scenario)
    [held] = scenario.tick(hold=True).tasking
    held.dies()
    scenario.tick()
    run = held.row
    assert run.status is TaskRunStatus.CRASHED
    assert json.loads(present(run.result_json))["harness"] == "the task's process is gone"
    assert set(pool_statuses(treehouse_state)) == {"available"}
    [(kind, body)] = [(m.kind, m.body) for m in tasks.messages_of(scenario.conn, 1, 10)]
    assert (kind, body) == ("report", "the task's process is gone")


def test_spend_and_health_count_task_runs_as_a_kind_of_their_own(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    git_pool: GitPool,
) -> None:
    with_events(canopy_env, "canopy-worker-private")
    submits(scenario)
    failed = {"status": "failed", "summary": "No such cache."}
    [run] = scenario.tick(task=scripted("WORKER_PRIVATE", {"RESULT": json.dumps(failed)})).tasks
    assert run.cost_usd == 0.25
    spent = json.loads(scenario.operator("spend", "--json").out)
    assert spent["totals"]["tasks"] == 0.25
    health = json.loads(scenario.operator("health", "--json").out)
    assert [(o["kind"], o["what"], o["status"], o["failed"]) for o in health["outcomes"] if o["kind"] == "tasks"] == [
        ("tasks", "task", "failed", True),
    ]
    [failure] = [f for f in health["failures"] if f["kind"] == "tasks"]
    assert (failure["id"], failure["subject"], failure["note"]) == (run.id, "1", "No such cache.")


def test_the_task_prompt(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    tmp_path: Path,
    markdown_snapshot: SnapshotAssertion,
) -> None:
    """A task's prompt, whole, so a change to its wording or to what fills it in is a diff in review."""
    submits(scenario)
    [run] = scenario.tick().tasks
    prompt = (canopy_env.state_dir / "tasks" / "runs" / f"{run.id}.prompt").read_text()
    assert prompt.replace(str(tmp_path), "<tmp>") == markdown_snapshot
