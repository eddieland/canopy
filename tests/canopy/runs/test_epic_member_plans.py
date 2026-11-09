"""A member ticket's plan and work, within its epic's approved plan, which its planner and worker read as approved."""

import json
from pathlib import Path

from canopy.core import epics, plans
from canopy.core.vocab import RunKind, RunStatus
from canopy.infra import procs
from tests.canopy.helpers import (
    BRANCH,
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
