"""The worker's copy of the plan (DESIGN §25, ROADMAP M44): written fresh for each run, ignored by git, and gone after.

An `implement` or `resume` for a ticket with an approved plan finds it as `.canopy-plan.md` where it starts, and its
prompt names that file and the plan's outline, never its text. `_run` checks the file against the approved hash
again before the worker starts, and a pushed branch that holds the copy gets a harness note.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import contract, db, plans, prompts
from canopy.core.vocab import RunKind, RunStatus, TickStatus
from canopy.infra import logs, procs
from canopy.runs import tidy
from tests.canopy.helpers import (
    BRANCH,
    KEY,
    InlineRunner,
    agent_runs,
    commands_run,
    commit_and_push,
    in_tick,
    planner_does,
    present,
    worker_does,
)
from tests.canopy.scenario_helpers import Ran, Scenario, dispatches
from tests.conftest import GitPool

PLAN = dispatches(kind=RunKind.PLAN)
TEXT = "# Plan for PROJ-1\n\n## repo\n\nAdd the button.\n\n```sh\n# not a heading\n```\n\n### Tests\n\nOne test.\n"


def approved(scenario: Scenario) -> int:
    """Plan PROJ-1 with TEXT and approve it; returns the plan run's id."""
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT))
    scenario.operator("plan", KEY, "--approve")
    return run.id


def test_an_implement_finds_the_approved_plan_ignored_and_it_is_gone_after(
    scenario: Scenario, git_pool: GitPool
) -> None:
    approved(scenario)
    looks = [["cat", plans.COPY], ["git", "status", "--porcelain"], ["git", "check-ignore", plans.COPY]]
    run = scenario.run(worker=worker_does(*looks, *commit_and_push(BRANCH)))
    assert run.status == RunStatus.DONE, Path(run.row["log_path"]).read_text()
    *_, (cat, status, ignored, *_) = commands_run(scenario.agent_log)
    assert cat["stdout"] == TEXT
    assert status["stdout"] == ""
    assert ignored["returncode"] == 0

    worker = agent_runs(scenario.agent_log)[-1]
    slot = Path(str(worker["cwd"]))
    prompt = run.prompt
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
    assert contract.stored_object(run.row["result_json"]).get("harness") is None


def test_without_an_approved_plan_the_prompt_has_no_plan_section(scenario: Scenario, git_pool: GitPool) -> None:
    run = scenario.run(worker=worker_does(["test", "-e", plans.COPY], *commit_and_push(BRANCH)))
    *_, [exists, *_] = commands_run(scenario.agent_log)
    assert exists["returncode"] == 1
    assert "## The plan" not in run.prompt


def dispatched_then(scenario: Scenario, between: Callable[[], object], *commands: list[str]) -> Ran:
    """Dispatch an implement of KEY, do `between`, then do its `_run`, its worker running `commands`.

    Returns:
        The run, closed.
    """
    conn, runner = scenario.conn, InlineRunner()
    with worker_does(*commands), in_tick(conn) as tick_id:
        assert main(dispatches()[1:], runner=runner) == 0
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        between()
        run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
        main(["_run", str(run_id)], runner=runner)
    return scenario.ran(present(db.get_run(conn, run_id)))


@pytest.mark.parametrize("change", ["a new plan", "approved again"])
def test_a_plan_changed_between_dispatch_and_run_is_not_the_one_the_prompt_names(
    scenario: Scenario, git_pool: GitPool, change: str
) -> None:
    conn, state_dir = scenario.conn, scenario.env.state_dir
    plan_run = approved(scenario)
    path = plans.path_for(state_dir, KEY, plan_run)

    def between() -> None:
        if change == "a new plan":
            # A new plan, approved: the prompt's outline is of the one before it. It stands as a plan run's.
            run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
            plans.record(conn, KEY, run_id, plans.write(state_dir, KEY, run_id, "# Other\n"))
        else:
            path.write_text(TEXT + "\nAnd more.\n")
        scenario.operator("plan", KEY, "--approve")

    workers_before = len(agent_runs(scenario.agent_log))
    run = dispatched_then(scenario, between, ["test", "-e", plans.COPY])
    assert run.status == RunStatus.CRASHED
    note = str(contract.stored_object(run.row["result_json"]).get("harness"))
    assert note == (
        "plan 1, which the worker's prompt names, is no longer the plan approved for PROJ-1 when the run was "
        "dispatched; the worker did not start"
    )
    assert len(agent_runs(scenario.agent_log)) == workers_before


def test_a_plan_approved_after_dispatch_is_not_copied_for_a_run_its_prompt_named_none(
    scenario: Scenario, git_pool: GitPool
) -> None:
    # With plans off, an implement may go ahead while a plan waits; the approval after it is for the next run.
    scenario.run(PLAN, worker=planner_does(plan=TEXT))
    run = dispatched_then(scenario, lambda: scenario.operator("plan", KEY, "--approve"), ["test", "-e", plans.COPY])
    *_, [exists] = commands_run(scenario.agent_log)
    assert exists["returncode"] == 1
    assert run.row["plan_id"] is None
    assert "## The plan" not in run.prompt


def test_an_edit_between_dispatch_and_run_crashes_the_run_before_the_worker(
    scenario: Scenario, git_pool: GitPool
) -> None:
    plan_run = approved(scenario)
    workers_before = len(agent_runs(scenario.agent_log))
    path = plans.path_for(scenario.env.state_dir, KEY, plan_run)
    # The edit lands after the dispatch's check and before `_run`'s.
    run = dispatched_then(scenario, lambda: path.write_text(TEXT + "\nAnd more.\n"), ["true"])
    assert run.status == RunStatus.CRASHED
    note = str(contract.stored_object(run.row["result_json"]).get("harness"))
    assert note == f"plan 1's file {path} is no longer the text the operator approved; the worker did not start"
    assert len(agent_runs(scenario.agent_log)) == workers_before


def test_a_pushed_branch_holding_the_copy_gets_a_harness_note(scenario: Scenario, git_pool: GitPool) -> None:
    approved(scenario)
    adds = [["git", "add", "-f", plans.COPY], ["git", "commit", "--quiet", "-m", "PROJ-1: with the plan"]]
    push = ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"]
    run = scenario.run(worker=worker_does(*adds, push))
    assert run.status == RunStatus.DONE
    note = contract.stored_object(run.row["result_json"]).get("harness")
    assert note == f"repo: the pushed {BRANCH} holds {plans.COPY}, the plan's copy, committed by the worker"


def test_an_override_without_plan_is_refused_once_the_ticket_has_an_approved_plan(
    scenario: Scenario, git_pool: GitPool
) -> None:
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} for {{LABELS}} with {{OPEN_PR}}\n")
    approved(scenario)
    [(action, rationale)] = scenario.refuses(dispatches())
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{PLAN}}" in rationale


def test_the_outline_is_the_headings_outside_code_bounded() -> None:
    text = "# Top\n```\n# code\n```\n~~~~\n# tilde\n~~~\n# still code\n~~~~\n## After"
    assert plans.outline(text) == ["# Top", "## After"]
    many = "\n".join(f"## {i} {'x' * 300}" for i in range(plans.MAX_OUTLINE + 5))
    found = plans.outline(many)
    assert len(found) == plans.MAX_OUTLINE
    assert {len(h) for h in found} == {plans.MAX_HEADING}
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
