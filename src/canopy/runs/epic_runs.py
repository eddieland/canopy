"""An epic's plan runs (DESIGN §43): each run's row and its slots, its close, and its end when its process dies.

A plan run holds a slot in the pool of each repository the epic names, leased as `canopy:epic:<id>`, and runs in
a desk of links to them, `<workspace>/desks/epic:<id>/`, a name no ticket's desk can take: a ticket key holds no `:`.
Its runs count toward `capacity.max_workers` with every other run that holds a slot, and reconcile closes one whose
process is gone as it closes a task's, its slots tidied and returned and its desk removed. Its rows name the
epic, never a ticket: the overseer never reads them.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import conversation, db, pools, records, sql
from canopy.core.items import Item
from canopy.core.vocab import PlanStatus, RunStatus
from canopy.infra import procs
from canopy.runs import desks, ending, tidy

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence
    from collections.abc import Set as AbstractSet

    from canopy.core.context import Context
    from canopy.core.vocab import PoolKind
    from canopy.infra import logs

#: What a plan run's slots are leased as, after `canopy:` (DESIGN §18): `canopy:epic:<id>`, which no ticket key can be.
HOLDER_KEY = "epic:"
#: Where plan runs' logs and prompts live: `<state_dir>/epic-runs/`, the operator's only.
RUNS_DIR = "epic-runs"
#: Where a ticket key would be, an attention item about an epic names it so (DESIGN §43).
EPIC_PREFIX = "epic:"
#: The attention reason an epic's plan waiting on the operator raises, as a ticket's does (DESIGN §25, §43).
REASON = "plan_review"
#: The note a plan run ended by the operator's stop is closed with.
STOP_NOTE = "the operator stopped the epic with `canopy stop --now`"


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
) -> int | None:
    """Record a plan run of epic `epic_id` in the slots `leases` hold, one per repository, in one go, if not stopped.

    Its log is `<logs_dir>/<id>.log`; `model` is the one its planner asks for (DESIGN §13), None for the runtime's
    default. The run carries the newest message about the epic, so a reply after it asks for the next plan. Checked in
    the transaction that inserts it, so a `stop` that commits first starts nothing.

    Returns:
        The new run's id, or None when the operator stopped the epic.
    """
    with db.transaction(conn):
        epic = records.select(records.Epic).where("id = ?", epic_id).one(conn)
        if epic is None or epic.stopped_at is not None:
            return None
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


def due(conn: sqlite3.Connection, max_attempts: int) -> list[records.Epic]:
    """Return the epics a tick starts a plan run for now, the oldest first (DESIGN §43).

    One is due once after its submission, and once after each reply of the operator's newer than its latest run: each
    run follows an operator's word, so one that failed waits for the next. None is due while a run of it runs, once
    it has had `max_attempts` runs, a bound never reset (D030), or once the operator stopped it.

    Returns:
        The epics, by when they were submitted.
    """
    never_run = sql.frag("NOT EXISTS (SELECT 1 FROM epic_runs r WHERE r.epic_id = epics.id)")
    # Past the newest message the latest run's prompt carried: a reply no run has taken yet.
    replied = sql.frag(
        "EXISTS (SELECT 1 FROM messages m WHERE m.subject_kind = ? AND m.subject_id = CAST(epics.id AS TEXT)"
        " AND m.source = 'operator' AND m.id > coalesce((SELECT r.message_id FROM epic_runs r"
        " WHERE r.epic_id = epics.id ORDER BY r.id DESC LIMIT 1), 0))",
        conversation.EPIC,
    )
    query = (
        records.select(records.Epic)
        .where("stopped_at IS NULL")
        .where(
            "NOT EXISTS (SELECT 1 FROM epic_runs r WHERE r.epic_id = epics.id AND r.status = ?)",
            RunStatus.RUNNING,
        )
        .where("(SELECT count(*) FROM epic_runs r WHERE r.epic_id = epics.id) < ?", max_attempts)
        .where("{} OR {}", never_run, replied)
        .order_by("id")
    )
    return query.all(conn)


@dataclass(frozen=True)
class Released:
    """What became of a plan run's slots once it ended."""

    #: The lease ids it dealt with, returned or kept.
    dealt: AbstractSet[str]
    #: Whether every one of them went back to its pool.
    returned: bool


@dataclass(frozen=True)
class WaitingPlan:
    """An epic's plan waiting on the operator, which raises `plan_review` about `epic:<id>` (DESIGN §43)."""

    epic_id: int
    #: The plan, by its id, and the plan run that wrote it.
    plan_id: int
    run_id: int
    #: When its run recorded it: the item is open since then.
    at: str


def review_items(conn: sqlite3.Connection) -> list[Item]:
    """Return a `plan_review` item for each epic's plan waiting on the operator, as the attention list lists it (§43).

    Each names the epic and its plan, never the goal or the plan's text: the list reaches sinks whose audience may not
    be the operator, and an epic is private, as a task is (§36).

    Returns:
        The items, by epic, each open since its plan was recorded.
    """
    return [_review_item(w) for w in waiting_plans(conn)]


def waiting_plans(conn: sqlite3.Connection) -> list[WaitingPlan]:
    """Return each epic's plan that waits on the operator now, by epic: each raises `plan_review` (DESIGN §43).

    One waits while it is its epic's newest, `proposed`, no plan run of the epic works, the operator has not stopped
    the epic, and no reply of theirs is newer than the messages its run's prompt carried: a reply asks for the next
    plan, which raises the item again. Approving it, replying, or stopping the epic ends it.

    Returns:
        The plans, never their text: the item names the epic.
    """
    query = (
        records.select(records.EpicPlan, "p")
        .join("epics e ON e.id = p.epic_id")
        .join("epic_runs w ON w.id = p.run_id")
        .where("p.status = ? AND e.stopped_at IS NULL", PlanStatus.PROPOSED)
        .where(
            "NOT EXISTS (SELECT 1 FROM epic_runs r WHERE r.epic_id = p.epic_id AND r.status = ?)",
            RunStatus.RUNNING,
        )
        .where(
            "NOT EXISTS (SELECT 1 FROM messages m WHERE m.subject_kind = ? AND m.subject_id = CAST(p.epic_id AS TEXT)"
            " AND m.source = 'operator' AND m.id > coalesce(w.message_id, 0))",
            conversation.EPIC,
        )
        .order_by("p.epic_id")
    )
    return [WaitingPlan(p.epic_id, p.id, p.run_id, p.created_at) for p in query.all(conn)]


def _review_item(waiting: WaitingPlan) -> Item:
    ref = f"{EPIC_PREFIX}{waiting.epic_id}"
    detail = (
        f"{ref}'s plan {waiting.plan_id}, from run {waiting.run_id}, waits on your approval: read it with "
        f"`canopy show {ref}`, approve it with `canopy plan {ref} --approve`, or ask for changes with "
        f"`canopy reply {ref}`"
    )
    return Item(ref, REASON, detail, waiting.at)


def runs_of(conn: sqlite3.Connection, epic_id: int) -> list[records.EpicRun]:
    """Return every plan run of epic `epic_id`, the oldest first."""
    return records.select(records.EpicRun).where("epic_id = ?", epic_id).order_by("id").all(conn)


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
    released = _close(ctx, run, status, note, log)
    return set() if released is None else set(released.dealt)


def stop_now(ctx: Context, run: records.EpicRun, log: logs.TickAdapter) -> ending.Ending:
    """Kill plan run `run`'s processes and close it `stopped`, its slots returned: `canopy stop epic:N --now`.

    That it was asked is recorded first, so a stop that dies after the kill leaves reconcile to close it `stopped`.

    Returns:
        How it ended: `GONE` if it had already ended, and nothing changed; `KEPT` if a slot could not be returned.
    """
    # Read again first: a run that ended since the stop read it signals nothing, so no pid it held, since reused, is.
    current = get_run(ctx.conn, run.id)
    if current is None or current.status is not RunStatus.RUNNING or not db.ask_stop(ctx.conn, "epic_runs", run.id):
        return ending.Ending.GONE
    _kill(current.pid)
    # Its `_epic` first, so it starts no agent after this; then the agent the row names now, which may be one `_epic`
    # started since the read above, such as a run asked again for its result (DESIGN §13).
    now = get_run(ctx.conn, run.id)
    _kill((now if now is not None else current).agent_pid)
    released = _close(ctx, current, RunStatus.STOPPED, STOP_NOTE, log)
    if released is None:
        return ending.Ending.GONE
    return ending.Ending.ENDED if released.returned else ending.Ending.KEPT


def _kill(pid: int | None) -> None:
    """Kill process group `pid`, if any, but never this process's own, as an `_epic` run in-process by tests has."""
    if pid is not None and pid not in (os.getpid(), os.getpgid(0)):
        procs.kill_group(pid)


def release(ctx: Context, run: records.EpicRun, log: logs.TickAdapter) -> Released:
    """Remove the run's desk, then tidy each of its slots as a worker run's is (DESIGN §8), and return it.

    A slot that could not be tidied is not returned, and the object directory is kept, so its objects can be read. A
    return that fails is left to the next tick's reconcile, which returns a canopy lease no running run holds.

    Returns:
        The lease ids it dealt with, returned or kept, and whether every one went back to its pool.
    """
    desks.remove(Path(run.desk_path))
    objects = objects_dir(Path(run.log_path))
    dealt: set[str] = set()
    tidied = True
    returned = True
    for slot in slots_of(ctx.conn, run.id):
        fields = {"epic_run_id": run.id, "slot": slot.slot_path, "repo": slot.repo, "lease_id": slot.lease_id}
        dealt.add(slot.lease_id)
        link = slot.git_link
        path = Path(slot.slot_path)
        if not tidy.tidy(ctx.runner, path, link=link, base=slot.base_branch, objects=objects, log=log, fields=fields):
            tidied = returned = False
            continue
        try:
            outcome = ctx.pool_of(slot.pool, slot.repo).return_slot(
                path,
                lease_id=slot.lease_id,
                lease_holder=slot.lease_holder,
            )
        except pools.PoolError as e:
            log.error("epic plan run's slot not returned", extra={**fields, "error": str(e)})  # noqa: TRY400
            returned = False
            continue
        log.info("epic plan run's slot returned", extra={**fields, "outcome": outcome.value})
        returned = returned and outcome is pools.ReturnOutcome.RETURNED
    if tidied:
        tidy.remove_objects(objects, log)
    return Released(frozenset(dealt), returned=returned)


def _close(ctx: Context, run: records.EpicRun, status: RunStatus, note: str, log: logs.TickAdapter) -> Released | None:
    """Close plan run `run` without its process, as `end` says, and return its slots.

    Returns:
        What became of its slots; None when its own process closed it first, and returned them.
    """
    fields = {"epic_run_id": run.id, "epic": run.epic_id, "pid": run.pid}
    # Its process is gone, but a planner it started may not be. Stop it before its slots go back to their pools.
    if run.agent_pid is not None and procs.kill_group(run.agent_pid):
        log.warning("killed the agent a gone process left behind", extra={**fields, "agent_pid": run.agent_pid})
    if not close_run(ctx.conn, run.id, status, json.dumps({"harness": note})):
        # Its own process closed it first, and returned its slots.
        return None
    procs.drop_lifelock(Path(run.log_path))
    released = release(ctx, run, log)
    log.warning("epic plan run closed without its process", extra={**fields, "status": status, "note": note})
    return released
