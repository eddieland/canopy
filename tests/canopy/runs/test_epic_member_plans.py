"""A member ticket's plan and work, within its epic's approved plan, which its planner and worker read as approved."""

import json
from datetime import UTC, datetime
from pathlib import Path

from canopy.core import epics, plans
from canopy.core.vocab import PlannerApproval, PlanStatus, RunKind, RunStatus
from canopy.infra import procs
from canopy.loop import harness_items
from tests.canopy.helpers import (
    BRANCH,
    EPIC_PLAN,
    KEY,
    agent_runs,
    commands_run,
    commit_and_push,
    epic_planned,
    inline_context,
    operator,
    planner_does,
    present,
    worker_does,
)
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import GitPool

PLAN = dispatches(kind=RunKind.PLAN)
TEXT = "# Plan for PROJ-1\n\n## Goal\n\nMove the store.\n\n## Epic\n\nCovers R1; provides C1.\n"
#: `EPIC_PLAN` with a second entry, which a later approval of `EPIC_PLAN` drops.
TWO_ENTRIES = EPIC_PLAN.replace(
    "## Decisions",
    "### B2. Read from the store\n\n- Covers: R1\n- Provides: none\n- Uses: C1\n- Repositories: repo\n"
    "- After: B1\n- Trivial: no\n\n## Decisions",
)


def approved_epic(scenario: Scenario, *member: str) -> int:
    """Submit epic:1, have its plan written and approved as `EPIC_PLAN`, and register `member`: return the plan's id."""
    assert operator("epic", "submit", "Move sessions to the new store.") == 0
    epic_planned(scenario.env, EPIC_PLAN)
    assert operator("plan", "epic:1", "--approve") == 0
    assert operator("epic", "add", "epic:1", KEY, *member) == 0
    return present(epics.approved_plan(scenario.conn, 1)).id


def test_a_members_planner_reads_its_epics_approved_plan_and_its_plan_names_it(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """The planner gets the copy as approved and the entries it fulfils; its plan records the epic plan it read."""
    assert git_pool.slots
    epic_plan_id = approved_epic(scenario, "--entry", "B1")
    run = scenario.run(PLAN, worker=planner_does(["cat", epics.EPIC_COPY], plan=TEXT))
    assert run.status is RunStatus.DONE, Path(run.row["log_path"]).read_text()
    # The member's planner's command, the last: the epic's own planner ran before it.
    _, cat = commands_run(scenario.agent_log)[-1]
    assert cat["stdout"] == EPIC_PLAN
    assert "This ticket is a member of epic:1" in run.prompt
    assert "This ticket fulfils `B1` of its breakdown." in run.prompt
    [plan] = plans.history(scenario.conn, KEY)
    assert plan.epic_plan_id == epic_plan_id
    # The copy went with the desk.
    assert not (scenario.env.root / "desks" / KEY).exists()


def test_a_member_of_no_entry_is_told_to_say_what_it_takes_on(scenario: Scenario, git_pool: GitPool) -> None:
    """A ticket the breakdown did not foresee plans within the epic all the same, naming the requirements it covers."""
    assert git_pool.slots
    approved_epic(scenario, "--no-entry")
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT))
    assert run.status is RunStatus.DONE
    assert "This ticket fulfils no entry of its breakdown" in run.prompt


def test_a_ticket_of_no_epic_is_planned_as_before(scenario: Scenario, git_pool: GitPool) -> None:
    """Outside an epic, or before its plan is approved, the prompt has no epic section and the plan names none."""
    assert git_pool.slots
    assert operator("epic", "submit", "Move sessions to the new store.") == 0
    assert operator("epic", "add", "epic:1", KEY) == 0
    run = scenario.run(PLAN, worker=planner_does(["cat", epics.EPIC_COPY], plan=TEXT))
    assert run.status is RunStatus.DONE
    assert "## The epic" not in run.prompt
    [[_, cat]] = commands_run(scenario.agent_log)
    assert cat["returncode"] != 0
    [plan] = plans.history(scenario.conn, KEY)
    assert plan.epic_plan_id is None


def test_a_member_is_not_planned_from_an_epic_plan_no_longer_as_approved(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """An approved copy edited since is never handed to a planner: the run crashes, saying why, and records no plan."""
    assert git_pool.slots
    approved_epic(scenario, "--entry", "B1")
    ctx = inline_context(scenario.env)
    plan = present(epics.approved_plan(ctx.conn, 1))
    epics.approved_path(ctx.state_dir, 1, plan.run_id, present(plan.approved_sha256)).write_text("# Something else\n")
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT))
    assert run.status is RunStatus.CRASHED
    assert (
        "epic:1's approved plan is no longer as the operator approved it"
        in json.loads(run.row["result_json"])["harness"]
    )
    assert plans.history(scenario.conn, KEY) == []


def test_a_member_whose_entry_a_later_approval_dropped_is_told_so(scenario: Scenario, git_pool: GitPool) -> None:
    """A registration names the plan approved when it was made: the planner hears its entry is gone since."""
    assert git_pool.slots
    assert operator("epic", "submit", "Move sessions to the new store.") == 0
    epic_planned(scenario.env, TWO_ENTRIES)
    assert operator("plan", "epic:1", "--approve") == 0
    assert operator("epic", "add", "epic:1", KEY, "--entry", "B2") == 0
    assert operator("reply", "epic:1", "Leave the reads to the API's own ticket.") == 0
    epic_planned(scenario.env, EPIC_PLAN)
    assert operator("plan", "epic:1", "--approve") == 0
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT))
    assert run.status is RunStatus.DONE
    assert "It was registered against `B2`, which the approved plan no longer holds" in run.prompt
    assert "This ticket fulfils" not in run.prompt


def test_an_override_without_the_epic_is_refused_once_its_plan_is_approved(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """An older planner override would plan a member without telling it of the epic's plan: it fails to render."""
    assert git_pool.slots
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-plan.md").write_text(
        "Plan {{KEY}} in {{REPOSITORIES}}, {{AUTHORIZATION}}, hearing {{OPERATOR_MESSAGES}}, into {{PLAN_OUT}}\n",
    )
    scenario.seen()
    approved_epic(scenario, "--entry", "B1")
    [(action, rationale)] = scenario.refuses(PLAN)
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{EPIC}}" in rationale


def drift_items(scenario: Scenario) -> dict[str | None, str]:
    """The `epic_drift` items the harness raises now, each its ticket's detail."""
    ctx = inline_context(scenario.env)
    found = harness_items.raised(ctx, None, datetime.now(UTC))
    return {i.ticket_key: i.detail for i in found if i.reason == harness_items.EPIC_DRIFT}


def test_a_planner_that_departs_from_the_epic_raises_epic_drift_naming_the_member(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """The ids its result names are held to the epic's plan: an entry, an unknown id, or no id at all is dropped."""
    assert git_pool.slots
    approved_epic(scenario, "--entry", "B1")
    result = {"status": "done", "summary": "planned it", "drift": ["R1", "C1", "B1", "R9", "C1", "nonsense"]}
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT, result=result))
    assert run.status is RunStatus.DONE
    assert '`drift` too, as `["R2", "C1"]`' in run.prompt
    [plan] = plans.history(scenario.conn, KEY)
    assert plan.epic_drift == "C1, R1"
    assert json.loads(run.row["result_json"])["drift"] == ["C1", "R1"]
    assert drift_items(scenario) == {
        KEY: (
            f"plan {plan.id} of {KEY} departs from epic:1's C1, R1: approve it as written (canopy plan {KEY} "
            f"--approve), or ask for a new plan of either (canopy reply {KEY}, canopy reply epic:1)"
        ),
    }


def test_a_planner_that_keeps_to_the_epic_raises_none(scenario: Scenario, git_pool: GitPool) -> None:
    """No drift, or only ids the epic's plan does not hold, records none and raises nothing."""
    assert git_pool.slots
    approved_epic(scenario, "--entry", "B1")
    result = {"status": "done", "summary": "planned it", "drift": ["R7", "B1"]}
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT, result=result))
    assert run.status is RunStatus.DONE
    [plan] = plans.history(scenario.conn, KEY)
    assert plan.epic_drift is None
    assert drift_items(scenario) == {}


def test_a_ticket_of_no_epic_is_not_asked_for_drift(scenario: Scenario, git_pool: GitPool) -> None:
    """Outside an epic there is no plan to depart from: its result tool takes no `drift`, and refuses one."""
    assert git_pool.slots
    result = {"status": "done", "summary": "planned it", "drift": ["R1"]}
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT, result=result))
    assert run.status is RunStatus.UNKNOWN
    assert "drift" not in run.prompt
    assert plans.history(scenario.conn, KEY) == []


def test_a_plan_that_departs_waits_on_the_operator_though_its_planner_says_it_needs_no_review(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """Only the operator settles a departure: `policy.planner_may_approve` does not approve such a plan."""
    assert git_pool.slots
    scenario.configures("private", policy={"planner_may_approve": True})
    approved_epic(scenario, "--entry", "B1")
    result = {
        "status": "done",
        "summary": "planned it",
        "review": "not_needed",
        "review_reason": "Small.",
        "drift": ["C1"],
    }
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT, result=result))
    assert run.status is RunStatus.DONE
    [plan] = plans.history(scenario.conn, KEY)
    assert (plan.status, plan.approved_channel) == (PlanStatus.PROPOSED, None)
    assert KEY in drift_items(scenario)


def test_a_members_worker_reads_its_epics_approved_plan_ignored_and_gone_after(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """An `implement` finds the copy at its worktree's root, ignored by git, and the slot goes back without it."""
    assert git_pool.slots
    approved_epic(scenario, "--entry", "B1")
    looks = [["cat", epics.EPIC_COPY], ["git", "status", "--porcelain"], ["git", "check-ignore", epics.EPIC_COPY]]
    run = scenario.run(worker=worker_does(*looks, *commit_and_push(BRANCH)))
    assert run.status is RunStatus.DONE, Path(run.row["log_path"]).read_text()
    *_, (cat, status, ignored, *_) = commands_run(scenario.agent_log)
    assert cat["stdout"] == EPIC_PLAN
    assert status["stdout"] == ""
    assert ignored["returncode"] == 0
    assert "This ticket is a member of epic:1" in run.prompt
    assert "This ticket fulfils `B1` of its breakdown." in run.prompt
    # The copy, never the text.
    assert "The store's read interface." not in run.prompt
    slot = Path(str(agent_runs(scenario.agent_log)[-1]["cwd"]))
    assert not (slot / epics.EPIC_COPY).exists()
    common = procs.SubprocessRunner().run(
        ["git", "-C", str(slot), "rev-parse", "--path-format=absolute", "--git-common-dir"],
    )
    exclude = Path(common.stdout.strip()) / "info" / "exclude"
    assert exclude.read_text().splitlines().count(f"/{epics.EPIC_COPY}") == 1


def test_a_worker_outside_an_epic_has_no_epic_section_and_no_copy(scenario: Scenario, git_pool: GitPool) -> None:
    """Before the epic's plan is approved, a member's worker works as any ticket's: no section, no file."""
    assert git_pool.slots
    assert operator("epic", "submit", "Move sessions to the new store.") == 0
    assert operator("epic", "add", "epic:1", KEY) == 0
    run = scenario.run(worker=worker_does(["test", "-e", epics.EPIC_COPY], *commit_and_push(BRANCH)))
    assert run.status is RunStatus.DONE
    assert "## The epic" not in run.prompt
    *_, [exists, *_] = commands_run(scenario.agent_log)
    assert exists["returncode"] != 0


def test_a_pushed_branch_holding_the_epic_copy_is_named(scenario: Scenario, git_pool: GitPool) -> None:
    """Ignored is not untrackable: a worker that adds the copy by name gets a harness note, and the branch stays."""
    assert git_pool.slots
    approved_epic(scenario, "--entry", "B1")
    adds = ["git", "add", "--force", epics.EPIC_COPY]
    run = scenario.run(worker=worker_does(adds, *commit_and_push(BRANCH)))
    harness = json.loads(run.row["result_json"])["harness"]
    assert f"the pushed {BRANCH} holds {epics.EPIC_COPY}, the epic plan's copy, committed by the worker" in harness


def test_a_member_is_not_worked_from_an_epic_plan_no_longer_as_approved(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """An approved copy edited since is never handed to a worker: the run crashes, saying why, before it starts."""
    assert git_pool.slots
    approved_epic(scenario, "--entry", "B1")
    ctx = inline_context(scenario.env)
    plan = present(epics.approved_plan(ctx.conn, 1))
    epics.approved_path(ctx.state_dir, 1, plan.run_id, present(plan.approved_sha256)).write_text("# Something else\n")
    run = scenario.run(worker=worker_does(*commit_and_push(BRANCH)))
    assert run.status is RunStatus.CRASHED
    harness = json.loads(run.row["result_json"])["harness"]
    assert "epic:1's approved plan is no longer as the operator approved it; its agent did not start" in harness
    # Only the epic's planner ran: the worker never started.
    assert len(agent_runs(scenario.agent_log)) == 1


def test_a_worker_override_without_the_epic_is_refused_once_its_plan_is_approved(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """An older implement override would build a member without the epic's contracts: it fails to render."""
    assert git_pool.slots
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Implement {{KEY}}, checking {{LABELS}}\n")
    scenario.seen()
    approved_epic(scenario, "--entry", "B1")
    [(action, rationale)] = scenario.refuses(dispatches())
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{EPIC}}" in rationale


#: `EPIC_PLAN` with `B1` marked trivial, which skips its member's own plan under `policy.plan`.
TRIVIAL = EPIC_PLAN.replace("- Trivial: no", "- Trivial: yes, a one-line config change")


def plans_by_approval(scenario: Scenario, *, planner_may_approve: bool = True) -> None:
    """Every implement waits on a plan the operator approves, and planners may say one needs no review."""
    scenario.configures("workspace", policy={"plan": "approve"})
    scenario.configures("private", policy={"planner_may_approve": planner_may_approve})


def trivial_epic(scenario: Scenario, plan: str = TRIVIAL) -> None:
    """Submit epic:1, have its plan written and approved as `plan`, and register KEY against `B1`."""
    scenario.operator("epic", "submit", "Move sessions to the new store.")
    epic_planned(scenario.env, plan)
    scenario.operator("plan", "epic:1", "--approve")
    scenario.operator("epic", "add", "epic:1", KEY, "--entry", "B1")


def test_a_trivial_member_is_implemented_on_its_epics_approval_alone(scenario: Scenario, git_pool: GitPool) -> None:
    """The epic's plan marks its entry trivial: no plan of its own is needed, and its implement follows the epic's."""
    assert git_pool.slots
    plans_by_approval(scenario)
    trivial_epic(scenario)
    assert epics.trivial(scenario.conn, scenario.env.state_dir, KEY, PlannerApproval.STRICT) == (
        "B1: a one-line config change"
    )
    scenario.seen()
    shown = scenario.operator("show", KEY)
    assert "Plan: not needed, by its epic's approved plan, which marks it trivial (B1: a one-line config change)" in (
        shown.out
    )

    run = scenario.run(worker=worker_does(["cat", epics.EPIC_COPY], *commit_and_push(BRANCH)))
    assert run.status is RunStatus.DONE, Path(run.row["log_path"]).read_text()
    assert "This ticket is a member of epic:1" in run.prompt
    assert "## The plan" not in run.prompt
    *_, (cat, *_) = commands_run(scenario.agent_log)
    assert cat["stdout"] == TRIVIAL
    assert plans.history(scenario.conn, KEY) == []


def test_a_member_is_never_trivial_with_planner_approval_off(scenario: Scenario, git_pool: GitPool) -> None:
    """With `planner_may_approve` off, a trivial mark counts for nothing: its implement waits on a plan."""
    assert git_pool.slots
    plans_by_approval(scenario, planner_may_approve=False)
    trivial_epic(scenario)
    [(action, rationale), *_] = scenario.refuses(dispatches())
    assert action == "refused:unplanned"
    assert f"{KEY} needs a plan before its implement" in rationale


def test_a_member_that_asked_for_a_plan_is_never_trivial(scenario: Scenario, git_pool: GitPool) -> None:
    """The operator's own word for the ticket, `canopy plan KEY`, comes before the epic's mark."""
    assert git_pool.slots
    plans_by_approval(scenario)
    trivial_epic(scenario)
    scenario.seen()
    scenario.operator("plan", KEY)
    [(action, _), *_] = scenario.refuses(dispatches())
    assert action == "refused:unplanned"


def test_a_re_approval_that_no_longer_marks_it_trivial_plans_it_and_one_that_does_approves_it_again(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """Read from the plan as approved now: unmarked, the member waits on its own plan; marked again, it goes ahead."""
    assert git_pool.slots
    plans_by_approval(scenario)
    trivial_epic(scenario)
    scenario.operator("reply", "epic:1", "B1 touches the session schema after all.")
    epic_planned(scenario.env, EPIC_PLAN)
    scenario.operator("plan", "epic:1", "--approve")
    [(action, _), *_] = scenario.refuses(dispatches())
    assert action == "refused:unplanned"

    scenario.operator("reply", "epic:1", "It does not: the schema stays.")
    epic_planned(scenario.env, TRIVIAL)
    scenario.operator("plan", "epic:1", "--approve")
    assert scenario.run(worker=worker_does(*commit_and_push(BRANCH))).status is RunStatus.DONE
