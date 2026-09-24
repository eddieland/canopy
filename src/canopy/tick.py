"""One tick of the loop (DESIGN §6): lock, migrate, reconcile, run the overseer, close the tick, publish attention."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from canopy import attention, db, lock, logs, policy, procs, prompts, resources, treehouse
from canopy.config import render_command

if TYPE_CHECKING:
    from canopy.context import Context

TICK_ID_ENV = "CANOPY_TICK_ID"
DONE_LINE = "tick complete"


@dataclass(frozen=True)
class Outcome:
    """How a tick ended."""

    tick_id: int | None
    status: str  # ok | overseer_failed | reconcile_failed | lock_busy
    summary: str


def run(ctx: Context, *, dry_run: bool) -> Outcome:
    """Run one tick: take the lock, then everything in DESIGN §6. A busy lock is an outcome, not an error."""
    try:
        with lock.hold(ctx.lock_path):
            outcome = _locked(ctx, dry_run=dry_run)
            # After the tick is closed: the list is the latest `ok` tick's, and this tick may be it.
            attention.publish(ctx, logs.for_tick(outcome.tick_id))
            return outcome
    except lock.LockBusyError:
        logs.for_tick(None).info("tick skipped: another tick holds the lock", extra={"lock": str(ctx.lock_path)})
        return Outcome(None, "lock_busy", "another tick holds the lock")


def _locked(ctx: Context, *, dry_run: bool) -> Outcome:
    applied = db.migrate(ctx.conn, resources.migrations_dir())
    abandoned = db.abandon_unfinished_ticks(ctx.conn)
    tick_id = db.start_tick(ctx.conn, dry_run=dry_run)
    log = logs.for_tick(tick_id)
    log.info("tick started", extra={"dry_run": dry_run, "repo": ctx.repo, "migrations_applied": applied})
    if abandoned:
        log.warning("closed ticks left running by a dead tick process", extra={"abandoned_ticks": abandoned})

    def finish(status: str, summary: str) -> Outcome:
        db.finish_tick(ctx.conn, tick_id, status, summary)
        log.info("tick finished", extra={"status": status, "summary": summary})
        return Outcome(tick_id, status, summary)

    try:
        capacity = reconcile(ctx, log)
    except treehouse.TreehouseError as e:
        log.exception("reconcile failed", extra={"error": str(e)})
        return finish("reconcile_failed", str(e))
    for item in attention.from_runs(ctx.conn):
        db.record_decision(ctx.conn, tick_id, item.ticket_key, f"{attention.ACTION_PREFIX}{item.reason}", item.detail)

    now = datetime.now(UTC)
    block = prompts.state_block(
        ctx.config,
        ctx.repo_root,
        tick_id=tick_id,
        dry_run=dry_run,
        capacity=capacity,
        running=db.running_runs(ctx.conn),
        tickets=db.open_tickets(ctx.conn),
        last_runs=db.latest_runs(ctx.conn),
        attempts=policy.attempts(ctx.conn),
        fix_ci_cooldowns=policy.fix_ci_cooldowns(ctx.conn, ctx.config, now),
        now=now,
    )
    prompt = prompts.render_overseer(ctx.config, block)
    failure = _run_overseer(ctx, tick_id, prompt, dry_run=dry_run, log=log)
    if failure is not None:
        return finish("overseer_failed", failure)

    actions = Counter(str(d["action"]) for d in db.decisions_for_tick(ctx.conn, tick_id))
    counts = ", ".join(f"{action}={n}" for action, n in sorted(actions.items())) or "none"
    return finish("ok", f"{'dry run; ' if dry_run else ''}{actions.total()} decisions: {counts}")


def reconcile(ctx: Context, log: logs.TickAdapter) -> prompts.Capacity:
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

    capacity = prompts.Capacity(max_workers=ctx.config.capacity.max_workers, running=len(running))
    log.info("reconciled", extra={"running": capacity.running, "available": capacity.available})
    return capacity


def _run_overseer(ctx: Context, tick_id: int, prompt: str, *, dry_run: bool, log: logs.TickAdapter) -> str | None:
    """Run `overseer_cmd`. Returns None on success, else why it failed. Output goes to `<state_dir>/ticks/<id>.log`."""
    argv = render_command(ctx.config.runtime.overseer_cmd, prompt)
    timeout_minutes = ctx.config.runtime.overseer_timeout_minutes
    log.info("running overseer", extra={"cmd": argv[0], "timeout_minutes": timeout_minutes})
    try:
        result = ctx.runner.run(
            argv,
            cwd=ctx.repo_root,
            env={TICK_ID_ENV: str(tick_id)},
            timeout=timeout_minutes * 60,
        )
    except procs.ProcError as e:
        log.exception("overseer could not start", extra={"error": str(e)})
        return str(e)

    out_dir = ctx.state_dir / "ticks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tick_id}.log"
    logs.write_private(out_path, f"{result.stdout}\n--- stderr ---\n{result.stderr}")

    lines = [line.strip().strip("`").strip() for line in result.stdout.splitlines() if line.strip()]
    if result.timed_out:
        failure = f"overseer timed out after {timeout_minutes} minutes"
    elif result.returncode != 0:
        failure = f"overseer exited {result.returncode}"
    elif not lines or lines[-1].lower() != DONE_LINE:
        failure = f"overseer did not end with {DONE_LINE!r}"
    else:
        return None
    log.error("overseer failed", extra={"reason": failure, "output": str(out_path), "dry_run": dry_run})
    return failure
