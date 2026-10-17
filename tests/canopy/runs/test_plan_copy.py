"""The worker's copy of the plan (DESIGN §25, ROADMAP M44): written fresh for each run, ignored by git, and gone after.

An `implement` or `resume` for a ticket with an approved plan finds it as `.canopy-plan.md` where it starts, and its
prompt names that file and the plan's outline, never its text. `_run` checks the file against the approved hash
again before the worker starts, and a pushed branch that holds the copy gets a harness note.
"""

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import contract, db, plans, prompts
from canopy.core.vocab import RunStatus, TickStatus
from canopy.infra import logs, procs
from canopy.runs import tidy
from tests.canopy.helpers import (
    BRANCH,
    KEY,
    LABEL,
    WORK,
    InlineRunner,
    agent_runs,
    commands_run,
    commit_and_push,
    dispatch_and_run,
    dispatch_refused,
    in_tick,
    operator,
    planner_does,
    present,
    prompt_of,
    worker_does,
)
from tests.conftest import CanopyEnv, GitPool

PLAN = ("--label", LABEL, "--kind", "plan")
TEXT = "# Plan for PROJ-1\n\n## repo\n\nAdd the button.\n\n```sh\n# not a heading\n```\n\n### Tests\n\nOne test.\n"


def approved(conn: sqlite3.Connection) -> int:
    """Plan PROJ-1 with TEXT and approve it; returns the plan run's id."""
    with planner_does(plan=TEXT):
        run = dispatch_and_run(conn, *PLAN)
    assert operator("plan", KEY, "--approve") == 0
    return int(run["id"])


def test_an_implement_finds_the_approved_plan_ignored_and_it_is_gone_after(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    approved(conn)
    looks = [["cat", plans.COPY], ["git", "status", "--porcelain"], ["git", "check-ignore", plans.COPY]]
    with worker_does(*looks, *commit_and_push(BRANCH)):
        run = dispatch_and_run(conn, *WORK)
    assert run["status"] == RunStatus.DONE, Path(run["log_path"]).read_text()
    *_, (cat, status, ignored, *_) = commands_run(agent_log)
    assert cat["stdout"] == TEXT
    assert status["stdout"] == ""
    assert ignored["returncode"] == 0

    worker = agent_runs(agent_log)[-1]
    slot = Path(str(worker["cwd"]))
    prompt = prompt_of(canopy_env, int(run["id"]))
    assert f"`{slot / plans.COPY}` is the plan the operator approved" in prompt
    assert "```text\n# Plan for PROJ-1\n## repo\n### Tests\n```" in prompt
    # The outline, never the text.
    assert "Add the button." not in prompt
    # Gone before the slot went back, and the exclude line stays, once.
    assert not (slot / plans.COPY).exists()
    common = procs.SubprocessRunner().run(
        ["git", "-C", str(slot), "rev-parse", "--path-format=absolute", "--git-common-dir"]
    )
    exclude = Path(common.stdout.strip()) / "info" / "exclude"
    assert exclude.read_text().splitlines().count(f"/{plans.COPY}") == 1
    assert contract.stored_object(run["result_json"]).get("harness") is None


def test_without_an_approved_plan_the_prompt_says_none(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(["test", "-e", plans.COPY], *commit_and_push(BRANCH)):
        run = dispatch_and_run(conn, *WORK)
    *_, [exists, *_] = commands_run(agent_log)
    assert exists["returncode"] == 1
    assert "## The plan\n\nNone.\n" in prompt_of(canopy_env, int(run["id"]))


def dispatched_then(conn: sqlite3.Connection, between: Callable[[], object]) -> sqlite3.Row:
    """Dispatch an implement of KEY, do `between`, then do its `_run`; returns the run, closed."""
    runner = InlineRunner()
    with worker_does(["test", "-e", plans.COPY]), in_tick(conn) as tick_id:
        assert main(["dispatch", KEY, "--repo", "repo", *WORK], runner=runner) == 0
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        between()
        run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
        main(["_run", str(run_id)], runner=runner)
    return present(db.get_run(conn, run_id))


@pytest.mark.parametrize("change", ["a new plan", "approved again"])
def test_a_plan_changed_between_dispatch_and_run_is_not_the_one_the_prompt_names(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection, change: str
) -> None:
    plan_run = approved(conn)
    path = plans.path_for(canopy_env.state_dir, KEY, plan_run)

    def between() -> None:
        if change == "a new plan":
            # A new plan, approved: the prompt's outline is of the one before it. It stands as a plan run's.
            run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
            plans.record(conn, KEY, run_id, plans.write(canopy_env.state_dir, KEY, run_id, "# Other\n"))
        else:
            path.write_text(TEXT + "\nAnd more.\n")
        assert operator("plan", KEY, "--approve") == 0

    workers_before = len(agent_runs(agent_log))
    run = dispatched_then(conn, between)
    assert run["status"] == RunStatus.CRASHED
    note = str(contract.stored_object(run["result_json"]).get("harness"))
    assert note == (
        "plan 1, which the worker's prompt names, is no longer the plan approved for PROJ-1 when the run was "
        "dispatched; the worker did not start"
    )
    assert len(agent_runs(agent_log)) == workers_before


def test_a_plan_approved_after_dispatch_is_not_copied_for_a_run_its_prompt_named_none(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    # With plans off, an implement may go ahead while a plan waits; the approval after it is for the next run.
    with planner_does(plan=TEXT):
        dispatch_and_run(conn, *PLAN)
    run = dispatched_then(conn, lambda: operator("plan", KEY, "--approve"))
    *_, [exists] = commands_run(agent_log)
    assert exists["returncode"] == 1
    assert run["plan_id"] is None
    assert "## The plan\n\nNone.\n" in prompt_of(canopy_env, int(run["id"]))


def test_an_edit_between_dispatch_and_run_crashes_the_run_before_the_worker(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    plan_run = approved(conn)
    workers_before = len(agent_runs(agent_log))
    path = plans.path_for(canopy_env.state_dir, KEY, plan_run)
    # The edit lands after the dispatch's check and before `_run`'s.
    runner = InlineRunner()
    with worker_does(["true"]), in_tick(conn) as tick_id:
        assert main(["dispatch", KEY, "--repo", "repo", *WORK], runner=runner) == 0
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        path.write_text(TEXT + "\nAnd more.\n")
        run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
        main(["_run", str(run_id)], runner=runner)
    run = present(db.get_run(conn, run_id))
    assert run["status"] == RunStatus.CRASHED
    note = str(contract.stored_object(run["result_json"]).get("harness"))
    assert note == f"plan 1's file {path} is no longer the text the operator approved; the worker did not start"
    assert len(agent_runs(agent_log)) == workers_before


def test_a_pushed_branch_holding_the_copy_gets_a_harness_note(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    approved(conn)
    adds = [["git", "add", "-f", plans.COPY], ["git", "commit", "--quiet", "-m", "PROJ-1: with the plan"]]
    push = ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"]
    with worker_does(*adds, push):
        run = dispatch_and_run(conn, *WORK)
    assert run["status"] == RunStatus.DONE
    note = contract.stored_object(run["result_json"]).get("harness")
    assert note == f"repo: the pushed {BRANCH} holds {plans.COPY}, the plan's copy, committed by the worker"


def test_an_override_without_plan_is_refused_once_the_ticket_has_an_approved_plan(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} for {{LABELS}} with {{OPEN_PR}}\n")
    approved(conn)
    [(action, rationale)] = dispatch_refused(conn, *WORK)
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{PLAN}}" in rationale


def test_the_outline_is_the_headings_outside_code_bounded() -> None:
    text = "# Top\n```\n# code\n```\n~~~~\n# tilde\n~~~\n# still code\n~~~~\n## After"
    assert plans.outline(text) == ["# Top", "## After"]
    many = "\n".join(f"## {i} {'x' * 300}" for i in range(plans.MAX_OUTLINE + 5))
    found = plans.outline(many)
    assert len(found) == plans.MAX_OUTLINE
    assert {len(h) for h in found} == {plans.MAX_HEADING}
    assert prompts.plan_note(None, []) == "None."
    assert prompts.plan_note(Path("/d/.canopy-plan.md"), []).endswith("It has no headings: read it whole.")
    fenced = prompts.plan_note(Path("/d/.canopy-plan.md"), ["# ```odd"])
    assert "````text\n# ```odd\n````" in fenced


def test_tidying_a_slot_removes_a_copy_left_behind(tmp_path: Path) -> None:
    # A slot whose `_run` died: reconcile tidies it as `_run` would have, and the copy goes with it.
    slot = tmp_path / "slot"
    slot.mkdir()
    (slot / plans.COPY).write_text(TEXT)
    log = logs.for_tick(None)
    runner = procs.SubprocessRunner()
    assert tidy.tidy(runner, slot, link=None, base="main", objects=tmp_path / "objects", log=log, fields={})
    assert not (slot / plans.COPY).exists()
