"""A member ticket's plan, written within its epic's approved plan, which its planner reads as approved (§43)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from canopy.core import epics, plans
from canopy.core.vocab import PlanStatus, RunKind, RunStatus
from canopy.loop import harness_items
from tests.canopy.helpers import (
    EPIC_PLAN,
    KEY,
    commands_run,
    epic_planned,
    inline_context,
    operator,
    planner_does,
    present,
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
    result = {"status": "done", "summary": "planned it", "drift": ["R1", "C1", "B1", "R9", "C1", "nonsense", 3]}
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT, result=result))
    assert run.status is RunStatus.DONE
    assert '`"drift":["R2","C1"]`' in run.prompt
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


def test_a_ticket_of_no_epic_keeps_no_drift(scenario: Scenario, git_pool: GitPool) -> None:
    """Outside an epic there is no plan to depart from: what its planner names is dropped."""
    assert git_pool.slots
    result = {"status": "done", "summary": "planned it", "drift": ["R1"]}
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT, result=result))
    assert run.status is RunStatus.DONE
    [plan] = plans.history(scenario.conn, KEY)
    assert plan.epic_drift is None


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
