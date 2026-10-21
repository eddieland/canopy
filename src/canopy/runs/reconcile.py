"""Reconcile (DESIGN §6 step 3): close runs whose process is gone and return leases no running run holds.

In a workspace, every repository with a clone has its own pool, and each is read and cleaned up in turn. A joint run
holds a slot in several pools, and all of them are returned, and its desk removed, when its process is gone
(DESIGN §18).

While treehouse makes the pools, reconcile also classifies each idle treehouse slot with canopy's own pool's checks and
logs a `pool_shadow_mismatch` line wherever the two disagree (ROADMAP M45, stage 2). The shadow changes nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from canopy.core import conversation, db, dead_runs, definitions, pool, pools, workspace
from canopy.core.vocab import PoolKind, RunStatus
from canopy.infra import cwds, logs, procs
from canopy.runs import desks, dispatch, tidy

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence
    from collections.abc import Set as AbstractSet

    from canopy.core.context import Context
    from canopy.core.workspace import Workspace


@dataclass(frozen=True)
class Capacity:
    """How many workers may run, and how many are running."""

    max_workers: int
    running: int

    @property
    def available(self) -> int:
        """Workers that may still start."""
        return max(0, self.max_workers - self.running)


@dataclass(frozen=True)
class Reconciled:
    """What reconcile leaves: the capacity, and each cloned repository's leased slots, by repository name."""

    capacity: Capacity
    leased: Mapping[str, Sequence[pools.Slot]] = field(default_factory=dict[str, list[pools.Slot]])


def run(ctx: Context, log: logs.TickAdapter) -> Reconciled:
    """Close runs whose process is gone and return canopy leases no running run holds.

    A repository in the map with no clone has no pool to read; the tick raises `repo_missing` for it instead.

    Returns:
        The capacity left, and each cloned repository's slots still leased, for the state block.

    Raises:
        pools.PoolError: the configured backend's pool could not be read or a slot could not be returned. The tick
            stops.
    """
    ws = ctx.workspace
    found: list[tuple[str, pools.Pool, Sequence[pools.Slot]]] = []
    for repo in ws.repos:
        if repo.cloned:
            ours = ctx.pool(repo.name)
            found.append((repo.name, ours, ours.status()))
    if ctx.config.pools.backend is PoolKind.TREEHOUSE:
        shadow(ctx.runner, ws, log, {name: slots for name, _, slots in found})
    found += _other_pools(ctx, log)
    returned = _close_dead_runs(ctx, log)
    running = db.running_runs(ctx.conn, "runs")
    running_slots = db.all_run_slots(ctx.conn, [int(r["id"]) for r in running])
    held = {s.lease_id for slots in running_slots.values() for s in slots}
    # A running review holds a slot too (DESIGN §21); its own reconcile returns it if its `_review` is gone.
    reviews = db.running_runs(ctx.conn, "review_runs")
    held |= {str(r["lease_id"]) for r in reviews if r["lease_id"]}
    # So does a running task run (DESIGN §36), which its own reconcile closes when its `_task` is gone.
    task_runs = db.running_runs(ctx.conn, "task_runs")
    held |= {str(r["lease_id"]) for r in task_runs}
    leased: dict[str, list[pools.Slot]] = {}
    for name, pool_, slots in found:
        still = _return_stale(log, name, pool_, slots, held=held, returned=returned)
        leased.setdefault(name, []).extend(still)
    for desk in desks.prune(ws.root, {str(r["ticket_key"]) for r in running}):
        log.warning("desk with no running run; removed", extra={"desk": str(desk)})
    if not running and not task_runs:
        # No run is live, so no run of an earlier canopy is still loading its snapshot.
        _prune_definitions(ctx, log)
    busy = len(running) + len(reviews) + len(task_runs)
    capacity = Capacity(max_workers=ctx.config.capacity.max_workers, running=busy)
    log.info("reconciled", extra={"running": capacity.running, "available": capacity.available})
    return Reconciled(capacity, leased)


def shadow(
    runner: procs.Runner,
    ws: Workspace,
    log: logs.TickAdapter,
    slots: Mapping[str, Sequence[pools.Slot]],
) -> int:
    """Classify each unleased treehouse slot with canopy's own checks, and log each one where they disagree.

    `slots` is what treehouse said of each cloned repository's pool, by repository name. Nothing is changed, and a
    check that fails is logged, never raised: the shadow must not stop a tick (ROADMAP M45, stage 2).

    Returns:
        How many slots it logged a mismatch for.
    """
    mismatches = 0
    # One read of the process table for every slot: on macOS each read is a full `lsof`.
    try:
        processes: cwds.Table | None = cwds.table(runner)
    except cwds.CwdError:
        processes = None
    for name, found in slots.items():
        repo = ws.repo(name)
        if repo is None:
            continue
        for slot in found:
            if slot.lease_holder or slot.lease_id:
                continue
            try:
                ours = (
                    pool.classify(runner, repo.path, slot.path, found=processes.inside(slot.path))
                    if processes is not None
                    else pool.UNVERIFIED
                )
            except OSError as e:
                ours = f"error: {e}"
            if ours != slot.status:
                mismatches += 1
                log.warning(
                    "pool_shadow_mismatch",
                    extra={"repo": name, "slot": str(slot.path), "treehouse": slot.status, "canopy": ours},
                )
    return mismatches


def _close_dead_runs(ctx: Context, log: logs.TickAdapter) -> set[str]:
    """Mark running runs whose `_run` is gone `crashed` and return all their slots.

    Returns:
        The lease ids returned, or kept for the operator.
    """
    returned: set[str] = set()
    for run in dead_runs.find(ctx.conn, "runs"):
        returned |= end_run(ctx, run, RunStatus.CRASHED, "the worker process is gone", log)
    return returned


def end_run(ctx: Context, run: sqlite3.Row, status: RunStatus, note: str, log: logs.TickAdapter) -> set[str]:
    """Close a run whose `_run` is gone, or was killed, as `status`: stop its worker, tidy and return its slots.

    Its desk and its object directory are removed too. Reconcile closes a crashed run this way, and `canopy stop --now`
    a stopped one (DESIGN §22). Each slot is tidied as `_run` would have (DESIGN §8): its `.git` file checked against
    what `_run` recorded, and the slot moved off the run's own objects. One that cannot be tidied is not returned, and
    the object directory is kept.

    Returns:
        The lease ids it dealt with, returned or kept, which reconcile then leaves alone.

    Raises:
        pools.PoolError: a slot could not be returned.
    """
    returned: set[str] = set()
    slots = db.run_slots(ctx.conn, int(run["id"]))
    fields = {
        "run_id": run["id"],
        "ticket": run["ticket_key"],
        "pid": run["pid"],
        "slots": [s.slot_path for s in slots],
        "repos": [s.repo for s in slots],
    }
    # `_run` is gone, but a worker it started may not be. Stop it before its slots go back to their pools.
    dead_runs.kill_agent("runs", run, log, fields)
    conversation.close_run(ctx.conn, ctx.config, run, status, json.dumps({"harness": note}))
    procs.drop_lifelock(Path(run["log_path"]))
    outcomes: list[str] = []
    objects = tidy.objects_dir(dispatch.runs_dir(ctx), int(run["id"]))
    tidied = True
    for slot in slots:
        where = {**fields, "slot": slot.slot_path, "repo": slot.repo}
        link = slot.git_link
        if not tidy.tidy(
            ctx.runner,
            Path(slot.slot_path),
            link=bytes(link) if link is not None else None,
            base=str(slot.base_branch),
            objects=objects,
            log=log,
            fields=where,
        ):
            tidied = False
            returned.add(slot.lease_id)  # kept for the operator: not returned as a stale lease either
            outcomes.append("kept")
            continue
        outcome = ctx.pool_of(slot.pool, slot.repo).return_slot(
            Path(slot.slot_path),
            lease_id=slot.lease_id,
            lease_holder=slot.lease_holder,
        )
        returned.add(slot.lease_id)
        outcomes.append(outcome.value)
    if tidied:
        tidy.remove_objects(objects, log)
    if dispatch.in_desk(str(run["kind"]), slots):
        desks.remove(desks.path(ctx.workspace.root, str(run["ticket_key"])))
    log.warning("run closed without its `_run`", extra={**fields, "status": status, "note": note, "returned": outcomes})
    return returned


def _return_stale(
    log: logs.TickAdapter,
    name: str,
    pool_: pools.Pool,
    slots: Sequence[pools.Slot],
    *,
    held: AbstractSet[str],
    returned: AbstractSet[str],
) -> list[pools.Slot]:
    """Return repository `name`'s canopy leases in `pool_` that no running run holds.

    Returns:
        The slots still leased.
    """
    leased: list[pools.Slot] = []
    for slot in slots:
        if not slot.lease_id or slot.lease_id in returned:
            continue
        if slot.canopy_key is None or slot.lease_id in held:
            leased.append(slot)
            continue
        outcome = pool_.return_slot(slot.path, lease_id=slot.lease_id, lease_holder=slot.lease_holder)
        log.warning(
            "canopy lease with no running worker; returned",
            extra={
                "slot": str(slot.path),
                "repo": name,
                "lease_holder": slot.lease_holder,
                "lease_id": slot.lease_id,
                "returned": outcome.value,
            },
        )
    return leased


def _other_pools(ctx: Context, log: logs.TickAdapter) -> list[tuple[str, pools.Pool, Sequence[pools.Slot]]]:
    """Read the pools of the backend `pools.backend` does not name, where the workspace has any (DESIGN §18).

    After a switch, their leases still go back to them: a run's when it ends, and one no run holds here. canopy's are
    read whenever `pools/` holds one, treehouse's whenever `.treehouse/` exists. Either that cannot be read is logged
    rather than stopping the tick: only the pools `pools.backend` names are the tick's to stop for.

    Returns:
        Each repository's name, its pool of the other backend, and that pool's slots.
    """
    ws = ctx.workspace
    found: list[tuple[str, pools.Pool, Sequence[pools.Slot]]] = []
    match ctx.config.pools.backend:
        case PoolKind.TREEHOUSE:
            for repo in ws.repos:
                if not (ws.root / pool.POOLS_DIR / repo.name).is_dir():
                    continue
                other = ctx.pool_of(PoolKind.CANOPY, repo.name)
                try:
                    found.append((repo.name, other, other.status()))
                except pools.PoolError as e:
                    log.warning("canopy pool not read", extra={"repo": repo.name, "error": str(e)})
        case PoolKind.CANOPY:
            if not (ws.root / workspace.POOLS_DIR).is_dir():
                return found
            for repo in ws.repos:
                if not repo.cloned:
                    continue
                other = ctx.pool_of(PoolKind.TREEHOUSE, repo.name)
                try:
                    found.append((repo.name, other, other.status()))
                except pools.PoolError as e:
                    log.warning("treehouse pool not read", extra={"repo": repo.name, "error": str(e)})
        case unknown:
            assert_never(unknown)
    return found


def _prune_definitions(ctx: Context, log: logs.TickAdapter) -> None:
    try:
        current = definitions.ensure(ctx.state_dir, ctx.config)
    except definitions.DefinitionsError as e:
        # The overseer's run refuses it too and fails the tick with this message.
        log.error("definitions snapshot not usable", extra={"error": str(e)})  # noqa: TRY400
        return
    for removed in definitions.prune(ctx.state_dir, current):
        log.info("removed an old definitions snapshot", extra={"path": str(removed)})
