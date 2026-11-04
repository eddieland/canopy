"""A member ticket's plan, written within its epic's approved plan, which its planner reads as approved (§43)."""

import json
from pathlib import Path

from canopy.core import epics, plans
from canopy.core.vocab import RunKind, RunStatus
from tests.canopy.helpers import KEY, commands_run, epic_planned, inline_context, operator, planner_does, present
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import GitPool

PLAN = dispatches(kind=RunKind.PLAN)
TEXT = "# Plan for PROJ-1\n\n## Goal\n\nMove the store.\n\n## Epic\n\nCovers R1; provides C1.\n"
EPIC_PLAN = """\
# Epic: sessions

## Goal

Sessions survive a restart.

## Requirements

- **R1.** Sessions survive a restart of the API.

## Contracts

- **C1.** The store's read interface. Provided by B1.

## Breakdown

### B1. Move the store

- Covers: R1
- Provides: C1
- Uses: none
- Repositories: repo
- After: none
- Trivial: no

## Decisions

## Out of scope
"""


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
