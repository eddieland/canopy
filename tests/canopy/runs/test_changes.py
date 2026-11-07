"""What a worker's or a task's run changed, recorded and kept as it ends (DESIGN §45), against real git in its slots.

Each repository's range, the commit the run started from, the one it left on origin, and the merge base, is a row;
the run's own change and the branch against its base are diffs beside its log. An unpushed slot keeps the diff of the
last commit the run made there, a crashed run keeps nothing, and a kick after the push leaves what was kept as it was.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest import mock

from canopy.cli.main import main
from canopy.core import db, review_diff, run_changes
from canopy.core.vocab import ResumeReason, RunKind, RunStatus
from canopy.infra import logs
from canopy.loop import gc_pass
from canopy.runs import changes, checkpoint, task_starts, tasks
from tests.canopy.helpers import (
    WORKER_DONE,
    InlineRunner,
    context,
    in_tick,
    inline_context,
    present,
    private_worker_does,
    worker_does,
)
from tests.canopy.scenario_helpers import dispatches
from tests.conftest import executable, git

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core import records
    from tests.canopy.conftest import Ws
    from tests.canopy.scenario_helpers import Ran, Scenario
    from tests.conftest import CanopyEnv, GitPool

BRANCH = "agent/PROJ-1-work"
#: The branch task 1 works on, under the test operator's `agent/` prefix.
TASK_BRANCH = "agent/task/1"


def writes(name: str, text: str, *, repo: str | None = None) -> list[list[str]]:
    """The commands a worker runs to write `name` and commit it, in `repo` of a joint run's desk when it names one."""
    where = ["-C", repo] if repo is not None else []
    path = f"{repo}/{name}" if repo is not None else name
    return [
        ["sh", "-c", f"printf '%s\\n' '{text}' > {path}"],
        ["git", *where, "add", name],
        ["git", *where, "commit", "--quiet", "-m", f"PROJ-1: {name}"],
    ]


def push(branch: str = BRANCH, *, repo: str | None = None) -> list[str]:
    """The command a worker runs to push its HEAD to `branch`."""
    return [
        "git",
        *(["-C", repo] if repo is not None else []),
        "push",
        "--quiet",
        "origin",
        f"HEAD:refs/heads/{branch}",
    ]


def changed(scenario: Scenario, ran: Ran) -> list[records.RunChange]:
    """What the run recorded it changed, by repository."""
    return run_changes.of_run(scenario.conn, ran.id)


def change_of(ran: Ran, repo: str = "repo") -> str:
    """The diff the run kept of its own change to `repo`."""
    return run_changes.change_path(ran.row["log_path"], repo).read_text()


def branch_of(ran: Ran, repo: str = "repo") -> str:
    """The diff the run kept of its branch in `repo` against its base."""
    return review_diff.run_path_for(ran.row["log_path"], repo).read_text()


def main_head(origin: Path) -> str:
    return git("rev-parse", "refs/heads/main", cwd=origin)


def test_an_implement_records_the_bases_commit_origins_head_and_the_merge_base_and_keeps_both_diffs(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    base = main_head(git_pool.origin)
    ran = scenario.run(worker=worker_does(*writes("a.txt", "the change"), push()))
    head = present(git_pool.remote_head(BRANCH))
    [row] = changed(scenario, ran)
    assert (row.start_sha, row.start_on_base, row.end_sha, row.merge_base_sha) == (base, True, head, base)
    assert (row.unpushed_sha, row.change_kept, row.branch_kept, row.missing) == (None, True, True, None)
    assert change_of(ran).startswith("diff --git a/a.txt b/a.txt\n")
    assert "+the change\n" in change_of(ran)
    assert branch_of(ran) == change_of(ran)
    assert review_diff.read_head(review_diff.run_path_for(ran.row["log_path"], "repo")) == head
    assert (row.files_changed, row.lines_added, row.lines_removed) == (1, 1, 0)
    [counted] = run_changes.files_of(scenario.conn, ran.id, "repo")
    assert (counted.path, counted.old_path, counted.added, counted.removed) == ("a.txt", None, 1, 0)
    shown = scenario.operator("show", f"run:{ran.id}").out
    assert f"\nChanged:\n  repo  {base[:12]}..{head[:12]}, from its base, merge base {base[:12]}\n" in shown
    assert f"\n    its change {run_changes.change_path(ran.row['log_path'], 'repo')}\n" in shown
    assert f"\n    against its base {review_diff.run_path_for(ran.row['log_path'], 'repo')}\n" in shown


def test_a_resume_starts_from_origins_previous_head_and_its_own_diff_holds_the_fix_alone(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    base = main_head(git_pool.origin)
    scenario.run(worker=worker_does(*writes("a.txt", "the change"), push()))
    before = present(git_pool.remote_head(BRANCH))
    scenario.time_passes(minutes=31)
    fixes = worker_does(*writes("b.txt", "the fix"), push())
    ran = scenario.run(dispatches(kind=RunKind.RESUME, reasons=(ResumeReason.CI,)), worker=fixes)
    after = present(git_pool.remote_head(BRANCH))
    [row] = changed(scenario, ran)
    assert (row.start_sha, row.start_on_base, row.end_sha, row.merge_base_sha) == (before, False, after, base)
    assert "b.txt" in change_of(ran)
    assert "a.txt" not in change_of(ran)
    # Counted of the run's own change alone.
    assert [f.path for f in run_changes.files_of(scenario.conn, ran.id, "repo")] == ["b.txt"]
    assert ("a.txt" in branch_of(ran), "b.txt" in branch_of(ran)) == (True, True)
    # For a pager: the run's own change, as git printed it.
    printed = scenario.operator("show", f"run:{ran.id}", "--diff").out
    assert printed == change_of(ran)
    shown = scenario.operator("show", f"run:{ran.id}").out
    assert f"  repo  {before[:12]}..{after[:12]}, merge base {base[:12]}\n" in shown


def test_a_joint_run_records_a_row_and_its_diffs_per_repository(ws_scenario: Scenario, ws: Ws) -> None:
    repos = ("api", "web")
    commands = [c for name in repos for c in (*writes(f"{name}.txt", name, repo=name), push(repo=name))]
    result = json.loads(WORKER_DONE) | {"prs": {name: f"https://example.test/{name}/pr/1" for name in repos}}
    del result["pr"]
    ran = ws_scenario.run(dispatches(repo=repos), worker=worker_does(*commands, result=json.dumps(result)))
    rows = changed(ws_scenario, ran)
    assert [(r.repo, r.end_sha, r.change_kept, r.branch_kept) for r in rows] == [
        (name, ws.remote_head(name, BRANCH), True, True) for name in repos
    ]
    assert [r.start_sha for r in rows] == [main_head(ws.origins[name]) for name in repos]
    for name, other in (repos, reversed(repos)):
        assert f"+{name}\n" in change_of(ran, name)
        assert f"{other}.txt" not in change_of(ran, name)
    # A joint run's diffs are each headed with their repository's range.
    printed = ws_scenario.operator("show", f"run:{ran.id}", "--diff").out
    assert printed.startswith(f"# api: {present(rows[0].start_sha)[:12]}..")
    assert "\n# web: " in printed


def test_a_task_run_records_its_range_and_keeps_its_diffs(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    git_pool: GitPool,
) -> None:
    base = main_head(git_pool.origin)
    scenario.operator("task", "submit", "Find out why the build is slow, and push a fix if one is small.")
    ctx = inline_context(canopy_env)
    with in_tick(ctx.conn) as tick_id:
        [started] = task_starts.start_queued(ctx, tick_id, logs.for_tick(tick_id))
    done: dict[str, object] = {"status": "done", "summary": "fixed", "branch": TASK_BRANCH, "prs": []}
    with private_worker_does(*writes("fix.txt", "the fix"), push(TASK_BRANCH), result=done):
        assert main(["_task", str(started.run_id)], runner=InlineRunner()) == 0
    run = present(tasks.get_run(ctx.conn, started.run_id))
    head = present(git_pool.remote_head(TASK_BRANCH))
    [row] = run_changes.of_run(ctx.conn, run.id, table="task_runs")
    assert (row.task_run_id, row.run_id, row.start_sha, row.end_sha) == (run.id, None, base, head)
    assert (row.start_on_base, row.merge_base_sha, row.change_kept, row.branch_kept) == (True, base, True, True)
    assert "+the fix\n" in run_changes.change_path(run.log_path, "repo").read_text()
    shown = scenario.operator("show", "task:1").out
    assert f"\n    changed:\n      repo  {base[:12]}..{head[:12]}, from its base, merge base {base[:12]}\n" in shown
    assert "+the fix\n" in scenario.operator("show", "task:1", "--diff").out


def test_an_unpushed_run_keeps_the_diff_of_what_it_committed_marked_as_not_on_origin(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    base = main_head(git_pool.origin)
    git_pool.reject_pushes()
    ran = scenario.run(worker=worker_does(*writes("a.txt", "the change")))
    assert ran.status is RunStatus.UNPUSHED
    [row] = changed(scenario, ran)
    assert (row.start_sha, row.end_sha, row.merge_base_sha) == (base, None, base)
    left = present(row.unpushed_sha)
    assert (row.change_kept, row.branch_kept) == (True, True)
    assert "+the change\n" in change_of(ran)
    shown = scenario.operator("show", f"run:{ran.id}").out
    marked = "; not on origin: the run left it unpushed"
    assert f"  repo  {base[:12]}..{left[:12]}, from its base, merge base {base[:12]}{marked}\n" in shown
    printed = scenario.operator("show", f"run:{ran.id}", "--diff").out
    assert printed.startswith(f"# repo: {base[:12]}..{left[:12]}, not on origin")


def test_a_run_that_moved_head_back_off_its_commits_keeps_the_last_of_them(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    base = main_head(git_pool.origin)
    leaves = worker_does(
        *writes("a.txt", "first"),
        *writes("b.txt", "second"),
        ["git", "checkout", "--quiet", "--detach", base],
    )
    ran = scenario.run(worker=leaves)
    assert ran.status is RunStatus.UNPUSHED
    assert git_pool.remote_head(BRANCH) is None
    [row] = changed(scenario, ran)
    assert row.unpushed_sha is not None
    assert ("+first\n" in change_of(ran), "+second\n" in change_of(ran)) == (True, True)


def test_a_joint_run_with_one_push_refused_marks_that_repository_alone(ws_scenario: Scenario, ws: Ws) -> None:
    executable(ws.origins["web"] / "hooks" / "pre-receive", "#!/bin/sh\necho 'refused' >&2\nexit 1\n")
    repos = ("api", "web")
    commands = [c for name in repos for c in writes(f"{name}.txt", name, repo=name)]
    ran = ws_scenario.run(dispatches(repo=repos), worker=worker_does(*commands))
    assert ran.status is RunStatus.UNPUSHED
    api, web = changed(ws_scenario, ran)
    assert (api.repo, api.unpushed_sha, api.end_sha) == ("api", None, ws.remote_head("api", BRANCH))
    assert (web.repo, web.end_sha) == ("web", None)
    assert web.unpushed_sha is not None
    assert "+web\n" in change_of(ran, "web")


def test_a_crashed_run_keeps_nothing_and_the_journal_says_so(scenario: Scenario, git_pool: GitPool) -> None:
    for slot in git_pool.slots:
        git("remote", "set-url", "origin", str(git_pool.origin.parent / "gone.git"), cwd=slot)
    ran = scenario.run()
    assert ran.status is RunStatus.CRASHED
    [row] = changed(scenario, ran)
    assert (row.start_sha, row.end_sha, row.change_kept, row.branch_kept) == (None, None, False, False)
    assert row.missing == run_changes.CRASHED
    assert not run_changes.change_path(ran.row["log_path"], "repo").exists()
    shown = scenario.operator("show", f"run:{ran.id}").out
    assert f"\nChanged:\n  repo  nothing read: {run_changes.CRASHED}\n" in shown
    refused = scenario.operator("show", f"run:{ran.id}", "--diff", code=1)
    assert f"kept no diff of its change to repo: {run_changes.CRASHED}" in refused.err


def test_a_diff_that_cannot_be_kept_leaves_the_run_as_it_is_and_the_journal_says_why(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    del git_pool
    with mock.patch.object(review_diff, "keep", autospec=True, side_effect=OSError("No space left on device")):
        ran = scenario.run(worker=worker_does(*writes("a.txt", "the change"), push()))
    assert ran.status is RunStatus.DONE
    [row] = changed(scenario, ran)
    assert (row.change_kept, row.branch_kept) == (False, False)
    assert row.missing == ("its own change: No space left on device; the branch against main: No space left on device")
    assert "  not kept: its own change: No space left on device;" in scenario.operator("show", f"run:{ran.id}").out


def test_a_kicked_run_keeps_what_it_left_before_the_kick(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"max_flaky_kicks": 1})
    scenario.run(worker=worker_does(*writes("a.txt", "the change"), push()))
    before = present(git_pool.remote_head(BRANCH))
    moves = git_pool.slots[1]
    git("fetch", "--quiet", "origin", cwd=moves)
    git("checkout", "--quiet", "--detach", "origin/main", cwd=moves)
    git("commit", "--quiet", "--allow-empty", "-m", "main moves", cwd=moves)
    git("push", "--quiet", "origin", "HEAD:refs/heads/main", cwd=moves)
    scenario.time_passes(minutes=31)
    flaky = json.loads(WORKER_DONE) | {"branch": BRANCH, "summary": "unit-tests lost its runner", "flaky": True}
    resume = dispatches(kind=RunKind.RESUME, reasons=(ResumeReason.CI,))
    ran = scenario.run(resume, worker=worker_does(result=json.dumps(flaky)))
    assert json.loads(ran.row["result_json"])["kicked"] == ["repo"]
    assert git_pool.remote_head(BRANCH) != before
    [row] = changed(scenario, ran)
    assert (row.start_sha, row.end_sha) == (before, before)
    assert change_of(ran) == ""
    assert review_diff.read_head(review_diff.run_path_for(ran.row["log_path"], "repo")) == before
    assert "a.txt" in branch_of(ran)


def test_the_diffs_go_with_run_files_days_and_the_rows_stay(scenario: Scenario, git_pool: GitPool) -> None:
    del git_pool
    ran = scenario.run(worker=worker_does(*writes("a.txt", "the change"), push()))
    kept = run_changes.files(ran.row["log_path"], ["repo"])
    assert all(p.is_file() for p in kept)
    scenario.time_passes(hours=24 * 31)
    ctx = context(scenario.env)
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    assert gc_pass.run(ctx, tick_id, logs.for_tick(tick_id)) is not None
    assert not any(p.exists() for p in kept)
    [row] = changed(scenario, ran)
    assert (row.change_kept, row.branch_kept) == (True, True)
    shown = scenario.operator("show", f"run:{ran.id}").out
    assert f"    its change {kept[0]}, since removed\n" in shown


def test_a_diff_is_read_no_further_than_canopy_keeps_it(scenario: Scenario, git_pool: GitPool) -> None:
    del git_pool
    read = checkpoint.Git.result
    with (
        mock.patch.object(review_diff, "MAX_BYTES", 99),
        mock.patch.object(review_diff, "KEPT_CHARS", 100),
        mock.patch.object(checkpoint.Git, "result", autospec=True, side_effect=read) as git_ran,
    ):
        ran = scenario.run(worker=worker_does(*writes("a.txt", "x" * 500), push()))
        printed = scenario.operator("show", f"run:{ran.id}", "--diff")
    diffs = [c for c in git_ran.call_args_list if c.args[1] == "diff" and "--no-color" in c.args]
    assert [c.kwargs["max_stdout"] for c in diffs] == [100, 100]
    assert len(change_of(ran)) == 100
    assert f"run:{ran.id}'s diff of repo is cut where canopy's bounds end" in printed.err


def test_the_end_is_the_head_the_push_check_read_though_someone_pushes_after_it(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    keep = changes.keep
    other = git_pool.slots[1]

    def a_coworker_pushes_first(
        slot_git: checkpoint.Git,
        *,
        repo: str,
        base: str,
        branch: str,
        start: checkpoint.Start,
        pushed: checkpoint.Pushed,
        log_path: str | Path,
        log: logs.TickAdapter,
    ) -> run_changes.Change:
        git("fetch", "--quiet", "origin", cwd=other)
        git("checkout", "--quiet", "--detach", f"origin/{BRANCH}", cwd=other)
        git("commit", "--quiet", "--allow-empty", "-m", "a coworker", cwd=other)
        git("push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=other)
        return keep(
            slot_git,
            repo=repo,
            base=base,
            branch=branch,
            start=start,
            pushed=pushed,
            log_path=log_path,
            log=log,
        )

    with mock.patch.object(changes, "keep", autospec=True, side_effect=a_coworker_pushes_first):
        ran = scenario.run(worker=worker_does(*writes("a.txt", "the change"), push()))
    moved = present(git_pool.remote_head(BRANCH))
    [row] = changed(scenario, ran)
    assert row.end_sha == git("rev-parse", f"{moved}^", cwd=git_pool.origin)
    assert review_diff.read_head(review_diff.run_path_for(ran.row["log_path"], "repo")) == row.end_sha


def test_a_merge_base_git_could_not_find_is_recorded_as_git_said(scenario: Scenario, git_pool: GitPool) -> None:
    del git_pool
    forgets_main = ["git", "update-ref", "-d", "refs/remotes/origin/main"]
    ran = scenario.run(worker=worker_does(*writes("a.txt", "the change"), push(), forgets_main))
    [row] = changed(scenario, ran)
    assert (row.change_kept, row.branch_kept) == (True, False)
    assert present(row.missing).startswith("the branch against main: git merge-base exited 128: ")
    assert "no merge base" not in present(row.missing)


def test_a_tasks_diff_passes_over_a_newer_run_that_kept_none_for_the_older_one_that_did(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    git_pool: GitPool,
) -> None:
    scenario.operator("task", "submit", "Find out why the build is slow, and push a fix if one is small.")
    ctx = inline_context(canopy_env)
    with in_tick(ctx.conn) as tick_id:
        [first] = task_starts.start_queued(ctx, tick_id, logs.for_tick(tick_id))
    asks: dict[str, object] = {
        "status": "blocked",
        "summary": "a fix",
        "branch": TASK_BRANCH,
        "question": "Keep going?",
    }
    with private_worker_does(*writes("fix.txt", "the fix"), push(TASK_BRANCH), result=asks):
        assert main(["_task", str(first.run_id)], runner=InlineRunner()) == 0
    scenario.operator("reply", "task:1", "Yes.")
    with in_tick(ctx.conn) as tick_id:
        [second] = task_starts.start_queued(ctx, tick_id, logs.for_tick(tick_id))
    for slot in git_pool.slots:
        git("remote", "set-url", "origin", str(git_pool.origin.parent / "gone.git"), cwd=slot)
    main(["_task", str(second.run_id)], runner=InlineRunner())
    [crashed] = run_changes.of_run(ctx.conn, second.run_id, table="task_runs")
    assert crashed.missing == run_changes.CRASHED
    printed = scenario.operator("show", "task:1", "--diff")
    assert "+the fix\n" in printed.out
    assert printed.err == ""
