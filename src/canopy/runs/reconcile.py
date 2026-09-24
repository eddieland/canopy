"""Reconcile (DESIGN §6 step 3): close runs whose process is gone and return leases no running run holds."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import db, treehouse
from canopy.infra import logs, procs

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


def run(ctx: Context, log: logs.TickAdapter) -> Capacity:
    """Close runs whose process is gone, return canopy leases no running run holds, and return the capacity left.

    Raises:
        treehouse.TreehouseError: treehouse could not be read or a slot could not be returned. The tick stops.
    """
    slots = treehouse.status(ctx.runner)
    handled: set[str] = set()
    for run in db.running_runs(ctx.conn):
        pid = run["pid"]
        if pid is not None and procs.alive(int(pid)):
            continue
        fields = {"run_id": run["id"], "ticket": run["ticket_key"], "pid": pid, "slot": run["slot_path"]}
        # `_run` is gone, but a worker it started may not be: it leads its own process group. Stop it before its
        # slot goes back to the pool.
        if run["worker_pid"] is not None and procs.kill_group(int(run["worker_pid"])):
            log.warning("killed the worker `_run` left behind", extra={**fields, "worker_pid": run["worker_pid"]})
        db.finish_run(ctx.conn, int(run["id"]), "crashed", json.dumps({"harness": "the worker process is gone"}))
        outcome = treehouse.return_slot(
            ctx.runner,
            Path(run["slot_path"]),
            lease_id=str(run["lease_id"]),
            lease_holder=str(run["lease_holder"]),
        )
        handled.add(str(run["lease_id"]))
        log.warning("worker process is gone; run marked crashed", extra={**fields, "returned": outcome.value})

    running = db.running_runs(ctx.conn)
    held = {str(r["lease_id"]) for r in running} | handled
    for slot in slots:
        if slot.canopy_key is None or not slot.lease_id or slot.lease_id in held:
            continue
        outcome = treehouse.return_slot(ctx.runner, slot.path, lease_id=slot.lease_id, lease_holder=slot.lease_holder)
        log.warning(
            "canopy lease with no running worker; returned",
            extra={
                "slot": str(slot.path),
                "lease_holder": slot.lease_holder,
                "lease_id": slot.lease_id,
                "returned": outcome.value,
            },
        )

    capacity = Capacity(max_workers=ctx.config.capacity.max_workers, running=len(running))
    log.info("reconciled", extra={"running": capacity.running, "available": capacity.available})
    return capacity
