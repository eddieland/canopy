"""Reconcile (DESIGN §6 step 3): close runs whose process is gone and return leases no running run holds.

In a workspace, every repository with a clone has its own pool, and each is read and cleaned up in turn. A joint run
holds a slot in several pools, and all of them are returned, and its desk removed, when its process is gone
(DESIGN §18).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import db, definitions, outbox, treehouse
from canopy.infra import logs, procs
from canopy.runs import desks

if TYPE_CHECKING:
    from canopy.core.context import Context


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
    leased: dict[str, list[treehouse.Slot]] = field(default_factory=dict[str, list[treehouse.Slot]])


def run(ctx: Context, log: logs.TickAdapter) -> Reconciled:
    """Close runs whose process is gone and return canopy leases no running run holds.

    A repository in the map with no clone has no pool to read; the tick raises `repo_missing` for it instead.

    Returns:
        The capacity left, and each cloned repository's slots still leased, for the state block.

    Raises:
        treehouse.TreehouseError: treehouse could not be read or a slot could not be returned. The tick stops.
    """
    ws = ctx.workspace
    pools = {repo.name: treehouse.status(ctx.runner, pool=ws.pool(repo.name)) for repo in ws.repos if repo.cloned}
    returned = _close_dead_runs(ctx, log)
    running = db.running_runs(ctx.conn)
    running_slots = db.all_run_slots(ctx.conn, [int(r["id"]) for r in running])
    held = {str(s["lease_id"]) for slots in running_slots.values() for s in slots}
    leased = {name: _return_stale(ctx, log, name, slots, held=held, returned=returned) for name, slots in pools.items()}
    if not ws.single:
        # Only a workspace of several has desks; in a workspace of one, `desks/` would be the repository's own.
        for desk in desks.prune(ws.root, {str(r["ticket_key"]) for r in running}):
            log.warning("desk with no running run; removed", extra={"desk": str(desk)})
    if not running:
        # No run is live, so no run of an earlier canopy is still loading its snapshot.
        _prune_definitions(ctx, log)
    capacity = Capacity(max_workers=ctx.config.capacity.max_workers, running=len(running))
    log.info("reconciled", extra={"running": capacity.running, "available": capacity.available})
    return Reconciled(capacity, leased)


def _close_dead_runs(ctx: Context, log: logs.TickAdapter) -> set[str]:
    """Mark running runs whose `_run` is gone `crashed` and return all their slots. Returns the lease ids returned."""
    returned: set[str] = set()
    for run in db.running_runs(ctx.conn):
        pid = run["pid"]
        if pid is not None and procs.alive(int(pid)):
            continue
        slots = db.run_slots(ctx.conn, int(run["id"]))
        fields = {
            "run_id": run["id"],
            "ticket": run["ticket_key"],
            "pid": pid,
            "slots": [s["slot_path"] for s in slots],
            "repos": [s["repo"] for s in slots],
        }
        # `_run` is gone, but a worker it started may not be: it leads its own process group. Stop it before its
        # slots go back to their pools.
        if run["worker_pid"] is not None and procs.kill_group(int(run["worker_pid"])):
            log.warning("killed the worker `_run` left behind", extra={**fields, "worker_pid": run["worker_pid"]})
        note = json.dumps({"harness": "the worker process is gone"})
        db.finish_run(
            ctx.conn, int(run["id"]), "crashed", note, event=outbox.run_ended(ctx.config, run, "crashed", note)
        )
        outcomes: list[str] = []
        for slot in slots:
            outcome = treehouse.return_slot(
                ctx.runner,
                Path(slot["slot_path"]),
                lease_id=str(slot["lease_id"]),
                lease_holder=str(slot["lease_holder"]),
                pool=ctx.workspace.pool(slot["repo"]),
            )
            returned.add(str(slot["lease_id"]))
            outcomes.append(outcome.value)
        if len(slots) > 1:
            desks.remove(desks.path(ctx.workspace.root, str(run["ticket_key"])))
        log.warning("worker process is gone; run marked crashed", extra={**fields, "returned": outcomes})
    return returned


def _return_stale(
    ctx: Context, log: logs.TickAdapter, name: str, slots: list[treehouse.Slot], *, held: set[str], returned: set[str]
) -> list[treehouse.Slot]:
    """Return repository `name`'s canopy leases that no running run holds. Returns the slots still leased."""
    leased: list[treehouse.Slot] = []
    for slot in slots:
        if not slot.lease_id or slot.lease_id in returned:
            continue
        if slot.canopy_key is None or slot.lease_id in held:
            leased.append(slot)
            continue
        outcome = treehouse.return_slot(
            ctx.runner,
            slot.path,
            lease_id=slot.lease_id,
            lease_holder=slot.lease_holder,
            pool=ctx.workspace.pool(name),
        )
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


def _prune_definitions(ctx: Context, log: logs.TickAdapter) -> None:
    try:
        current = definitions.ensure(ctx.state_dir)
    except definitions.DefinitionsError as e:
        # The overseer's run refuses it too and fails the tick with this message.
        log.error("definitions snapshot not usable", extra={"error": str(e)})  # noqa: TRY400
        return
    for removed in definitions.prune(ctx.state_dir, current):
        log.info("removed an old definitions snapshot", extra={"path": str(removed)})
