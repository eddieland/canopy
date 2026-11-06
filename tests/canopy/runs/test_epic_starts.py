"""An epic's plan run, started by the tick in code and kept only when canopy can read its plan (DESIGN §43)."""

import json
from pathlib import Path
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli.main import main
from canopy.core import config, db, epics, plans, prompts, records
from canopy.core.context import Context
from canopy.core.vocab import PlanStatus, RunStatus
from canopy.infra import logs
from canopy.runs import epic_runs, epic_starts
from tests.canopy.helpers import (
    InlineRunner,
    agent_runs,
    commands_run,
    edits_plan,
    epic_planning,
    in_tick,
    inline_context,
    operator,
    planner_does,
    pool_statuses,
    present,
    running_run,
)
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import CanopyEnv, GitPool

GOAL = "Move sessions to the new store."
PLAN = """\
# Epic: sessions in the new store

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


def start(ctx: Context) -> list[epic_starts.Started]:
    """Start the plan runs epics are due, as a live tick does, in a tick of its own."""
    with in_tick(ctx.conn) as tick_id:
        return epic_starts.start_due(ctx, tick_id, logs.for_tick(tick_id))


def run_plan(run_id: int) -> None:
    """Do plan run `run_id` in this process, as its detached `canopy _epic` would."""
    assert main(["_epic", str(run_id)], runner=InlineRunner()) == 0


def test_a_submitted_epic_is_planned_once_and_its_plan_proposed(
    capsys: pytest.CaptureFixture[str],
    inline: Context,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    """The tick starts one plan run, the planner writes the plan, and canopy keeps it `proposed`, its slot returned."""
    assert operator("epic", "submit", GOAL) == 0
    [started] = start(inline)
    assert start(inline) == []  # one plan run of an epic at a time
    assert "leased" in pool_statuses(treehouse_state)
    with planner_does(plan=PLAN):
        run_plan(started.run_id)
    run = present(epic_runs.get_run(inline.conn, started.run_id))
    assert run.status is RunStatus.DONE
    plan = present(epics.current_plan(inline.conn, 1))
    assert (plan.status, plan.run_id) == (PlanStatus.PROPOSED, run.id)
    path = epics.plan_path(inline.state_dir, 1, run.id)
    assert path.read_text() == PLAN
    assert plan.sha256 == plans.read(path).sha256
    assert set(pool_statuses(treehouse_state)) == {"available"}
    assert not Path(run.desk_path).exists()
    # Its planner was the read-only planner, given the goal, in its desk of links.
    [planner] = agent_runs(agent_log)
    assert "canopy-planner" in " ".join(planner["argv"])
    assert GOAL in (planner["stdin"] or "") + " ".join(planner["argv"])
    assert Path(planner["cwd"]).name == "epic:1"
    # A done run is not started again until the operator replies.
    assert start(inline) == []
    assert operator("show", "epic:1") == 0
    shown = capsys.readouterr().out
    assert f"  {run.id}  done" in shown
    assert "Plan: proposed, written" in shown


@pytest.mark.parametrize(
    ("plan", "note"),
    [
        (None, "its .canopy-new-plan.md is missing; no plan was recorded"),
        (PLAN.replace("## Contracts", "## Interfaces"), "its plan's ids or breakdown cannot be read"),
        (PLAN.replace("Repositories: repo", "Repositories: web"), "B1 names web, which is not the epic's"),
    ],
    ids=["no plan", "an outline canopy cannot read", "a repository not the epic's"],
)
def test_a_plan_canopy_cannot_read_is_not_recorded(inline: Context, plan: str | None, note: str) -> None:
    """A `done` run whose plan is missing, or whose ids or breakdown canopy cannot read, is `unknown`: no plan."""
    assert operator("epic", "submit", GOAL) == 0
    [started] = start(inline)
    with planner_does(plan=plan):
        run_plan(started.run_id)
    run = present(epic_runs.get_run(inline.conn, started.run_id))
    assert run.status is RunStatus.UNKNOWN
    assert note in json.loads(present(run.result_json))["harness"]
    assert epics.plans_of(inline.conn, 1) == []


def test_a_revision_starts_as_the_plan_it_replaces_and_is_refused_left_so(inline: Context, agent_log: Path) -> None:
    """#2099: an epic's revision starts with its file as the plan it replaces; left so after a reply, it is no plan."""
    assert operator("epic", "submit", GOAL) == 0
    [started] = start(inline)
    with planner_does(plan=PLAN):
        run_plan(started.run_id)
    assert operator("reply", "epic:1", "Say where the store moves.") == 0
    [untouched] = start(inline)
    with planner_does(["cat", plans.WRITTEN], plan=None):
        run_plan(untouched.run_id)
    run = present(epic_runs.get_run(inline.conn, untouched.run_id))
    assert run.status is RunStatus.UNKNOWN
    assert plans.UNREVISED in json.loads(present(run.result_json))["harness"]
    [*_, [cat]] = commands_run(agent_log)
    assert cat["stdout"] == PLAN
    assert [p.run_id for p in epics.plans_of(inline.conn, 1)] == [started.run_id]
    # Edited, it is the new plan, and what its planner did not edit is the plan it replaces.
    assert operator("reply", "epic:1", "Say where the store moves, please.") == 0
    [edited] = start(inline)
    with planner_does(edits_plan("The store moves.", "The store moves to Redis."), plan=None):
        run_plan(edited.run_id)
    plan = present(epics.current_plan(inline.conn, 1))
    assert plan.run_id == edited.run_id
    path = epics.plan_path(inline.state_dir, 1, edited.run_id)
    assert path.read_text() == PLAN.replace("The store moves.", "The store moves to Redis.")


def test_a_blocked_planner_records_its_question_and_no_plan(inline: Context) -> None:
    """A planner that cannot plan without a human decision is `blocked`; its question is kept on the run."""
    assert operator("epic", "submit", GOAL) == 0
    [started] = start(inline)
    with planner_does(plan=None, result={"status": "blocked", "summary": "stuck", "question": "A or B?"}):
        run_plan(started.run_id)
    run = present(epic_runs.get_run(inline.conn, started.run_id))
    assert run.status is RunStatus.BLOCKED
    assert json.loads(present(run.result_json))["question"] == "A or B?"
    assert epics.plans_of(inline.conn, 1) == []


def test_plan_runs_wait_for_max_workers_and_a_dry_tick_starts_none(canopy_env: CanopyEnv, git_pool: GitPool) -> None:
    """Every run holding a slot counts toward `max_workers`; a dry tick starts no plan run (D036)."""
    assert git_pool.slots
    canopy_env.configure(canopy_env.user_file, {"capacity": {"max_workers": 1}})
    ctx = inline_context(canopy_env)
    assert operator("epic", "submit", GOAL) == 0
    assert operator("epic", "submit", "Another goal.") == 0
    assert main(["tick", "--dry-run"], runner=InlineRunner()) in (0, 1)
    assert epic_runs.runs_of(ctx.conn, 1) == []
    [started] = start(ctx)
    assert started.epic_id == 1
    assert db.busy_workers(ctx.conn) == 1


def test_plan_runs_stop_at_max_plan_attempts(canopy_env: CanopyEnv, git_pool: GitPool) -> None:
    """An epic has at most `policy.max_plan_attempts` plan runs, never reset (D030)."""
    assert git_pool.slots
    canopy_env.configure(canopy_env.user_file, {"policy": {"max_plan_attempts": 1}})
    ctx = inline_context(canopy_env)
    assert operator("epic", "submit", GOAL) == 0
    assert epic_runs.due(ctx.conn, 1) != []
    [started] = start(ctx)
    with planner_does(plan=None, result={"status": "failed", "summary": "no"}):
        run_plan(started.run_id)
    assert epic_runs.due(ctx.conn, 1) == []


def test_a_running_plan_run_takes_worker_capacity(scenario: Scenario, git_pool: GitPool) -> None:
    """While a plan run holds the one worker `max_workers` allows, a dispatch is refused for capacity."""
    assert git_pool.slots
    scenario.configures(capacity={"max_workers": 1})
    epic_planning(scenario.env)
    assert scenario.refuses(dispatches()) == [("refused:capacity", "1 of 1 workers are running")]


# Stopping


def test_a_stop_while_the_plan_run_works_lets_it_finish_and_starts_no_more(
    capsys: pytest.CaptureFixture[str],
    inline: Context,
) -> None:
    """The plan run at work finishes and its plan is kept; no tick starts another, and the epic shows it stopped."""
    assert operator("epic", "submit", GOAL) == 0
    [started] = start(inline)
    assert operator("stop", "epic:1") == 0
    out = capsys.readouterr().out
    assert "epic:1 is stopped; no plan run of it starts again." in out
    assert f"Its plan run {started.run_id} is still working and will finish; --now ends it." in out
    assert present(epic_runs.get_run(inline.conn, started.run_id)).status is RunStatus.RUNNING
    with planner_does(plan=PLAN):
        run_plan(started.run_id)
    assert present(epic_runs.get_run(inline.conn, started.run_id)).status is RunStatus.DONE
    assert present(epics.current_plan(inline.conn, 1)).status is PlanStatus.PROPOSED
    assert epic_runs.due(inline.conn, 3) == []
    assert start(inline) == []
    assert operator("show", "epic:1") == 0
    shown = capsys.readouterr().out
    assert "ago: no plan run of it starts again" in shown
    assert "`canopy reply epic:1` asks" not in shown


def test_stop_now_ends_the_plan_run_and_returns_its_slots(
    capsys: pytest.CaptureFixture[str],
    inline: Context,
    treehouse_state: Path,
) -> None:
    """`--now` kills the plan run, closes it `stopped`, returns its slot, and removes its desk."""
    assert operator("epic", "submit", GOAL) == 0
    [started] = start(inline)
    assert operator("stop", "epic:1", "--now") == 0
    assert f"Its plan run {started.run_id} was ended and its slots returned." in capsys.readouterr().out
    run = present(epic_runs.get_run(inline.conn, started.run_id))
    assert run.status is RunStatus.STOPPED
    assert json.loads(present(run.result_json))["harness"] == epic_runs.STOP_NOTE
    assert set(pool_statuses(treehouse_state)) == {"available"}
    assert not Path(run.desk_path).exists()
    assert start(inline) == []
    # A second stop finds the epic stopped and no run at work.
    assert operator("stop", "epic:1", "--now") == 0
    out = capsys.readouterr().out
    assert "epic:1 was already stopped." in out
    assert "plan run" not in out


def test_a_stop_after_the_tick_read_the_epic_due_starts_nothing(inline: Context, treehouse_state: Path) -> None:
    """A stop that commits between the tick's read and its insert wins: no run, and the slot it leased goes back."""
    assert operator("epic", "submit", GOAL) == 0
    read = epic_runs.due(inline.conn, 3)
    assert operator("stop", "epic:1") == 0
    with mock.patch.object(epic_runs, "due", autospec=True, return_value=read):
        assert start(inline) == []
    assert epic_runs.runs_of(inline.conn, 1) == []
    assert set(pool_statuses(treehouse_state)) == {"available"}


def test_stopping_an_epic_stops_no_member_s_run(inline: Context) -> None:
    """`--now` ends the plan run alone: membership never authorized work, so stopping the epic ends no member's."""
    assert operator("epic", "submit", GOAL) == 0
    assert operator("epic", "add", "epic:1", "PROJ-2") == 0
    [started] = start(inline)
    worker = running_run(inline, "PROJ-2")
    assert operator("stop", "epic:1", "--now") == 0
    assert present(epic_runs.get_run(inline.conn, started.run_id)).status is RunStatus.STOPPED
    assert present(records.select(records.Run).where("id = ?", worker).one(inline.conn)).status is RunStatus.RUNNING
    assert [m.ticket_key for m in epics.members_of(inline.conn, 1)] == ["PROJ-2"]


def test_the_epic_planner_prompt(canopy_env: CanopyEnv, markdown_snapshot: SnapshotAssertion) -> None:
    """The prompt an epic's planner gets, its placeholders filled as a start fills them (DESIGN §43)."""
    cfg = config.load(canopy_env.root, canopy_env.user_file)
    values = {
        "EPIC_ID": "1",
        "GOAL": GOAL,
        "DESK": "/ws/desks/epic:1",
        "REPOSITORIES": "- `api`: `/ws/desks/epic:1/api`\n- `web`: `/ws/desks/epic:1/web`",
        "MEMBERS": "- PROJ-2",
        "MAP": None,
        "OPERATOR_MESSAGES": None,
        "PLAN_OUT": plans.WRITTEN,
        "PLAN_FILE": plans.REPLACED,
        "MAX_PLAN_CHARS": str(plans.MAX_CHARS),
        "TIMEOUT_MINUTES": "45",
    }
    assert prompts.render_epic_plan(cfg, values) == markdown_snapshot
