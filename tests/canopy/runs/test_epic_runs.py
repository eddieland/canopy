"""An epic's plan runs as runs canopy holds (DESIGN §43): counted, reconciled, and spent like any other."""

import json
import os
from pathlib import Path

from canopy.core import db, epics, records
from canopy.core.context import Context
from canopy.core.vocab import RunStatus
from canopy.infra import logs
from canopy.runs import desks, epic_runs, reconcile
from tests.canopy.helpers import DEAD_PID, in_tick, inline_context, pool_statuses, present
from tests.conftest import CanopyEnv, GitPool


def plan_run(ctx: Context, *, pid: int, cost: float | None = None) -> records.EpicRun:
    """Record a plan run of a new epic in a slot of `repo`, its desk made, claimed by `pid`."""
    epic = epics.submit(
        ctx.conn,
        ctx.workspace,
        "Move sessions.",
        repos=(),
        project=None,
        tracker_epic=None,
        channel="cli",
    )
    lease = ctx.pool("repo").lease(f"{epic_runs.HOLDER_KEY}{epic.id}")
    key = epic_runs.desk_key(epic.id)
    desk = desks.make(ctx.workspace.root, key, [("repo", lease.path)])
    with in_tick(ctx.conn) as tick_id:
        run_id = epic_runs.insert_run(
            ctx.conn,
            epic_id=epic.id,
            tick_id=tick_id,
            desk=desk,
            leases=[("repo", lease)],
            pool=ctx.config.pools.backend,
            logs_dir=epic_runs.runs_dir(ctx),
        )
    assert db.claim_run(ctx.conn, "epic_runs", run_id, pid)
    if cost is not None:
        records.update(records.EpicRun).set(cost_usd=cost).where("id = ?", run_id).run(ctx.conn)
    return present(epic_runs.get_run(ctx.conn, run_id))


def test_a_plan_run_is_recorded_with_a_slot_per_repository_and_named_for_no_ticket(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
) -> None:
    """Its row names the epic and its desk, `desks/epic:<id>`, a name no ticket key takes; its slot is its own."""
    assert git_pool.slots
    ctx = inline_context(canopy_env)
    run = plan_run(ctx, pid=os.getpid())
    assert (run.epic_id, run.status, Path(run.desk_path).name) == (1, RunStatus.RUNNING, "epic:1")
    [slot] = epic_runs.slots_of(ctx.conn, run.id)
    assert (slot.repo, slot.lease_holder) == ("repo", "canopy:epic:1")
    assert epic_runs.running(ctx.conn) == [run]
    assert db.running_runs(ctx.conn, "runs") == []


def test_a_running_plan_run_holds_its_slot_and_desk_and_counts_toward_max_workers(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    """Reconcile leaves a live plan run's lease and desk alone, and counts it among the runs holding a slot."""
    assert git_pool.slots
    ctx = inline_context(canopy_env)
    run = plan_run(ctx, pid=os.getpid())
    assert db.busy_workers(ctx.conn) == 1
    with in_tick(ctx.conn) as tick_id:
        reconciled = reconcile.run(ctx, logs.for_tick(tick_id))
    assert reconciled.capacity.running == 1
    assert "leased" in pool_statuses(treehouse_state)
    assert desks.is_desk(Path(run.desk_path))


def test_reconcile_closes_a_plan_run_whose_process_is_gone_and_returns_its_slot(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    """A plan run whose process died is closed `crashed`, its slot returned and its desk removed."""
    assert git_pool.slots
    ctx = inline_context(canopy_env)
    run = plan_run(ctx, pid=DEAD_PID)
    with in_tick(ctx.conn) as tick_id:
        reconciled = reconcile.run(ctx, logs.for_tick(tick_id))
    closed = present(epic_runs.get_run(ctx.conn, run.id))
    assert closed.status is RunStatus.CRASHED
    assert json.loads(present(closed.result_json)) == {"harness": "the plan run's process is gone"}
    assert set(pool_statuses(treehouse_state)) == {"available"}
    assert not Path(run.desk_path).exists()
    assert reconciled.capacity.running == 0


def test_a_plan_run_s_cost_counts_toward_what_canopy_spent(canopy_env: CanopyEnv, git_pool: GitPool) -> None:
    """The month's spend, which the budget is held to, counts an epic's plan runs too (TRUST_MODEL T3)."""
    assert git_pool.slots
    ctx = inline_context(canopy_env)
    plan_run(ctx, pid=os.getpid(), cost=0.75)
    assert db.spent_ever(ctx.conn) == 0.75
