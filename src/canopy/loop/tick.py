"""One tick of the loop (DESIGN §6): lock, migrate, reconcile, run the overseer, close the tick, publish attention."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from canopy.chores import reconcile as chore_reconcile
from canopy.chores import view as chore_view
from canopy.core import agent_output, conversation, db, definitions, prompts, treehouse
from canopy.core.config import render_command
from canopy.infra import lock, logs, procs, resources
from canopy.loop import attention, state
from canopy.reviews import reconcile as review_reconcile
from canopy.reviews import view as review_view
from canopy.runs import policy, reconcile

if TYPE_CHECKING:
    from canopy.core.context import Context

TICK_ID_ENV = conversation.TICK_ID_ENV
DONE_LINE = "tick complete"


@dataclass(frozen=True)
class Outcome:
    """How a tick ended."""

    tick_id: int | None
    status: str  # ok | skipped | overseer_failed | reconcile_failed | lock_busy
    summary: str
    usage: agent_output.Usage | None = None  # what the overseer cost, when the runtime reported it


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

    def finish(status: str, summary: str, usage: agent_output.Usage | None = None) -> Outcome:
        db.finish_tick(ctx.conn, tick_id, status, summary)
        spent = {"cost_usd": usage.cost_usd, "tokens": usage.tokens} if usage is not None else {}
        log.info("tick finished", extra={"status": status, "summary": summary, **spent})
        return Outcome(tick_id, status, summary, usage)

    try:
        # Reviews first: a review whose `_review` is gone returns its slot, and then frees worker capacity.
        review_reconcile.run(ctx, log)
        reconciled = reconcile.run(ctx, log)
    except treehouse.TreehouseError as e:
        log.exception("reconcile failed", extra={"error": str(e)})
        return finish("reconcile_failed", str(e))
    chore_reconcile.run(ctx, log)
    _record_harness_items(ctx, tick_id)

    now = datetime.now(UTC)
    running = db.running_runs(ctx.conn)
    last_runs = db.latest_runs(ctx.conn)
    single = ctx.workspace.single
    tickets = db.open_tickets(ctx.conn)
    private = {str(t["key"]): found for t in tickets if (found := conversation.state_section(ctx.conn, t)) is not None}
    block = state.state_block(
        ctx.config,
        ctx.repo_root,
        tick_id=tick_id,
        dry_run=dry_run,
        capacity=reconciled.capacity,
        workspace=ctx.workspace,
        leased=reconciled.leased,
        running=running,
        tickets=tickets,
        units=db.all_units(ctx.conn),
        last_runs=last_runs,
        run_slots=db.all_run_slots(ctx.conn, [int(r["id"]) for r in [*running, *last_runs.values()]]),
        attempts=policy.attempts(ctx.conn, single=single),
        fix_ci_cooldowns=policy.fix_ci_cooldowns(ctx.conn, ctx.config, now, single=single),
        now=now,
        split_attempts=policy.split_attempts(ctx.conn),
        split_children=db.open_split_children(ctx.conn),
        chores=chore_view.state_section(chore_view.states(ctx.conn, ctx.config, ctx.workspace), now),
        reviews=review_view.state_section(ctx.conn, ctx.config, now),
        private=private,
        mirror_delimiter=conversation.body_delimiter(),
    )
    prompt = prompts.render_overseer(ctx.config, block)
    failure, usage = _run_overseer(ctx, tick_id, prompt, dry_run=dry_run, log=log)
    if failure is not None:
        return finish("overseer_failed", failure, usage)

    decisions = db.decisions_for_tick(ctx.conn, tick_id)
    prefix = "dry run; " if dry_run else ""
    # A tick-wide skip (mcp_unavailable, tracker_unsupported) means the overseer could not see the world. Closing it
    # `ok` would make its empty list the attention list and notify every open item as resolved (D037).
    skips = [str(d["rationale"]) for d in decisions if d["ticket_key"] is None and d["action"] == "skip"]
    if skips:
        return finish("skipped", f"{prefix}overseer skipped the tick: {'; '.join(skips)}", usage)
    actions = Counter(str(d["action"]) for d in decisions)
    counts = ", ".join(f"{action}={n}" for action, n in sorted(actions.items())) or "none"
    return finish("ok", f"{prefix}{actions.total()} decisions: {counts}", usage)


def _record_harness_items(ctx: Context, tick_id: int) -> None:
    """Record the attention items the harness raises itself, every tick their cause holds (DESIGN §14)."""
    for item in attention.from_runs(ctx.conn):
        db.record_decision(ctx.conn, tick_id, item.ticket_key, f"{attention.ACTION_PREFIX}{item.reason}", item.detail)
    # A private ticket's question reaches the operator here: it is on no tracker (DESIGN §22).
    for waiting in conversation.awaiting(ctx.conn):
        db.record_decision(
            ctx.conn,
            tick_id,
            waiting.key,
            f"{attention.ACTION_PREFIX}awaiting_reply",
            attention.awaiting_detail(waiting),
        )
    for failed in chore_view.failed_items(ctx.conn, ctx.config, ctx.workspace):
        action = f"{attention.ACTION_PREFIX}{chore_view.FAILED_REASON}"
        db.record_decision(ctx.conn, tick_id, None, action, failed.detail, chore=failed.chore)
    for repo in ctx.workspace.repos:
        # A tick never clones: a repository in the map with no clone waits for the operator (DESIGN §18).
        if not repo.cloned:
            detail = f"{repo.path} has no clone; run `canopy workspace sync` in {ctx.repo_root}"
            db.record_decision(
                ctx.conn, tick_id, None, f"{attention.ACTION_PREFIX}repo_missing", detail, repo=repo.name
            )


def _run_overseer(
    ctx: Context, tick_id: int, prompt: str, *, dry_run: bool, log: logs.TickAdapter
) -> tuple[str | None, agent_output.Usage | None]:
    """Run `overseer_cmd`. Returns why it failed, None on success, and what it cost if the runtime reported it.

    Output goes to `<state_dir>/ticks/<id>.log`. The session and cost are recorded on the tick, failed or not.
    """
    # OpenCode reads the repository's config too: it must not define an agent of canopy's (D044).
    shadowing = definitions.shadowing(ctx.repo_root)
    if shadowing:
        failure = definitions.shadowing_message(shadowing)
        log.error("overseer not started", extra={"reason": failure, "dry_run": dry_run})
        return failure, None
    try:
        definitions_dir = definitions.ensure(ctx.state_dir, ctx.config)
    except definitions.DefinitionsError as e:
        log.error("overseer not started", extra={"reason": str(e), "dry_run": dry_run})  # noqa: TRY400
        return str(e), None
    argv = render_command(ctx.config.runtime.overseer_cmd, prompt, definitions_dir)
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
        return str(e), None

    out_dir = ctx.state_dir / "ticks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tick_id}.log"
    logs.write_private(out_path, f"{result.stdout}\n--- stderr ---\n{result.stderr}")

    output = agent_output.read(result.stdout)
    db.set_tick_report(ctx.conn, tick_id, output.session_id, output.usage)
    lines = [line.strip().strip("`").strip() for line in output.text.splitlines() if line.strip()]
    if result.timed_out:
        failure = f"overseer timed out after {timeout_minutes} minutes"
    elif result.returncode != 0:
        failure = f"overseer exited {result.returncode}"
    elif not lines or lines[-1].lower() != DONE_LINE:
        failure = f"overseer did not end with {DONE_LINE!r}"
    else:
        return None, output.usage
    log.error("overseer failed", extra={"reason": failure, "output": str(out_path), "dry_run": dry_run})
    return failure, output.usage
