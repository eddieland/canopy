"""One tick of the loop (DESIGN §6): lock, migrate, reconcile, check `canopy`, run and check the overseer, publish."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from canopy.chores import reconcile as chore_reconcile
from canopy.core import (
    agent_output,
    chore_view,
    conversation,
    db,
    definitions,
    drafts,
    notice,
    plans,
    pools,
    progress,
)
from canopy.core.config import render_command
from canopy.core.items import one_line
from canopy.core.vocab import TickStatus
from canopy.infra import lock, logs, procs, resources
from canopy.loop import attention, duties, state
from canopy.memory import attention as memory_attention
from canopy.memory import reconcile as memory_reconcile
from canopy.reviews import reconcile as review_reconcile
from canopy.reviews import view as review_view
from canopy.runs import drafted, policy, reconcile

if TYPE_CHECKING:
    from collections.abc import Iterable

    from canopy.core import records
    from canopy.core.context import Context

TICK_ID_ENV = conversation.TICK_ID_ENV
# A word no model writes by chance, alone on a line of the overseer's final message (DESIGN §6).
DONE_LINE = "CANOPY_TICK_DONE"
# The overseer acts only through `canopy`, so a tick runs this as the overseer would, for nothing, before paying for
# the overseer (DESIGN §6). When it fails, the tick closes with this status and raises an item of the same name.
CANOPY_CHECK = ("canopy", "--version")
CANOPY_CHECK_TIMEOUT_SECONDS = 60
# How long a ticket marked done stays in the state block's `recently_done`, so the overseer leaves it out while a human
# has yet to close it in the tracker (DESIGN §7). One still open after that is read again and marked done again, which
# lists it for as long once more.
RECENTLY_DONE_DAYS = 30
# How a tick ended: the status it closed its row with, or, with no row, `lock_busy` when another tick held the lock and
# `error` when `canopy loop` caught the tick raising.
type OutcomeStatus = TickStatus | Literal["lock_busy", "error"]
# What ended `canopy loop`'s wait before its deadline: the operator's act (a message, a ticket started or stopped, a
# grant, a notice set or cleared), a run ending, the operator pressing the loop's tick-now key, or the operator asking
# from the web UI.
type Woken = Literal["message", "starts", "grant", "notice", "run", "key", "web"]
# What started a tick the loop ran, recorded on its row (`ticks.woken_by`): the loop starting, a wait that ran its
# length, one a gate shortened, or what ended one early.
type WokenBy = Woken | Literal["start", "timer", "gate"]
# How the overseer's session title says what started its tick (DESIGN §13); a tick run by hand has no `WokenBy`.
_WOKEN_TITLES: dict[WokenBy | None, str] = {
    None: "by hand",
    "start": "loop start",
    "timer": "timer",
    "gate": "gate",
    "message": "message",
    "starts": "start or stop",
    "grant": "grant",
    "notice": "notice",
    "run": "run ended",
    "key": "asked",
    "web": "asked",
}


@dataclass(frozen=True)
class Outcome:
    """How a tick ended."""

    tick_id: int | None
    status: OutcomeStatus
    summary: str
    usage: agent_output.Usage | None = None  # what the overseer cost, when the runtime reported it


def run(ctx: Context, *, dry_run: bool, woken_by: WokenBy | None = None) -> Outcome:
    """Run one tick: take the lock, then everything in DESIGN §6. A busy lock is an outcome, not an error.

    `woken_by` is what started a tick `canopy loop` runs, for the overseer's session title; None for one run by hand.

    Returns:
        How the tick ended: its id, status, summary, and what the overseer cost. A busy lock is `lock_busy`, with no
        tick id.
    """
    try:
        with lock.hold(ctx.lock_path):
            outcome = _locked(ctx, dry_run=dry_run, woken_by=woken_by)
            # After the tick is closed: the list is the latest `ok` tick's, and this tick may be it.
            attention.publish(ctx, logs.for_tick(outcome.tick_id))
            return outcome
    except lock.LockBusyError:
        logs.for_tick(None).info("tick skipped: another tick holds the lock", extra={"lock": str(ctx.lock_path)})
        return Outcome(None, "lock_busy", "another tick holds the lock")


def state_block(
    ctx: Context, *, tick_id: int, dry_run: bool, now: datetime, reconciled: reconcile.Reconciled, query_due: bool
) -> str:
    """Read the journal for tick `tick_id` and render the overseer's state block from it (DESIGN §6 step 4).

    `reconciled` is what reconcile left: the capacity, and each repository's leased slots.

    Returns:
        The `## State` section, the overseer's whole message.
    """
    block, _, _ = _render(ctx, tick_id=tick_id, dry_run=dry_run, now=now, reconciled=reconciled, query_due=query_due)
    return block


def session_title(tick_id: int, woken_by: WokenBy | None, *, tickets: int, running: int, open_items: int) -> str:
    """The overseer's session title: what started tick `tick_id`, then what it faces (DESIGN §13).

    `tickets` counts the open tickets its state block lists, `running` the worker runs still running, and `open_items`
    the attention list's items.

    Returns:
        `tick <id> · <what started it> · <what it faces>`, such as `tick 412 · run ended · 2 tickets, 1 running`.
    """
    faces = [
        f"{tickets} ticket{'' if tickets == 1 else 's'}" if tickets else "",
        f"{running} running" if running else "",
        f"{open_items} need{'s' if open_items == 1 else ''} you" if open_items else "",
    ]
    return f"tick {tick_id} · {_WOKEN_TITLES[woken_by]} · {', '.join(f for f in faces if f) or 'nothing open'}"


def _render(
    ctx: Context,
    *,
    tick_id: int,
    dry_run: bool,
    now: datetime,
    reconciled: reconcile.Reconciled,
    query_due: bool,
    woken_by: WokenBy | None = None,
) -> tuple[str, duties.Duties, str]:
    """Render the state block, and read what it asks of the overseer from the same journal reads (DESIGN §6 step 5).

    Returns:
        The `## State` section, the overseer's duties this tick, and its session title, which `woken_by` starts.
    """
    running = db.running_runs(ctx.conn, "runs")
    last_runs = db.latest_runs(ctx.conn)
    # A stopped ticket waits on the operator alone: listed by key, it gets no decision every tick (DESIGN §22).
    stopped = conversation.stopped(ctx.conn)
    tickets = [t for t in db.open_tickets(ctx.conn) if t.key not in stopped]
    private = {t.key: found for t in tickets if (found := conversation.state_section(ctx.conn, t)) is not None}
    operator = {t.key: found for t in tickets if (found := conversation.operator_section(ctx.conn, t)) is not None}
    planned = _plans(ctx, tickets)
    recently_done = db.recently_done(ctx.conn, db.format_time(now - timedelta(days=RECENTLY_DONE_DAYS)))
    chores = chore_view.state_section(chore_view.states(ctx.conn, ctx.config, ctx.workspace), now)
    shown = [int(r["id"]) for r in [*running, *last_runs.values()]]
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
        stopped=stopped,
        recently_done=recently_done,
        units=db.all_units(ctx.conn),
        last_runs=last_runs,
        run_slots=db.all_run_slots(ctx.conn, shown),
        run_reasons=db.run_reasons(ctx.conn, shown),
        attempts=policy.attempts(ctx.conn),
        grants=policy.grants(ctx.conn),
        ci_cooldowns=policy.ci_cooldowns(ctx.conn, ctx.config, now),
        now=now,
        split_attempts=policy.ticket_attempts(ctx.conn, policy.SPLIT),
        split_children=db.open_split_children(ctx.conn),
        chores=chores,
        reviews=review_view.state_section(ctx.conn, ctx.config, now),
        notices=notice.recent(ctx.conn, now),
        private=private,
        operator=operator,
        planned=planned,
        mirror_delimiter=conversation.body_delimiter(),
        attention=attention.for_overseer(ctx.conn),
        query_due=query_due,
        operator_sent=drafts.sent_by_pr(ctx.conn),
    )
    owed = duties.owed(
        ctx.conn,
        tick_id,
        query_due=query_due,
        tickets=tickets,
        stopped=stopped,
        recently_done=recently_done,
        chores=chores,
    )
    title = session_title(
        tick_id, woken_by, tickets=len(tickets), running=len(running), open_items=len(attention.current(ctx.conn))
    )
    return block, owed, title


def _plans(ctx: Context, tickets: Iterable[records.Ticket]) -> dict[str, plans.PlanState]:
    """Return each ticket's plan for the state block, by key: only the tickets plans touch (DESIGN §25)."""
    done = policy.ticket_attempts(ctx.conn, policy.PLAN)
    granted = policy.ticket_grants(ctx.conn, policy.PLAN)
    base = policy.limits(ctx.config)[policy.PLAN]
    found: dict[str, plans.PlanState] = {}
    for t in tickets:
        limit = base + granted.get(t.key, 0)
        section = plans.state_section(ctx.conn, ctx.config.policy.plan, t, attempts=done.get(t.key, 0), limit=limit)
        if section is not None:
            found[t.key] = section
    return found


def _locked(ctx: Context, *, dry_run: bool, woken_by: WokenBy | None) -> Outcome:
    applied = db.migrate(ctx.conn, resources.migrations_dir())
    abandoned = db.abandon_unfinished_ticks(ctx.conn)
    tick_id = db.start_tick(ctx.conn, dry_run=dry_run)
    log = logs.for_tick(tick_id)
    log.info("tick started", extra={"dry_run": dry_run, "repo": ctx.repo, "migrations_applied": applied})
    if abandoned:
        log.warning("closed ticks left running by a dead tick process", extra={"abandoned_ticks": abandoned})

    def finish(status: TickStatus, summary: str, usage: agent_output.Usage | None = None) -> Outcome:
        db.finish_tick(ctx.conn, tick_id, status, summary)
        spent = usage.spent() if usage is not None else {}
        log.info("tick finished", extra={"status": status, "summary": summary, **spent})
        return Outcome(tick_id, status, summary, usage)

    try:
        # Reviews first: a review whose `_review` is gone returns its slot, and then frees worker capacity.
        review_reconcile.run(ctx, log)
        reconciled = reconcile.run(ctx, log)
    except pools.PoolError as e:
        log.exception("reconcile failed", extra={"error": str(e)})
        return finish(TickStatus.RECONCILE_FAILED, str(e))
    chore_reconcile.run(ctx, log)
    memory_reconcile.run(ctx, log)
    drafted.reconcile(ctx, log)
    # Before anything reads a message or a run: the harness items and the state block see at least every message, and
    # every run that started or ended, up to here. Idle pacing reads the time (DESIGN §6).
    db.set_tick_read(ctx.conn, tick_id)
    _record_harness_items(ctx, tick_id)

    now = datetime.now(UTC)
    query_due = _query_due(ctx, now)
    db.set_tick_query(ctx.conn, tick_id, due=query_due)
    block, owed, title = _render(
        ctx, tick_id=tick_id, dry_run=dry_run, now=now, reconciled=reconciled, query_due=query_due, woken_by=woken_by
    )
    unavailable = _check_canopy(ctx, tick_id, log)
    if unavailable is not None:
        detail = f"{unavailable}; the overseer did not run. Make `canopy --version` work where the loop runs"
        db.record_decision(ctx.conn, tick_id, None, f"{attention.ACTION_PREFIX}{attention.UNAVAILABLE}", detail)
        return finish(TickStatus.CANOPY_UNAVAILABLE, unavailable)
    # The state block is the whole message: the prompt is in the overseer's definition, cached across ticks (DESIGN §6).
    failure, usage = _run_overseer(ctx, tick_id, block, title, dry_run=dry_run, log=log)
    if failure is not None:
        return finish(TickStatus.OVERSEER_FAILED, failure, usage)

    decisions = db.decisions_for_tick(ctx.conn, tick_id)
    prefix = "dry run; " if dry_run else ""
    # A tick-wide skip (mcp_unavailable, tracker_unsupported) means the overseer could not see the world. Closing it
    # `ok` would make its empty list the attention list and notify every open item as resolved.
    skips = [d.rationale for d in decisions if d.ticket_key is None and d.action == "skip"]
    if skips:
        return finish(TickStatus.SKIPPED, f"{prefix}overseer skipped the tick: {'; '.join(skips)}", usage)
    # A duty left undone fails the tick as a missing done line does: closing it `ok` would resolve the items of every
    # ticket it left out and count a query it never ran (DESIGN §6 step 5).
    undone = duties.undone(ctx.conn, tick_id, owed)
    if undone:
        log.error("overseer left duties undone", extra={"undone": undone, "dry_run": dry_run})
        return finish(TickStatus.OVERSEER_FAILED, f"{prefix}overseer left duties undone: {'; '.join(undone)}", usage)
    actions = Counter(d.action for d in decisions)
    counts = ", ".join(f"{action}={n}" for action, n in sorted(actions.items())) or "none"
    return finish(TickStatus.OK, f"{prefix}{actions.total()} decisions: {counts}", usage)


def _query_due(ctx: Context, now: datetime) -> bool:
    """Whether this tick runs the tracker query (DESIGN §7, Spacing the query).

    Every tick does with `tracker.query_every_minutes` at 0. Otherwise one does once that long has passed since the
    newest live `ok` tick that ran it started, or when none has.

    Returns:
        True if the overseer runs the query this tick.
    """
    every = ctx.config.tracker.query_every_minutes
    if every == 0:
        return True
    last = db.last_query_at(ctx.conn)
    return last is None or now - db.parse_time(last) >= timedelta(minutes=every)


def _record_harness_items(ctx: Context, tick_id: int) -> None:
    """Record the attention items the harness raises itself, every tick their cause holds (DESIGN §14)."""
    for item in attention.from_runs(ctx.conn):
        db.record_decision(ctx.conn, tick_id, item.ticket_key, f"{attention.ACTION_PREFIX}{item.reason}", item.detail)
    # A private ticket's question reaches the operator here: it is on no tracker (DESIGN §22). So does a planner's on a
    # public ticket, since the planner writes nothing to the ticket (DESIGN §25).
    for waiting in [*conversation.awaiting(ctx.conn), *plans.awaiting(ctx.conn)]:
        db.record_decision(
            ctx.conn,
            tick_id,
            waiting.key,
            f"{attention.ACTION_PREFIX}awaiting_reply",
            attention.awaiting_detail(waiting),
        )
    for remembered in memory_attention.items(ctx.conn, ctx.config):
        action = f"{attention.ACTION_PREFIX}{remembered.reason}"
        db.record_decision(ctx.conn, tick_id, remembered.ticket_key, action, remembered.detail)
    for draft in drafted.waiting(ctx.conn):
        action = f"{attention.ACTION_PREFIX}{drafted.WAITING_REASON}"
        db.record_decision(ctx.conn, tick_id, draft.ticket_key, action, draft.detail, repo=draft.repo)
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


def _check_canopy(ctx: Context, tick_id: int, log: logs.TickAdapter) -> str | None:
    """Run `canopy --version` as the overseer would run `canopy`: from its PATH, cwd, and environment (DESIGN §6).

    A launcher whose environment is gone (an uninstall, a cleared cache) fails to start as a missing one does.

    Returns:
        Why `canopy` does not work for the overseer, or None when it does.
    """
    try:
        result = ctx.runner.run(
            CANOPY_CHECK, cwd=ctx.repo_root, env={TICK_ID_ENV: str(tick_id)}, timeout=CANOPY_CHECK_TIMEOUT_SECONDS
        )
    except procs.ProcError as e:
        failure = f"`canopy` does not start for the overseer: {e}"
    else:
        if result.timed_out:
            failure = f"`canopy --version` did not finish in {CANOPY_CHECK_TIMEOUT_SECONDS} seconds"
        elif result.returncode != 0:
            said = one_line(result.stderr or result.stdout)[-300:]
            failure = f"`canopy --version` exited {result.returncode}" + (f": {said}" if said else "")
        else:
            return None
    log.error("overseer not started", extra={"reason": failure})
    return failure


def _run_overseer(
    ctx: Context, tick_id: int, block: str, title: str, *, dry_run: bool, log: logs.TickAdapter
) -> tuple[str | None, agent_output.Usage | None]:
    """Run `overseer_cmd` with the state block `block` as its `{prompt}`, and `title` as its `{title}`.

    Output goes to `<state_dir>/ticks/<id>.log` as the overseer prints it, its stderr after it once it ends, and the
    block to `<id>.prompt` beside it first, for the transcript's first model call (DESIGN §22). What its events report
    so far is recorded on the tick as they come, so a running tick shows its session and spend; the session and cost
    again when the overseer ends, failed or not.

    Returns:
        Why it failed, None on success, and what it cost if the runtime reported it.
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
    argv = render_command(ctx.config.runtime.overseer_cmd, block, definitions_dir, title)
    timeout_minutes = ctx.config.runtime.overseer_timeout_minutes
    log.info("running overseer", extra={"cmd": argv[0], "timeout_minutes": timeout_minutes})
    out_dir = ctx.state_dir / "ticks"
    out_dir.mkdir(parents=True, exist_ok=True)
    logs.write_private(out_dir / f"{tick_id}.prompt", block)
    out_path = out_dir / f"{tick_id}.log"
    with logs.open_private(out_path) as out:
        watch = progress.Progress(ctx.conn, "ticks", tick_id, out, log, agent="overseer", fields={})
        try:
            result = ctx.runner.run(
                argv,
                cwd=ctx.repo_root,
                env={TICK_ID_ENV: str(tick_id)},
                timeout=timeout_minutes * 60,
                on_line=watch,
            )
        except procs.ProcError as e:
            # It printed nothing, so it keeps no output, as a tick whose overseer never ran keeps none.
            out_path.unlink(missing_ok=True)
            log.exception("overseer could not start", extra={"error": str(e)})
            return str(e), None
        out.write(f"\n--- stderr ---\n{result.stderr}")

    output = agent_output.read(result.stdout)
    db.set_tick_report(
        ctx.conn, tick_id, output.session_id, output.usage, digest=definitions_dir.name, tools=output.tools
    )
    if result.timed_out:
        failure = f"overseer timed out after {timeout_minutes} minutes"
    elif result.returncode != 0:
        failure = f"overseer exited {result.returncode}"
    elif not _done(output.last):
        failure = f"overseer's final message has no {DONE_LINE} line"
    else:
        return None, output.usage
    log.error("overseer failed", extra={"reason": failure, "output": str(out_path), "dry_run": dry_run})
    return failure, output.usage


def _done(message: str) -> bool:
    """Whether `message`, the overseer's final message, has the done line.

    Text around that line is allowed: models summarize what they did. Only the final message is passed, so a run cut
    off after an earlier message that named the token still fails.

    Returns:
        True if a line, trimmed of whitespace and backticks, is `DONE_LINE` and nothing else.
    """
    return any(line.strip().strip("`").strip() == DONE_LINE for line in message.splitlines())
