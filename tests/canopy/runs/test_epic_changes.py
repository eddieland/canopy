"""When an epic's plan changes (DESIGN §43): each member it reaches met where it stands, and the operator told once."""

import json

from canopy.core import epic_changes, plans
from canopy.core.vocab import PlanStatus, RunKind, RunStatus
from canopy.notify import message
from tests.canopy.helpers import KEY, epic_planned, planner_does, present
from tests.canopy.scenario_helpers import Printed, Scenario, dispatches, pushes
from tests.conftest import GitPool

#: A second member, which fulfils `B1`.
OTHER = "PROJ-2"
PLAN = dispatches(kind=RunKind.PLAN)
IMPLEMENT = dispatches(slug="work")
TEXT = "# Plan for PROJ-1\n\n## Goal\n\nRead sessions from the store.\n\n## Epic\n\nCovers R2; uses C1.\n"
EPIC_PLAN = """\
# Epic: sessions

## Goal

Sessions survive a restart.

## Requirements

- **R1.** Sessions survive a restart of the API.
- **R2.** The API reads sessions from the store.

## Contracts

- **C1.** The store's read interface. Provided by B1, used by B2.

## Breakdown

### B1. Move the store

- Covers: R1
- Provides: C1
- Uses: none
- Repositories: repo
- After: none
- Trivial: no

### B2. Read from the store

- Covers: R2
- Provides: none
- Uses: C1
- Repositories: repo
- After: B1
- Trivial: no

## Decisions

## Out of scope
"""
#: `EPIC_PLAN` with its contract's text changed: it reaches `B1`, which provides it, and `B2`, which uses it.
C1_CHANGED = EPIC_PLAN.replace("The store's read interface.", "The store's read and write interface.")
#: `C1_CHANGED` with `R1`'s text changed too: it reaches `B1` alone.
R1_CHANGED = C1_CHANGED.replace("a restart of the API.", "a restart of the API and of its workers.")


def approved_epic(scenario: Scenario, *members: tuple[str, str]) -> None:
    """Submit epic:1, have its plan written and approved as `EPIC_PLAN`, and register each (key, entry) of `members`."""
    scenario.operator("epic", "submit", "Move sessions to the new store.")
    epic_planned(scenario.env, EPIC_PLAN)
    scenario.operator("plan", "epic:1", "--approve")
    for key, entry in members:
        scenario.operator("epic", "add", "epic:1", key, "--entry", entry)


def approved_again(scenario: Scenario, plan: str, reply: str = "The store is written to as well.") -> Printed:
    """The operator asks for epic:1's next plan in `reply`, its planner writes `plan`, and they approve it.

    Returns:
        What the approval printed.
    """
    scenario.operator("reply", "epic:1", reply)
    epic_planned(scenario.env, plan)
    return scenario.operator("plan", "epic:1", "--approve")


def test_a_proposed_plan_a_change_reaches_is_stale_and_its_next_plan_is_told_once(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """The plan waiting is superseded, naming the ids; the next planner hears them, and the one after does not."""
    assert git_pool.slots
    scenario.configures(notify={"sinks": {"slack": {"cmd": "true", "events": ["runs"]}}})
    approved_epic(scenario, (KEY, "B2"))
    assert scenario.run(PLAN, worker=planner_does(plan=TEXT)).status is RunStatus.DONE

    approved = approved_again(scenario, C1_CHANGED)
    assert "  changed: C1\n" in approved.out
    assert f"Plans superseded as stale, to be planned again: {KEY}\n" in approved.out
    [stale] = plans.history(scenario.conn, KEY)
    assert (stale.status, stale.epic_changed_ids) == (PlanStatus.SUPERSEDED, "C1")
    assert present(epic_changes.pending(scenario.conn, KEY)).ids == ["C1"]
    assert "changed since: C1" in scenario.operator("show", "epic:1").out

    # The operator hears once, naming the members each way, and nothing of the plan's text.
    [row] = scenario.conn.execute("SELECT fields FROM notify_events WHERE kind = 'epic.changed'").fetchall()
    fields = json.loads(str(row["fields"]))
    assert fields == {"epic": 1, "plan": 2, "ids": ["C1"], "count": 1, "stale": [KEY], "held": [], "told": []}
    assert message.event_line("epic.changed", fields) == (
        f"? epic:1 plan 2 changed C1; plan stale, planned again: {KEY}: canopy show epic:1"
    )
    assert message.event_page("http://ui/", "epic.changed", fields) == "http://ui/epics/1"

    again = scenario.run(PLAN, worker=planner_does(plan=TEXT))
    assert again.status is RunStatus.DONE
    assert "The operator approved the epic's plan again since this ticket was last planned" in again.prompt
    assert "changing `C1`: the copy is the plan as approved now" in again.prompt
    assert epic_changes.pending(scenario.conn, KEY) is None
    third = scenario.run(PLAN, worker=planner_does(plan=TEXT + "\nAnd a test.\n"))
    assert "approved the epic's plan again" not in third.prompt


def test_an_approved_plans_implement_waits_until_the_operator_approves_it_again(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """`epic_changed` refuses the implement in code; the operator's approval, as the file stands, lets it go ahead."""
    assert git_pool.slots
    approved_epic(scenario, (KEY, "B2"))
    assert scenario.run(PLAN, worker=planner_does(plan=TEXT)).status is RunStatus.DONE
    scenario.operator("plan", KEY, "--approve")

    approved = approved_again(scenario, C1_CHANGED)
    assert (
        f"Implements held until you approve the plan again or ask for a new one (epic_changed): {KEY}" in approved.out
    )
    [plan] = plans.history(scenario.conn, KEY)
    assert plan.status is PlanStatus.APPROVED
    [(action, rationale), *_] = scenario.refuses(IMPLEMENT)
    assert action == "refused:epic_changed"
    assert f"epic:1's plan changed C1 since plan {plan.id} of {KEY} was approved" in rationale

    # The file is as it was: approving it again is the operator's word that it still fits the epic's plan.
    scenario.operator("plan", KEY, "--approve")
    assert epic_changes.pending(scenario.conn, KEY) is None
    assert scenario.run(IMPLEMENT, worker=pushes()).status is RunStatus.DONE


def test_asking_for_a_new_plan_lifts_the_hold_and_the_planner_is_told(scenario: Scenario, git_pool: GitPool) -> None:
    """The held plan is superseded by the operator's ask; the plan run it starts hears the ids, and plans anew."""
    assert git_pool.slots
    approved_epic(scenario, (KEY, "B2"))
    assert scenario.run(PLAN, worker=planner_does(plan=TEXT)).status is RunStatus.DONE
    scenario.operator("plan", KEY, "--approve")
    approved_again(scenario, C1_CHANGED)

    scenario.operator("plan", KEY)
    again = scenario.run(PLAN, worker=planner_does(plan=TEXT + "\nWrites too.\n"))
    assert "changing `C1`" in again.prompt
    scenario.operator("plan", KEY, "--approve")
    assert scenario.run(IMPLEMENT, worker=pushes()).status is RunStatus.DONE


def test_work_in_flight_or_built_is_left_alone_and_a_member_not_reached_is_untouched(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """A run at work and a ticket with a branch are only told; a change that misses a member is no news to it."""
    assert git_pool.slots
    approved_epic(scenario, (KEY, "B1"), (OTHER, "B2"))
    assert scenario.run(IMPLEMENT, worker=pushes()).status is RunStatus.DONE
    planning = scenario.starts(dispatches(OTHER, RunKind.PLAN), worker=planner_does(plan=TEXT))

    approved = approved_again(scenario, C1_CHANGED)
    assert f"Left as they are, each told at its next plan: {KEY}, {OTHER}\n" in approved.out
    assert "superseded as stale" not in approved.out
    assert planning.finishes().status is RunStatus.DONE
    # Its plan, landing after, waits on the operator as any does: nothing paused it or marked it.
    [landed] = plans.history(scenario.conn, OTHER)
    assert (landed.status, landed.epic_changed_ids) == (PlanStatus.PROPOSED, None)
    assert present(epic_changes.pending(scenario.conn, KEY)).ids == ["C1"]

    # R1 is B1's alone: OTHER, which fulfils B2, is not reached, and its plan stays as it was.
    approved = approved_again(scenario, R1_CHANGED, "Workers restart too.")
    assert f"Left as they are, each told at its next plan: {KEY}\n" in approved.out
    assert present(plans.current(scenario.conn, OTHER)).status is PlanStatus.PROPOSED
    assert present(epic_changes.pending(scenario.conn, KEY)).ids == ["C1", "R1"]
