"""One tick of the loop (DESIGN §6): lock, migrate, reconcile, run the overseer, close the tick.

Attention rendering (step 6) arrives with `attention.py` in M3. Returning stale leases and detecting dead workers in
reconcile arrive with dispatch in M2; until then reconcile only reads the pool and logs what it would do.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy import db, lock, logs, procs, prompts, resources, treehouse
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
            return _locked(ctx, dry_run=dry_run)
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

    block = prompts.state_block(
        ctx.config,
        ctx.repo_root,
        tick_id=tick_id,
        dry_run=dry_run,
        capacity=capacity,
        running=db.running_runs(ctx.conn),
        tickets=db.open_tickets(ctx.conn),
    )
    prompt = prompts.render_overseer(ctx.config, block)
    failure = _run_overseer(ctx, tick_id, prompt, dry_run=dry_run, log=log)
    if failure is not None:
        return finish("overseer_failed", failure)

    actions = Counter(str(d["action"]) for d in db.decisions_for_tick(ctx.conn, tick_id))
    counts = ", ".join(f"{action}={n}" for action, n in sorted(actions.items())) or "none"
    return finish("ok", f"{'dry run; ' if dry_run else ''}{actions.total()} decisions: {counts}")


def reconcile(ctx: Context, log: logs.TickAdapter) -> prompts.Capacity:
    """Read the pool and running workers; return the capacity left for this tick."""
    running = db.running_runs(ctx.conn)
    leases = {str(r["lease_id"]) for r in running}
    for slot in treehouse.status(ctx.runner):
        if slot.canopy_key is not None and slot.lease_id and slot.lease_id not in leases:
            log.warning(
                "canopy lease with no running worker; not returned until M2",
                extra={"slot": str(slot.path), "lease_holder": slot.lease_holder, "lease_id": slot.lease_id},
            )
    capacity = prompts.Capacity(max_workers=ctx.config.max_workers, running=len(running))
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
    _write_private(out_path, f"{result.stdout}\n--- stderr ---\n{result.stderr}")

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


def _write_private(path: Path, text: str) -> None:
    """Write `text` to `path`, readable only by the operator (TRUST_MODEL T2).

    The mode is set on the open file, so a file that already existed with a wider mode is narrowed too, and a symlink
    at `path` is refused rather than followed.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(text)
