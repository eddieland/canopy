"""An initiative's plan run, started by the tick in code and kept only when canopy can read its plan (DESIGN §43)."""

import json
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli.main import main
from canopy.core import config, db, initiatives, plans, prompts
from canopy.core.context import Context
from canopy.core.vocab import PlanStatus, RunStatus
from canopy.infra import logs
from canopy.runs import initiative_runs, initiative_starts
from tests.canopy.helpers import (
    InlineRunner,
    agent_runs,
    in_tick,
    initiative_planning,
    inline_context,
    operator,
    planner_does,
    pool_statuses,
    present,
)
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import CanopyEnv, GitPool

GOAL = "Move sessions to the new store."
PLAN = """\
# Initiative: sessions in the new store

## Goal

Sessions survive a restart.

## Requirements

- **R1.** Sessions survive a restart of the API.

## Contracts

None.

## Breakdown

### B1. Move the store

- Covers: R1
- Provides: none
- Uses: none
- Repositories: repo
- After: none
- Trivial: no

The store moves.

## Decisions

## Out of scope
"""


@pytest.fixture
def inline(canopy_env: CanopyEnv, git_pool: GitPool) -> Context:
    """The workspace's context over real git slots, whose runner starts no detached process: a test runs it."""
    assert git_pool.slots
    return inline_context(canopy_env)


def start(ctx: Context) -> list[initiative_starts.Started]:
    """Start the plan runs initiatives are due, as a live tick does, in a tick of its own."""
    with in_tick(ctx.conn) as tick_id:
        return initiative_starts.start_due(ctx, tick_id, logs.for_tick(tick_id))


def run_plan(run_id: int) -> None:
    """Do plan run `run_id` in this process, as its detached `canopy _initiative` would."""
    assert main(["_initiative", str(run_id)], runner=InlineRunner()) == 0


def test_a_submitted_initiative_is_planned_once_and_its_plan_proposed(
    capsys: pytest.CaptureFixture[str],
    inline: Context,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    """The tick starts one plan run, the planner writes the plan, and canopy keeps it `proposed`, its slot returned."""
    assert operator("initiative", "submit", GOAL) == 0
    [started] = start(inline)
    assert start(inline) == []  # one plan run of an initiative at a time
    assert "leased" in pool_statuses(treehouse_state)
    with planner_does(plan=PLAN):
        run_plan(started.run_id)
    run = present(initiative_runs.get_run(inline.conn, started.run_id))
    assert run.status is RunStatus.DONE
    plan = present(initiatives.current_plan(inline.conn, 1))
    assert (plan.status, plan.run_id) == (PlanStatus.PROPOSED, run.id)
    path = initiatives.plan_path(inline.state_dir, 1, run.id)
    assert path.read_text() == PLAN
    assert plan.sha256 == plans.read(path).sha256
    assert set(pool_statuses(treehouse_state)) == {"available"}
    assert not Path(run.desk_path).exists()
    # Its planner was the read-only planner, given the goal, in its desk of links.
    [planner] = agent_runs(agent_log)
    assert "canopy-planner" in " ".join(planner["argv"])
    assert GOAL in (planner["stdin"] or "") + " ".join(planner["argv"])
    assert Path(planner["cwd"]).name == "init:1"
    # A done run is not started again until the operator replies.
    assert start(inline) == []
    assert operator("show", "init:1") == 0
    shown = capsys.readouterr().out
    assert f"  {run.id}  done" in shown
    assert "Plan: proposed, written" in shown


@pytest.mark.parametrize(
    ("plan", "note"),
    [
        (None, "its .canopy-new-plan.md is missing; no plan was recorded"),
        (PLAN.replace("## Contracts", "## Interfaces"), "its plan's ids or breakdown cannot be read"),
        (PLAN.replace("Repositories: repo", "Repositories: web"), "B1 names web, which is not the initiative's"),
    ],
    ids=["no plan", "an outline canopy cannot read", "a repository not the initiative's"],
)
def test_a_plan_canopy_cannot_read_is_not_recorded(inline: Context, plan: str | None, note: str) -> None:
    """A `done` run whose plan is missing, or whose ids or breakdown canopy cannot read, is `unknown`: no plan."""
    assert operator("initiative", "submit", GOAL) == 0
    [started] = start(inline)
    with planner_does(plan=plan):
        run_plan(started.run_id)
    run = present(initiative_runs.get_run(inline.conn, started.run_id))
    assert run.status is RunStatus.UNKNOWN
    assert note in json.loads(present(run.result_json))["harness"]
    assert initiatives.plans_of(inline.conn, 1) == []


def test_a_blocked_planner_records_its_question_and_no_plan(inline: Context) -> None:
    """A planner that cannot plan without a human decision is `blocked`; its question is kept on the run."""
    assert operator("initiative", "submit", GOAL) == 0
    [started] = start(inline)
    with planner_does(plan=None, result={"status": "blocked", "summary": "stuck", "question": "A or B?"}):
        run_plan(started.run_id)
    run = present(initiative_runs.get_run(inline.conn, started.run_id))
    assert run.status is RunStatus.BLOCKED
    assert json.loads(present(run.result_json))["question"] == "A or B?"
    assert initiatives.plans_of(inline.conn, 1) == []


def test_plan_runs_wait_for_max_workers_and_a_dry_tick_starts_none(canopy_env: CanopyEnv, git_pool: GitPool) -> None:
    """Every run holding a slot counts toward `max_workers`; a dry tick starts no plan run (D036)."""
    assert git_pool.slots
    canopy_env.configure(canopy_env.user_file, {"capacity": {"max_workers": 1}})
    ctx = inline_context(canopy_env)
    assert operator("initiative", "submit", GOAL) == 0
    assert operator("initiative", "submit", "Another goal.") == 0
    assert main(["tick", "--dry-run"], runner=InlineRunner()) in (0, 1)
    assert initiative_runs.runs_of(ctx.conn, 1) == []
    [started] = start(ctx)
    assert started.initiative_id == 1
    assert db.busy_workers(ctx.conn) == 1


def test_plan_runs_stop_at_max_plan_attempts(canopy_env: CanopyEnv, git_pool: GitPool) -> None:
    """An initiative has at most `policy.max_plan_attempts` plan runs, never reset (D030)."""
    assert git_pool.slots
    canopy_env.configure(canopy_env.user_file, {"policy": {"max_plan_attempts": 1}})
    ctx = inline_context(canopy_env)
    assert operator("initiative", "submit", GOAL) == 0
    assert initiative_runs.due(ctx.conn, 1) != []
    [started] = start(ctx)
    with planner_does(plan=None, result={"status": "failed", "summary": "no"}):
        run_plan(started.run_id)
    assert initiative_runs.due(ctx.conn, 1) == []


def test_a_running_plan_run_takes_worker_capacity(scenario: Scenario, git_pool: GitPool) -> None:
    """While a plan run holds the one worker `max_workers` allows, a dispatch is refused for capacity."""
    assert git_pool.slots
    scenario.configures(capacity={"max_workers": 1})
    initiative_planning(scenario.env)
    assert scenario.refuses(dispatches()) == [("refused:capacity", "1 of 1 workers are running")]


def test_the_initiative_planner_prompt(canopy_env: CanopyEnv, markdown_snapshot: SnapshotAssertion) -> None:
    """The prompt an initiative's planner gets, its placeholders filled as a start fills them (DESIGN §43)."""
    cfg = config.load(canopy_env.root, canopy_env.user_file)
    values = {
        "INITIATIVE_ID": "1",
        "GOAL": GOAL,
        "DESK": "/ws/desks/init:1",
        "REPOSITORIES": "- `api`: `/ws/desks/init:1/api`\n- `web`: `/ws/desks/init:1/web`",
        "MEMBERS": "- PROJ-2",
        "MAP": None,
        "OPERATOR_MESSAGES": None,
        "PLAN_OUT": plans.WRITTEN,
        "PLAN_FILE": plans.REPLACED,
        "MAX_PLAN_CHARS": str(plans.MAX_CHARS),
        "TIMEOUT_MINUTES": "45",
    }
    assert prompts.render_initiative_plan(cfg, values) == markdown_snapshot
