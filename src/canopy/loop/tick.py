"""One tick of the loop (DESIGN §6): lock, migrate, reconcile, check `canopy`, run and check the overseer, publish.

A live tick starts the operator's queued one-off tasks after reconcile, in code, before the overseer (DESIGN §36). A
tick that closes `ok` notes, on each ticket, what it did about the operator's messages it read (`acknowledge.py`).
"""

from __future__ import annotations

import shutil
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, Protocol, assert_never

from canopy.chores import reconcile as chore_reconcile
from canopy.core import (
    chore_view,
    connector_runs,
    conversation,
    db,
    definitions,
    drafts,
    feedback_plans,
    follow_ups,
    notice,
    plans,
    pools,
    progress,
    run_models,
    run_offers,
)
from canopy.core.config import render_command
from canopy.core.items import one_line
from canopy.core.vocab import Decider, TickStatus
from canopy.infra import lock, logs, procs, resources
from canopy.loop import (
    acknowledge,
    archive,
    attention,
    connectors,
    duties,
    gc_pass,
    harness,
    observations,
    phases,
    state,
)
from canopy.memory import attention as memory_attention
from canopy.memory import reconcile as memory_reconcile
from canopy.reviews import reconcile as review_reconcile
from canopy.reviews import view as review_view
from canopy.runs import drafted, policy, reconcile
from canopy.runs import tasks as task_starts
from canopy.runtime import project_config, stdout

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from canopy.core import records
    from canopy.core.context import Context
    from canopy.runtime.report import Usage

TICK_ID_ENV = conversation.TICK_ID_ENV
# A word no model writes by chance, alone on a line of the overseer's final message (DESIGN §6).
DONE_LINE = "CANOPY_TICK_DONE"
# The overseer acts only through `canopy`, so a tick runs this as the overseer would, for nothing, before paying for
# the overseer (DESIGN §6). When it fails, the tick closes with this status and raises an item of the same name.
CANOPY_CHECK = ("canopy", "--version")
CANOPY_CHECK_TIMEOUT_SECONDS = 60
MIB = 1024 * 1024
# How long a ticket marked done stays in the state block's `recently_done` while the query still finds it, so the
# overseer leaves it out while a human has yet to close it in the tracker (DESIGN §7). One still open after that is read
# again and marked done again, which lists it for as long once more.
RECENTLY_DONE_DAYS = 30
#: How many of the runtime's errors a failed overseer's summary names; past it, the first and last, the rest counted.
MAX_ERRORS_NAMED = 3
# How a tick ended: the status it closed its row with, or, with no row, `lock_busy` when another tick held the lock and
# `error` when `canopy loop` caught the tick raising before it had one or after it closed it.
type OutcomeStatus = TickStatus | Literal["lock_busy", "error"]
# What ended `canopy loop`'s wait before its deadline: the operator's act (a message, a ticket started or stopped, a
# grant, a task submitted, replied to, or stopped, a notice set or cleared), a run ending, the operator pressing the
# loop's tick-now key, or the operator asking from the web UI.
type Woken = Literal["message", "starts", "grant", "task", "notice", "run", "key", "web"]
# What started a tick the loop ran, recorded on its row (`ticks.woken_by`): the loop starting, a wait that ran its
# length, one a gate shortened, or what ended one early.
type WokenBy = Woken | Literal["start", "timer", "gate"]


@dataclass(frozen=True)
class Outcome:
    """How a tick ended."""

    tick_id: int | None
    status: OutcomeStatus
    summary: str
    usage: Usage | None = None  # what the overseer cost, when the runtime reported it


def run(ctx: Context, *, dry_run: bool, woken_by: WokenBy | None = None, ui: str | None = None) -> Outcome:
    """Run one tick: take the lock, then everything in DESIGN §6. A busy lock is an outcome, not an error.

    `woken_by` is what started a tick `canopy loop` runs, for the overseer's session title; None for one run by hand.
    `ui` is where notifications' links open the web UI, when the loop running the tick serves it; None links nothing.

    Returns:
        How the tick ended: its id, status, summary, and what the overseer cost. A busy lock is `lock_busy`, with no
        tick id.
    """
    try:
        with lock.hold(ctx.lock_path):
            outcome = _locked(ctx, dry_run=dry_run, woken_by=woken_by)
            # After the tick is closed: the list is the latest `ok` tick's, and this tick may be it.
            attention.publish(ctx, logs.for_tick(outcome.tick_id), ui=ui)
    except lock.LockBusyError:
        logs.for_tick(None).info("tick skipped: another tick holds the lock", extra={"lock": str(ctx.lock_path)})
        return Outcome(None, "lock_busy", "another tick holds the lock")
    # Which models served its overseer (DESIGN §13), out of the lock, so the read does not hold up the next tick; a dry
    # run spends no time beyond its overseer.
    if not dry_run and outcome.tick_id is not None:
        run_models.read_ended(ctx, "ticks", outcome.tick_id, logs.for_tick(outcome.tick_id))
    return outcome


def state_block(
    ctx: Context,
    *,
    tick_id: int,
    dry_run: bool,
    now: datetime,
    reconciled: reconcile.Reconciled,
    query_due: bool,
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
    return f"tick {tick_id} · {_woken_title(woken_by)} · {', '.join(f for f in faces if f) or 'nothing open'}"


def _woken_title(woken_by: WokenBy | None) -> str:
    match woken_by:
        case None:
            return "by hand"
        case "start":
            return "loop start"
        case "timer" | "gate" | "message" | "grant" | "task" | "notice":
            return woken_by
        case "starts":
            return "start or stop"
        case "run":
            return "run ended"
        case "key" | "web":
            return "asked"
        case _:
            assert_never(woken_by)


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
    # A ticket the harness decided is named with its decision, and nothing else of it is shown (DESIGN §37).
    by_harness = harness.recorded(ctx.conn, tick_id)
    decided = frozenset(str(d.ticket_key) for d in by_harness)
    tickets = [t for t in db.open_tickets(ctx.conn) if t.key not in stopped and t.key not in decided]
    private = {t.key: found for t in tickets if (found := conversation.state_section(ctx.conn, t)) is not None}
    operator = {t.key: found for t in tickets if (found := conversation.operator_section(ctx.conn, t)) is not None}
    planned = _plans(ctx, tickets)
    # Only those the query still finds open: one a human closed will not come back from it (DESIGN §7).
    found = duties.last_queried(ctx.conn)
    since = db.format_time(now - timedelta(days=RECENTLY_DONE_DAYS))
    recently_done = [t for t in db.recently_done(ctx.conn, since) if str(t["key"]) in found]
    chores = chore_view.state_section(chore_view.states(ctx.conn, ctx.config, ctx.workspace), now)
    shown = [*(int(r["id"]) for r in running), *(r.id for r in last_runs.values())]
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
        harness=harness.section(by_harness),
        units=db.all_units(ctx.conn),
        last_runs=last_runs,
        run_slots=db.all_run_slots(ctx.conn, shown),
        run_reasons=db.run_reasons(ctx.conn, shown),
        attempts=policy.attempts(ctx.conn),
        grants=policy.grants(ctx.conn),
        ci_cooldowns=policy.ci_cooldowns(ctx.conn, ctx.config, now),
        now=now,
        chores=chores,
        reviews=review_view.state_section(ctx.conn, ctx.config, now),
        notices=notice.recent(ctx.conn, now),
        private=private,
        operator=operator,
        planned=planned,
        feedback_planned=_feedback_plans(ctx, tickets, now),
        mirror_delimiter=conversation.body_delimiter(),
        attention=attention.for_overseer(ctx.conn),
        query_due=query_due,
        operator_sent=drafts.sent_by_pr(ctx.conn),
        observations=observations.section(ctx, tick_id, now, tickets, decided=decided),
    )
    owed = duties.owed(
        ctx.conn,
        tick_id,
        query_due=query_due,
        tickets=tickets,
        stopped=stopped,
        recently_done=recently_done,
        decided=decided,
        chores=chores,
    )
    title = session_title(
        tick_id,
        woken_by,
        tickets=len(tickets),
        running=len(running),
        open_items=len(attention.current(ctx.conn)),
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
        section = plans.state_section(ctx.conn, ctx.config.policy, t, attempts=done.get(t.key, 0), limit=limit)
        if section is not None:
            found[t.key] = section
    return found


def _feedback_plans(
    ctx: Context,
    tickets: Iterable[records.Ticket],
    now: datetime,
) -> dict[str, feedback_plans.FeedbackPlanState]:
    """Return each ticket's feedback plan for the state block, by key: only the tickets feedback plans touch (§32).

    After the tick's connectors read, so whether a waiting plan is stale is as of what they observed.
    """
    done = policy.feedback_plan_attempts(ctx.conn)
    granted = policy.grants(ctx.conn)
    units = db.all_units(ctx.conn)
    found: dict[str, feedback_plans.FeedbackPlanState] = {}
    for t in tickets:
        repos = [str(u.repo) for u in units.get(t.key, [])]
        attempts = {r: done.get(policy.unit(t.key, r), 0) for r in repos}
        limits = {r: policy.feedback_plan_limit(ctx.config, granted.get(policy.unit(t.key, r), {})) for r in repos}
        section = feedback_plans.state_section(ctx.conn, ctx.config, t, attempts=attempts, limits=limits, now=now)
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

    def finish(status: TickStatus, summary: str, usage: Usage | None = None) -> Outcome:
        _record_overseer(ctx, tick_id, log)
        db.finish_tick(ctx.conn, tick_id, status, summary)
        spent = usage.spent() if usage is not None else {}
        log.info("tick finished", extra={"status": status, "summary": summary, **spent})
        return Outcome(tick_id, status, summary, usage)

    try:
        return _steps(ctx, tick_id, log, finish, dry_run=dry_run, woken_by=woken_by)
    # Closed with what it raised, so the journal keeps why it failed when the logs do not. Should closing it raise too,
    # the next tick closes it `abandoned`.
    except Exception as e:
        log.exception("tick raised", extra={"error": str(e)})
        return finish(TickStatus.ERROR, f"{type(e).__name__}: {e}")


class _Finish(Protocol):
    """Closes the tick with its status and summary, and what the overseer cost, and returns its outcome."""

    def __call__(self, status: TickStatus, summary: str, usage: Usage | None = None) -> Outcome: ...


def _steps(
    ctx: Context,
    tick_id: int,
    log: logs.TickAdapter,
    finish: _Finish,
    *,
    dry_run: bool,
    woken_by: WokenBy | None,
) -> Outcome:
    """Run tick `tick_id` from reconcile to closing it, through `finish` (DESIGN §6 steps 2 to 5).

    Returns:
        How the tick ended.
    """
    if not dry_run:
        # First, so a tick whose reconcile fails, as one on a full disk may, still frees what retention lets go.
        gc_pass.run(ctx, tick_id, log)
    try:
        # Reviews first: a review whose `_review` is gone returns its slot, and then frees worker capacity.
        review_reconcile.run(ctx, log)
        reconciled = reconcile.run(ctx, log)
    except pools.PoolError as e:
        log.exception("reconcile failed", extra={"error": str(e)})
        return finish(TickStatus.RECONCILE_FAILED, str(e))
    chore_reconcile.run(ctx, log)
    memory_reconcile.run(ctx, log)
    if not dry_run:
        # The operator's tasks start in code, before the overseer, which never sees one: it plans around the slots
        # their runs hold (DESIGN §36). A dry tick starts none (D036).
        started = task_starts.start_queued(ctx, tick_id, log)
        if started:
            running = reconciled.capacity.running + len(started)
            reconciled = replace(reconciled, capacity=replace(reconciled.capacity, running=running))
    archive_unpushed = archive.run(ctx, log, dry_run=dry_run)
    # After the reconcile and before the harness's items: a source that fails raises one (DESIGN §30).
    drafted.reconcile(ctx, connectors.run(ctx, tick_id, log).read, log)
    # What moved on a waiting feedback plan's PRs, first seen now: its quiet period runs from the newest (§32).
    feedback_plans.note_moves(ctx.conn, ctx.config)
    derived = _derive(ctx, tick_id, log)
    # Before anything reads a message or a run: the harness items and the state block see at least every message, and
    # every run that started or ended, up to here. Idle pacing reads the time (DESIGN §6).
    db.set_tick_read(ctx.conn, tick_id)
    _record_harness_items(ctx, tick_id, archive_unpushed)
    # Before the overseer, which is then shown only the tickets left to it (DESIGN §37).
    _harness_decides(ctx, tick_id, derived, log)

    now = datetime.now(UTC)
    query_due = _query_due(ctx, now)
    db.set_tick_query(ctx.conn, tick_id, due=query_due)
    block, owed, title = _render(
        ctx,
        tick_id=tick_id,
        dry_run=dry_run,
        now=now,
        reconciled=reconciled,
        query_due=query_due,
        woken_by=woken_by,
    )
    halted = _halt(ctx, tick_id, log)
    if halted is not None:
        return finish(*halted)
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
    # Closing `ok` acknowledges the operator's messages the tick read, so each ticket's conversation says what the tick
    # did about them, in the same transaction: a tick that dies between the two leaves neither (DESIGN §22, Messages).
    with db.transaction(ctx.conn):
        if not dry_run:
            acknowledge.note(ctx.conn, tick_id)
        return finish(TickStatus.OK, f"{prefix}{actions.total()} decisions: {counts}", usage)


def _derive(ctx: Context, tick_id: int, log: logs.TickAdapter) -> list[phases.Derived]:
    """Derive §7's table from what the connectors observed, and record it beside the decisions (DESIGN §30).

    What it raises is logged, never the tick's outcome: the harness then decides nothing, and every ticket is the
    overseer's.

    Returns:
        What it derived; nothing when it raised.
    """
    try:
        derived = phases.derive(ctx, datetime.now(UTC))
        phases.record(ctx.conn, tick_id, derived)
    except Exception as e:
        log.exception("deriving the phases raised", extra={"error": str(e)})
        return []
    stale = sum(d.stale is not None for d in derived)
    log.info("phases derived", extra={"subjects": len(derived), "stale": stale})
    return derived


def _harness_decides(ctx: Context, tick_id: int, derived: Iterable[phases.Derived], log: logs.TickAdapter) -> None:
    """Record the decisions the harness makes in code from the derivation, before the overseer runs (DESIGN §37).

    What it raises is logged, never the tick's outcome: what it recorded is undone with it, so every ticket is the
    overseer's.
    """
    try:
        decided = harness.decide(ctx, derived)
        harness.record(ctx.conn, tick_id, ctx.repo, decided)
    except Exception as e:
        log.exception("the harness's decisions raised", extra={"error": str(e)})
        return
    if decided:
        log.info("harness decided", extra={"tickets": [d.key for d in decided]})


def _record_overseer(ctx: Context, tick_id: int, log: logs.TickAdapter) -> None:
    """Record the phases the overseer left each derived subject at, as the tick closes (DESIGN §30)."""
    try:
        phases.record_overseer(ctx.conn, tick_id)
    except Exception as e:
        log.exception("recording the overseer's phases raised", extra={"error": str(e)})


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


def _record_harness_items(ctx: Context, tick_id: int, archive_unpushed: str | None) -> None:
    """Record the attention items the harness raises itself, every tick their cause holds (DESIGN §14).

    `archive_unpushed` is what this tick's archive pass found not pushed, if anything (DESIGN §25).
    """
    for item in attention.from_runs(ctx.conn):
        _harness_item(ctx, tick_id, item.ticket_key, item.reason, item.detail)
    # A private ticket's question reaches the operator here: it is on no tracker (DESIGN §22). So does a planner's on a
    # public ticket, since the planner writes nothing to the ticket (DESIGN §25).
    for waiting in [*conversation.awaiting(ctx.conn), *plans.awaiting(ctx.conn)]:
        _harness_item(ctx, tick_id, waiting.key, "awaiting_reply", attention.awaiting_detail(waiting))
    # The tickets runs reported that the journal could not record (§18). Those it recorded the sinks heard of once.
    for item in follow_ups.unrecorded(ctx.conn):
        _harness_item(ctx, tick_id, item.ticket_key, item.reason, item.detail)
    for remembered in memory_attention.items(ctx.conn, ctx.config):
        _harness_item(ctx, tick_id, remembered.ticket_key, remembered.reason, remembered.detail)
    for draft in drafted.waiting(ctx.conn):
        _harness_item(ctx, tick_id, draft.ticket_key, drafted.WAITING_REASON, draft.detail, repo=draft.repo)
    for failed in chore_view.failed_items(ctx.conn, ctx.config, ctx.workspace):
        _harness_item(ctx, tick_id, None, chore_view.FAILED_REASON, failed.detail, chore=failed.chore)
    _record_connector_failed(ctx, tick_id)
    if archive_unpushed is not None:
        _harness_item(ctx, tick_id, None, archive.REASON, archive_unpushed)
    for repo in ctx.workspace.repos:
        # A tick never clones: a repository in the map with no clone waits for the operator (DESIGN §18).
        if not repo.cloned:
            detail = f"{repo.path} has no clone; run `canopy workspace sync` in {ctx.repo_root}"
            _harness_item(ctx, tick_id, None, "repo_missing", detail, repo=repo.name)


def _harness_item(
    ctx: Context,
    tick_id: int,
    key: str | None,
    reason: str,
    detail: str,
    *,
    repo: str | None = None,
    chore: str | None = None,
) -> None:
    """Record an attention item the harness raises, marked as its own (DESIGN §37, TRUST_MODEL T5)."""
    action = f"{attention.ACTION_PREFIX}{reason}"
    db.record_decision(ctx.conn, tick_id, key, action, detail, repo=repo, chore=chore, decider=Decider.HARNESS)


def _record_connector_failed(ctx: Context, tick_id: int) -> None:
    """Record one item for every source whose run this tick read less than it was asked, each named in its detail."""
    sources = connector_runs.failures(ctx.conn, tick_id)
    if sources:
        _harness_item(ctx, tick_id, None, connector_runs.FAILED_REASON, "; ".join(s.detail for s in sources))


def _halt(ctx: Context, tick_id: int, log: logs.TickAdapter) -> tuple[TickStatus, str] | None:
    """Check what the overseer needs before paying for it: free disk, then `canopy` as it runs it (DESIGN §6 step 5).

    A check that fails records the attention item named for the status the tick closes with.

    Returns:
        That status and the tick's summary, or None when both checks pass.
    """
    low = _check_disk(ctx, log)
    if low is not None:
        status, summary, then = TickStatus.DISK_LOW, low, "Free space there, and the next tick runs it"
    else:
        unavailable = _check_canopy(ctx, tick_id, log)
        if unavailable is None:
            return None
        status, summary = TickStatus.CANOPY_UNAVAILABLE, unavailable
        then = "Make `canopy --version` work where the loop runs"
    _harness_item(ctx, tick_id, None, status, f"{summary}; the overseer did not run. {then}")
    return status, summary


def _check_disk(ctx: Context, log: logs.TickAdapter) -> str | None:
    """Check the free space where the overseer and its runs write: the state directory, and the workspace (DESIGN §6).

    The pools are in the workspace (§18), so a run's build fills its disk. Each filesystem is checked once.

    Returns:
        Which has less than `loop.min_free_disk_mib` free, and how much, or None when each has enough or it is off.
    """
    least = ctx.config.loop.min_free_disk_mib
    if least == 0:
        return None
    seen: set[int] = set()
    for path in (ctx.state_dir, ctx.repo_root):
        device = path.stat().st_dev
        if device in seen:
            continue
        seen.add(device)
        free = shutil.disk_usage(path).free // MIB
        if free < least:
            failure = f"{free} MiB free on {path}, under loop.min_free_disk_mib ({least})"
            log.error("overseer not started", extra={"reason": failure})
            return failure
    return None


def _check_canopy(ctx: Context, tick_id: int, log: logs.TickAdapter) -> str | None:
    """Run `canopy --version` as the overseer would run `canopy`: from its PATH, cwd, and environment (DESIGN §6).

    A launcher whose environment is gone (an uninstall, a cleared cache) fails to start as a missing one does.

    Returns:
        Why `canopy` does not work for the overseer, or None when it does.
    """
    try:
        result = ctx.runner.run(
            CANOPY_CHECK,
            cwd=ctx.repo_root,
            env={TICK_ID_ENV: str(tick_id)},
            timeout=CANOPY_CHECK_TIMEOUT_SECONDS,
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
    ctx: Context,
    tick_id: int,
    block: str,
    title: str,
    *,
    dry_run: bool,
    log: logs.TickAdapter,
) -> tuple[str | None, Usage | None]:
    """Run `overseer_cmd` with the state block `block` as its prompt, and `title` as its `{title}`.

    Output goes to `<state_dir>/ticks/<id>.log` as the overseer prints it, its stderr after it once it ends, and the
    block to `<id>.prompt` beside it first, for the transcript's first model call (DESIGN §22). What its events report
    so far is recorded on the tick as they come, so a running tick shows its session and spend; the session and cost
    again when the overseer ends, failed or not.

    Returns:
        Why it failed, with the errors the runtime reported unless it timed out, None on success, and what it cost if
        the runtime reported it.
    """
    # The runtime reads the repository's config too: it must not define an agent of canopy's (D044).
    failure = project_config.refusal([ctx.repo_root])
    if failure is not None:
        log.error("overseer not started", extra={"reason": failure, "dry_run": dry_run})
        return failure, None
    try:
        definitions_dir = definitions.ensure(ctx.state_dir, ctx.config)
    except definitions.DefinitionsError as e:
        log.error("overseer not started", extra={"reason": str(e), "dry_run": dry_run})  # noqa: TRY400
        return str(e), None
    command = render_command(ctx.config.runtime.overseer_cmd, block, definitions_dir, title)
    argv = command.argv
    timeout_minutes = ctx.config.runtime.overseer_timeout_minutes
    log.info("running overseer", extra={"cmd": argv[0], "timeout_minutes": timeout_minutes})
    out_dir = ctx.state_dir / "ticks"
    out_dir.mkdir(parents=True, exist_ok=True)
    logs.write_private(out_dir / f"{tick_id}.prompt", block)
    out_path = out_dir / f"{tick_id}.log"
    with logs.open_private(out_path) as out:
        watch = progress.Progress(ctx.conn, "ticks", tick_id, out, log, agent="overseer", fields={})
        env = {TICK_ID_ENV: str(tick_id)}
        try:
            with run_offers.probing(ctx.conn, "ticks", tick_id, ctx.runner, argv, cwd=ctx.repo_root, env=env, log=log):
                result = ctx.runner.run(
                    argv,
                    cwd=ctx.repo_root,
                    env=env,
                    stdin=command.stdin,
                    timeout=timeout_minutes * 60,
                    on_line=watch,
                )
        except procs.ProcError as e:
            # It printed nothing, so it keeps no output, as a tick whose overseer never ran keeps none.
            out_path.unlink(missing_ok=True)
            log.exception("overseer could not start", extra={"error": str(e)})
            return str(e), None
        out.write(f"\n--- stderr ---\n{result.stderr}")

    output = stdout.read(result.stdout)
    db.set_tick_report(
        ctx.conn,
        tick_id,
        output.session_id,
        output.usage,
        digest=definitions_dir.name,
        tools=output.tools,
    )
    if result.timed_out:
        failure = f"overseer timed out after {timeout_minutes} minutes"
    elif result.returncode != 0:
        failure = f"overseer exited {result.returncode}"
    elif not _done(output.last):
        failure = f"overseer's final message has no {DONE_LINE} line"
    else:
        return None, output.usage
    # What the runtime said is why it ended; after a timeout, canopy ended it.
    if output.errors and not result.timed_out:
        failure = f"{failure}; the runtime reported {_reported(output.errors)}"
    log.error("overseer failed", extra={"reason": failure, "output": str(out_path), "dry_run": dry_run})
    return failure, output.usage


def _reported(errors: Sequence[str]) -> str:
    """`errors`, the runtime's, in order: the first, which may be the cause, and the last, which ended the run, always.

    Returns:
        Each error joined by `; then `, the middle ones counted instead past `MAX_ERRORS_NAMED`.
    """
    if len(errors) > MAX_ERRORS_NAMED:
        errors = [errors[0], f"{len(errors) - 2} more", errors[-1]]
    return "; then ".join(errors)


def _done(message: str) -> bool:
    """Whether `message`, the overseer's final message, has the done line.

    Text around that line is allowed: models summarize what they did. Only the final message is passed, so a run cut
    off after an earlier message that named the token still fails.

    Returns:
        True if a line, trimmed of whitespace and backticks, is `DONE_LINE` and nothing else.
    """
    return any(line.strip().strip("`").strip() == DONE_LINE for line in message.splitlines())
