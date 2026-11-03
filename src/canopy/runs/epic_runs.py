"""An epic's plan runs (DESIGN §43): each run's row and its slots, its close, and its end when its process dies.

A plan run holds a slot in the pool of each repository the epic names, leased as `canopy:epic:<id>`, and runs in
a desk of links to them, `<workspace>/desks/epic:<id>/`, a name no ticket's desk can take: a ticket key holds no `:`.
Its runs count toward `capacity.max_workers` with every other run that holds a slot, and reconcile closes one whose
process is gone as it closes a task's, its slots tidied and returned and its desk removed. Its rows name the
epic, never a ticket: the overseer never reads them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import conversation, db, pools, records, sql
from canopy.core.vocab import RunStatus
from canopy.infra import procs
from canopy.runs import desks, tidy

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

    from canopy.core.context import Context
    from canopy.core.vocab import PoolKind
    from canopy.infra import logs

#: What a plan run's slots are leased as, after `canopy:` (DESIGN §18): `canopy:epic:<id>`, which no ticket key can be.
HOLDER_KEY = "epic:"
#: Where plan runs' logs and prompts live: `<state_dir>/epic-runs/`, the operator's only.
RUNS_DIR = "epic-runs"


def desk_key(epic_id: int) -> str:
    """Return the name of epic `epic_id`'s desk under `desks/`: `epic:<id>`, no ticket's key."""
    return f"{HOLDER_KEY}{epic_id}"


def runs_dir(ctx: Context) -> Path:
    """Where plan runs' logs and prompts live, readable only by the operator (TRUST_MODEL T2).

    Returns:
        `<state_dir>/epic-runs`, created if it is missing.
    """
    path = ctx.state_dir / RUNS_DIR
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def objects_dir(log_path: Path) -> Path:
    """Return a plan run's object directory, beside its log at `log_path`, as a task run's is (DESIGN §8)."""
    return log_path.with_suffix(".objects")


def insert_run(
    conn: sqlite3.Connection,
    *,
    epic_id: int,
    tick_id: int,
    desk: Path,
    leases: Sequence[tuple[str, pools.Lease]],
    pool: PoolKind,
    logs_dir: Path,
    model: str | None = None,
) -> int:
    """Record a plan run of epic `epic_id` in the slots `leases` hold, one per repository, in one go.

    Its log is `<logs_dir>/<id>.log`; `model` is the one its planner asks for (DESIGN §13), None for the runtime's
    default. The run carries the newest message about the epic, so a reply after it asks for the next plan.

    Returns:
        The new run's id.
    """
    with db.transaction(conn):
        newest = (
            sql.select("max(id)")
            .from_("messages")
            .where("subject_kind = ? AND subject_id = ?", conversation.EPIC, str(epic_id))
        )
        insert = records.insert(
            records.EpicRun,
            epic_id=epic_id,
            tick_id=tick_id,
            desk_path=str(desk),
            started_at=db.now(),
            log_path="",
            message_id=sql.execute(conn, newest).fetchone()[0],
            model=model,
        )
        run_id = int(insert.run(conn).lastrowid or 0)
        log_path = str(logs_dir / f"{run_id}.log")
        records.update(records.EpicRun).set(log_path=log_path).where("id = ?", run_id).run(conn)
        rows = records.insert_rows(
            records.EpicRunSlot,
            ("run_id", "repo", "slot_path", "lease_id", "lease_holder", "base_branch", "pool"),
        )
        rows.many(
            conn,
            [
                (run_id, repo, str(lease.path), lease.lease_id, lease.lease_holder, lease.base_branch, str(pool))
                for repo, lease in leases
            ],
        )
    return run_id


def get_run(conn: sqlite3.Connection, run_id: int) -> records.EpicRun | None:
    """Return plan run `run_id`, or None if there is none."""
    return records.select(records.EpicRun).where("id = ?", run_id).one(conn)


def running(conn: sqlite3.Connection) -> list[records.EpicRun]:
    """Return every plan run still running, the oldest first."""
    return records.select(records.EpicRun).where("status = ?", RunStatus.RUNNING).order_by("id").all(conn)


def slots_of(conn: sqlite3.Connection, run_id: int) -> list[records.EpicRunSlot]:
    """Return the slots plan run `run_id` leased, by repository."""
    return records.select(records.EpicRunSlot).where("run_id = ?", run_id).order_by("repo").all(conn)


def set_git_link(conn: sqlite3.Connection, run_id: int, repo: str, link: bytes | None) -> None:
    """Record what run `run_id`'s slot in `repo` held in its `.git` file when the run started (DESIGN §8)."""
    update = records.update(records.EpicRunSlot).set(git_link=link)
    update.where("run_id = ? AND repo = ?", run_id, repo).run(conn)


def close_run(conn: sqlite3.Connection, run_id: int, status: RunStatus, result_json: str | None) -> bool:
    """Close plan run `run_id` as `status`, with `result_json`.

    Returns:
        True if this call closed it; False if it was already closed.
    """
    return db.finish_run(conn, "epic_runs", run_id, status, result_json)


def end(ctx: Context, run: records.EpicRun, status: RunStatus, note: str, log: logs.TickAdapter) -> set[str]:
    """Close a plan run whose process is gone, or was killed, as `status`: stop its planner, return its slots.

    Reconcile closes a crashed run this way.

    Returns:
        The lease ids it dealt with, returned or kept, which reconcile then leaves alone; none when the run's own
        process closed it first.
    """
    fields = {"epic_run_id": run.id, "epic": run.epic_id, "pid": run.pid}
    # Its process is gone, but a planner it started may not be. Stop it before its slots go back to their pools.
    if run.agent_pid is not None and procs.kill_group(run.agent_pid):
        log.warning("killed the agent a gone process left behind", extra={**fields, "agent_pid": run.agent_pid})
    if not close_run(ctx.conn, run.id, status, json.dumps({"harness": note})):
        # Its own process closed it first, and returned its slots.
        return set()
    procs.drop_lifelock(Path(run.log_path))
    dealt = release(ctx, run, log)
    log.warning("epic plan run closed without its process", extra={**fields, "status": status, "note": note})
    return dealt


def release(ctx: Context, run: records.EpicRun, log: logs.TickAdapter) -> set[str]:
    """Remove the run's desk, then tidy each of its slots as a worker run's is (DESIGN §8), and return it.

    A slot that could not be tidied is not returned, and the object directory is kept, so its objects can be read. A
    return that fails is left to the next tick's reconcile, which returns a canopy lease no running run holds.

    Returns:
        The lease ids it dealt with, returned or kept.
    """
    desks.remove(Path(run.desk_path))
    objects = objects_dir(Path(run.log_path))
    dealt: set[str] = set()
    tidied = True
    for slot in slots_of(ctx.conn, run.id):
        fields = {"epic_run_id": run.id, "slot": slot.slot_path, "repo": slot.repo, "lease_id": slot.lease_id}
        dealt.add(slot.lease_id)
        link = slot.git_link
        path = Path(slot.slot_path)
        if not tidy.tidy(ctx.runner, path, link=link, base=slot.base_branch, objects=objects, log=log, fields=fields):
            tidied = False
            continue
        try:
            outcome = ctx.pool_of(slot.pool, slot.repo).return_slot(
                path,
                lease_id=slot.lease_id,
                lease_holder=slot.lease_holder,
            )
        except pools.PoolError as e:
            log.error("epic plan run's slot not returned", extra={**fields, "error": str(e)})  # noqa: TRY400
            continue
        log.info("epic plan run's slot returned", extra={**fields, "outcome": outcome.value})
    if tidied:
        tidy.remove_objects(objects, log)
    return dealt
