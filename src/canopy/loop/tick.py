"""One tick of the loop (DESIGN §6): lock, migrate, reconcile, run the overseer, close the tick, publish attention."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from canopy.core import db, prompts, treehouse
from canopy.core.config import render_command
from canopy.infra import lock, logs, procs, resources
from canopy.loop import attention, state
from canopy.runs import policy, reconcile

if TYPE_CHECKING:
    from canopy.core.context import Context

TICK_ID_ENV = "CANOPY_TICK_ID"
DONE_LINE = "tick complete"


@dataclass(frozen=True)
class Outcome:
    """How a tick ended."""

    tick_id: int | None
    status: str  # ok | skipped | overseer_failed | reconcile_failed | lock_busy
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
        capacity = reconcile.run(ctx, log)
    except treehouse.TreehouseError as e:
        log.exception("reconcile failed", extra={"error": str(e)})
        return finish("reconcile_failed", str(e))
    for item in attention.from_runs(ctx.conn):
        db.record_decision(ctx.conn, tick_id, item.ticket_key, f"{attention.ACTION_PREFIX}{item.reason}", item.detail)

    now = datetime.now(UTC)
    block = state.state_block(
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

    decisions = db.decisions_for_tick(ctx.conn, tick_id)
    prefix = "dry run; " if dry_run else ""
    # A tick-wide skip (mcp_unavailable, tracker_unsupported) means the overseer could not see the world. Closing it
    # `ok` would make its empty list the attention list and notify every open item as resolved (D037).
    skips = [str(d["rationale"]) for d in decisions if d["ticket_key"] is None and d["action"] == "skip"]
    if skips:
        return finish("skipped", f"{prefix}overseer skipped the tick: {'; '.join(skips)}")
    actions = Counter(str(d["action"]) for d in decisions)
    counts = ", ".join(f"{action}={n}" for action, n in sorted(actions.items())) or "none"
    return finish("ok", f"{prefix}{actions.total()} decisions: {counts}")


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
