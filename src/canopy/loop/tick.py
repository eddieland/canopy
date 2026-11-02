"""One tick of the loop (DESIGN §6): lock, migrate, reconcile, check the overseer's tools, run and check it, publish.

A live tick starts the operator's queued one-off tasks after reconcile, in code, before the overseer (DESIGN §36). The
runs the overseer asks for are recorded, and the tick starts them once its run has ended, with the harness's own
(`spawns.py`, DESIGN §40); one it did not start is closed unstarted as it closes, or by the next tick if it died. Its
overseer's run is recorded as it starts and as it ends (`core/overseer_runs.py`). A tick that closes `ok` notes, on
each ticket, what it did about the operator's messages it read (`acknowledge.py`).
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, Protocol, assert_never

import canopy_mcp

from canopy.chores import reconcile as chore_reconcile
from canopy.core import (
    agent_models,
    chore_view,
    commit_hooks,
    connector_runs,
    conversation,
    db,
    definitions,
    hostgit,
    item_numbers,
    notice,
    overseer_runs,
    plan_lengths,
    plans,
    pools,
    progress,
    recorded_runs,
    run_models,
    run_offers,
)
from canopy.core.config import render_command
from canopy.core.items import one_line
from canopy.core.vocab import Decider, TickStatus
from canopy.infra import lock, logs, procs, resources, tracing
from canopy.loop import (
    acknowledge,
    archive,
    attention,
    connectors,
    duties,
    gc_pass,
    harness,
    harness_cursors,
    harness_dispatches,
    harness_items,
    mcp,
    observations,
    phases,
    spawns,
    state,
)
from canopy.memory import attention as memory_attention
from canopy.memory import reconcile as memory_reconcile
from canopy.reviews import reconcile as review_reconcile
from canopy.reviews import view as review_view
from canopy.reviews import waiting as review_waiting
from canopy.runs import artifact_authority, drafted, drafts, feedback_plans, follow_ups, policy, reconcile, task_starts
from canopy.runtime import project_config, servers, stdout

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Sequence

    from canopy.core import records
    from canopy.core.context import Context
    from canopy.runtime.report import Usage

TICK_ID_ENV = conversation.TICK_ID_ENV
# A word no model writes by chance, alone on a line of the overseer's final message (DESIGN §6).
DONE_LINE = "CANOPY_TICK_DONE"
# The overseer acts only through canopy's tools, so a tick starts their server as the runtime would, and asks it to
# `initialize`, before paying for the overseer (DESIGN §6, §27). When it fails, the tick closes `canopy_unavailable`
# and raises an item of the same name.
SERVER_CHECK_TIMEOUT_SECONDS = 60
MIB = 1024 * 1024
# How long a ticket marked done stays in the state block's `recently_done` while the query still finds it, so the
# overseer leaves it out while a human has yet to close it in the tracker (DESIGN §7). One still open after that is read
# again and marked done again, which lists it for as long once more.
RECENTLY_DONE_DAYS = 30
#: What the summary of a tick that ran no overseer starts with, after a dry run's prefix (DESIGN §39).
NO_OVERSEER = "no overseer, nothing left to judge"
#: How many of the runtime's errors a failed overseer's summary names; past it, the first and last, the rest counted.
MAX_ERRORS_NAMED = 3
# How a tick ended: the status it closed its row with, or, with no row, `lock_busy` when another tick held the lock and
# `error` when `canopy loop` caught the tick raising before it had one or after it closed it.
type OutcomeStatus = TickStatus | Literal["lock_busy", "error"]
# What ended `canopy loop`'s wait before its deadline: the operator's act (a message, a ticket started or stopped, a
# grant, a task submitted, replied to, or stopped, a notice set or cleared), a run ending, a poll of the connectors
# (DESIGN §39), the operator pressing the loop's tick-now key, or the operator asking from the web UI.
type Woken = Literal["message", "starts", "grant", "task", "notice", "run", "poll", "key", "web"]
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
) -> str:
    """Read the journal for tick `tick_id` and render the overseer's state block from it (DESIGN §6 step 4).

    `reconciled` is what reconcile left: the capacity, and each repository's leased slots.

    Returns:
        The `## State` section, the overseer's whole message.
    """
    rendered = _render(ctx, tick_id=tick_id, dry_run=dry_run, now=now, reconciled=reconciled)
    return rendered.block


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
        case "timer" | "gate" | "message" | "grant" | "task" | "notice" | "poll":
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
    woken_by: WokenBy | None = None,
) -> _Rendered:
    """Render the state block, and read what it asks of the overseer from the same journal reads (DESIGN §6 step 5).

    Returns:
        The `## State` section, the overseer's duties this tick and what is left to it, and its session title, which
        `woken_by` starts.
    """
    running = db.running_runs(ctx.conn, "runs")
    last_runs = db.latest_runs(ctx.conn)
    # A stopped ticket waits on the operator alone: listed by key, it gets no decision every tick (DESIGN §22).
    stopped = conversation.stopped(ctx.conn)
    # A ticket the harness decided, or dispatches after the overseer, is named with what it does, and nothing else of
    # it is shown (DESIGN §37).
    by_harness = harness.recorded(ctx.conn, tick_id)
    to_come = harness_dispatches.plan(ctx, tick_id, now)
    decided = frozenset([*(str(d.ticket_key) for d in by_harness), *(r.key for r in to_come.runs)])
    tickets = [t for t in db.open_tickets(ctx.conn) if t.key not in stopped and t.key not in decided]
    private = {t.key: found for t in tickets if (found := conversation.state_section(ctx.conn, t)) is not None}
    # A public ticket's comments on artifacts that are authority are shown with its operator messages (DESIGN §38).
    authors = frozenset(ctx.config.artifacts.authorized_authors)
    operator: dict[str, conversation.OperatorSection] = {}
    for t in tickets:
        authorized = artifact_authority.authorized(ctx.conn, t.key, authors)
        if (found := conversation.operator_section(ctx.conn, t, authorized=authorized)) is not None:
            operator[t.key] = found
    planned = _plans(ctx, tickets)
    # Only those the query still finds open: one a human closed will not come back from it (DESIGN §7).
    found = duties.last_queried(ctx.conn)
    since = db.format_time(now - timedelta(days=RECENTLY_DONE_DAYS))
    recently_done = [t for t in db.recently_done(ctx.conn, since) if str(t["key"]) in found]
    # A chore with no `when` is the harness's: the block names it only as a dispatch to come (DESIGN §37).
    chores = [
        c for c in chore_view.state_section(chore_view.states(ctx.conn, ctx.config, ctx.workspace), now) if c["when"]
    ]
    shown = [*(int(r["id"]) for r in running), *(r.id for r in last_runs.values())]
    reviews = review_view.state_section(ctx.conn, ctx.config, now)
    units = db.all_units(ctx.conn)
    # What each cursor names, so a live read of a stale subject can tell what it passed (DESIGN §35).
    cursors = [
        *(t.comment_cursor for t in tickets),
        *(c for us in units.values() for u in us for c in (u.review_cursor, u.ci_cursor)),
    ]
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
        dispatches_to_come=harness_dispatches.section(to_come),
        units=units,
        last_runs=last_runs,
        run_slots=db.all_run_slots(ctx.conn, shown),
        run_reasons=db.run_reasons(ctx.conn, shown),
        attempts=policy.attempts(ctx.conn),
        grants=policy.grants(ctx.conn),
        ci_cooldowns=policy.ci_cooldowns(ctx.conn, ctx.config, now),
        now=now,
        chores=chores,
        reviews=reviews,
        notices=notice.recent(ctx.conn, now),
        private=private,
        operator=operator,
        planned=planned,
        feedback_planned=_feedback_plans(ctx, tickets, now),
        attention=attention.for_overseer(ctx.conn, decided=decided),
        operator_sent=drafts.sent_by_pr(ctx.conn),
        observations=observations.section(ctx, tick_id, now, tickets, decided=decided),
        numbered=item_numbers.named(ctx.conn, [c for c in cursors if c is not None]),
    )
    owed = duties.owed(
        ctx.conn,
        tick_id,
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
    return _Rendered(block, owed, _left(ctx.conn, tick_id, owed, reviews), title)


@dataclass(frozen=True)
class _Rendered:
    """The overseer's state block, and what reading it for the same tick found."""

    #: The `## State` section, the overseer's whole message.
    block: str
    #: What the overseer owes this tick (DESIGN §6 step 5).
    owed: duties.Duties
    #: What the block leaves the overseer to judge, a phrase each; with none, the tick runs no overseer (DESIGN §39).
    left: Sequence[str]
    #: The overseer's session title.
    title: str


def _left(
    conn: sqlite3.Connection,
    tick_id: int,
    owed: duties.Duties,
    reviews: review_view.ReviewsSection | None,
) -> list[str]:
    """What the state block leaves the overseer to judge, after the harness's decisions (DESIGN §37, §39).

    Each duty it owes, which before it runs is each one there is: a ticket listed or the query found, and a due chore
    with a `when`. And the reviews it starts: the review query's, the operator's requests,
    and the revisions their notes ask for.

    Returns:
        A phrase for each; none when the harness has left it nothing.
    """
    left = duties.undone(conn, tick_id, owed)
    if reviews is not None and (reviews["query"] or reviews["requests"] or reviews.get("revisions")):
        left.append("reviews to start or wait on")
    return left


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
        section = feedback_plans.state_section(
            ctx.conn,
            ctx.config,
            ctx.workspace,
            t,
            attempts=attempts,
            limits=limits,
            now=now,
        )
        if section is not None:
            found[t.key] = section
    return found


def _locked(ctx: Context, *, dry_run: bool, woken_by: WokenBy | None) -> Outcome:
    applied = db.migrate(ctx.conn, resources.migrations_dir())
    abandoned = db.abandon_unfinished_ticks(ctx.conn)
    overseer_runs.close_abandoned(ctx.conn)
    # A run a dead tick recorded and did not start is never started: this tick decides again (DESIGN §40).
    unstarted = recorded_runs.close_unstarted(ctx.conn)
    tick_id = db.start_tick(ctx.conn, dry_run=dry_run)
    log = logs.for_tick(tick_id)
    log.info("tick started", extra={"dry_run": dry_run, "repo": ctx.repo, "migrations_applied": applied})
    if abandoned:
        log.warning("closed ticks left running by a dead tick process", extra={"abandoned_ticks": abandoned})
    if unstarted:
        log.warning("closed runs a dead tick recorded and never started", extra={"unstarted": unstarted})

    def finish(status: TickStatus, summary: str, usage: Usage | None = None) -> Outcome:
        _record_overseer(ctx, tick_id, log)
        # Whatever the tick did not start, because it ended early, belongs to it alone.
        recorded_runs.close_unstarted(ctx.conn, tick_id=tick_id)
        # An overseer run still running when its tick closes, because the tick raised, failed with it.
        overseer_runs.close_running(ctx.conn, tick_id, summary)
        db.finish_tick(ctx.conn, tick_id, status, summary)
        spent = usage.spent() if usage is not None else {}
        log.info("tick finished", extra={"status": status, "summary": summary, **spent})
        traced.set(
            status=status,
            cost_usd=usage.cost_usd if usage is not None else None,
            new_tokens=usage.new_tokens if usage is not None else None,
        )
        return Outcome(tick_id, status, summary, usage)

    with tracing.span("tick", tick_id=tick_id, dry_run=dry_run) as traced:
        try:
            return _steps(ctx, tick_id, log, finish, dry_run=dry_run, woken_by=woken_by)
        # Closed with what it raised, so the journal keeps why it failed when the logs do not. Should closing it raise
        # too, the next tick closes it `abandoned`.
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
        with tracing.span("gc"):
            gc_pass.run(ctx, tick_id, log)
            _measure_plans(ctx, log)
    with tracing.span("reconcile"):
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
        reconciled = _start_tasks(ctx, tick_id, reconciled, log)
    archive_unpushed = archive.run(ctx, log, dry_run=dry_run)
    _observe(ctx, tick_id, log, dry_run=dry_run)
    _decide_in_code(ctx, tick_id, archive_unpushed, log, dry_run=dry_run)

    now = datetime.now(UTC)
    with tracing.span("state") as state:
        _query(ctx, tick_id, now, log)
        rendered = _render(ctx, tick_id=tick_id, dry_run=dry_run, now=now, reconciled=reconciled, woken_by=woken_by)
        state.set(left=len(rendered.left))
    # With nothing left to judge, the overseer would be handed an empty block: the tick runs none, and owes nothing.
    # The disk check still holds the harness's dispatches, which fill a disk as the overseer's do (DESIGN §39).
    overseer = bool(rendered.left)
    halted = _halt(ctx, tick_id, log, overseer=overseer)
    db.set_tick_overseer(ctx.conn, tick_id, ran=overseer and halted is None)
    if halted is not None:
        return finish(*halted)
    with tracing.span("overseer") as traced:
        failure, usage = _overseer(ctx, tick_id, rendered, dry_run=dry_run, log=log)
        traced.set(
            failed=failure is not None,
            cost_usd=usage.cost_usd if usage is not None else None,
            new_tokens=usage.new_tokens if usage is not None else None,
        )
    # After the overseer, whatever its run ended as, every run it recorded and the harness's own; a tick halted before
    # it starts none (DESIGN §37, §40).
    with tracing.span("spawn"):
        _spawn(ctx, tick_id, log)
    if failure is not None:
        return finish(TickStatus.OVERSEER_FAILED, failure, usage)
    owed = rendered.owed

    decisions = db.decisions_for_tick(ctx.conn, tick_id)
    prefix = ("dry run; " if dry_run else "") + ("" if overseer else f"{NO_OVERSEER}; ")
    # A duty left undone fails the tick as a missing done line does: closing it `ok` would resolve the items of every
    # ticket it left out (DESIGN §6 step 5).
    undone = duties.undone(ctx.conn, tick_id, owed)
    if undone:
        log.error("overseer left duties undone", extra={"undone": undone, "dry_run": dry_run})
        failure = f"overseer left duties undone: {'; '.join(undone)}"
        overseer_runs.left_undone(ctx.conn, tick_id, failure)
        return finish(TickStatus.OVERSEER_FAILED, f"{prefix}{failure}", usage)
    actions = Counter(d.action for d in decisions)
    counts = ", ".join(f"{action}={n}" for action, n in sorted(actions.items())) or "none"
    # Closing `ok` acknowledges the operator's messages the tick read, so each ticket's conversation says what the tick
    # did about them, in the same transaction: a tick that dies between the two leaves neither (DESIGN §22, Messages).
    with db.transaction(ctx.conn):
        if not dry_run:
            acknowledge.note(ctx.conn, tick_id)
        return finish(TickStatus.OK, f"{prefix}{actions.total()} decisions: {counts}", usage)


# The plans the journal has no current measurements of, a few a tick (`plan_lengths`). A failure is logged, and the
# tick goes on: the Plans report measures what is missing itself.
def _measure_plans(ctx: Context, log: logs.TickAdapter) -> None:
    try:
        measured = plan_lengths.fill(ctx.conn, ctx.state_dir)
    except Exception as e:
        log.exception("plans not measured", extra={"error": str(e)})
        return
    if measured:
        log.info("plans measured", extra={"plans": measured})


def _start_tasks(
    ctx: Context,
    tick_id: int,
    reconciled: reconcile.Reconciled,
    log: logs.TickAdapter,
) -> reconcile.Reconciled:
    """Start the operator's queued tasks, each taking a slot from the capacity the overseer is shown.

    Returns:
        What reconcile left, less the capacity the tasks started now hold.
    """
    with tracing.span("tasks") as traced:
        started = task_starts.start_queued(ctx, tick_id, log)
        traced.set(started=len(started))
    if not started:
        return reconciled
    running = reconciled.capacity.running + len(started)
    return replace(reconciled, capacity=replace(reconciled.capacity, running=running))


def _observe(ctx: Context, tick_id: int, log: logs.TickAdapter, *, dry_run: bool) -> None:
    """Run the sources: after the reconcile, and before the harness's items, as a failing source raises one (§30)."""
    with tracing.span("connectors"):
        drafted.reconcile(ctx, connectors.run(ctx, tick_id, log, dry_run=dry_run).read, log)
        # What moved on a waiting feedback plan's PRs, first seen now: its quiet period runs from the newest (§32).
        feedback_plans.note_moves(ctx.conn, ctx.config, ctx.workspace)


def _decide_in_code(
    ctx: Context,
    tick_id: int,
    archive_unpushed: str | None,
    log: logs.TickAdapter,
    *,
    dry_run: bool,
) -> None:
    """Derive what the journal says, record the harness's own items, and decide what it decides in code (DESIGN §37)."""
    with tracing.span("derive"):
        # Before the derivation and the block, so both read each cursor past what needs no handling (DESIGN §37).
        _harness_cursors(ctx, tick_id, log, dry_run=dry_run)
        derived = _derive(ctx, tick_id, log)
        # Before anything reads a message or a run: the harness items and the state block see at least every message,
        # and every run that started or ended, up to here. Idle pacing reads the time (DESIGN §6).
        db.set_tick_read(ctx.conn, tick_id)
        _record_harness_items(ctx, tick_id, archive_unpushed)
        _record_from_causes(ctx, tick_id, derived, log)
        # Before the overseer, which is then shown only the tickets left to it (DESIGN §37).
        _harness_decides(ctx, tick_id, derived or [], log)


def _overseer(
    ctx: Context,
    tick_id: int,
    rendered: _Rendered,
    *,
    dry_run: bool,
    log: logs.TickAdapter,
) -> tuple[str | None, Usage | None]:
    """Run the overseer on the state block `rendered`, unless it leaves the overseer nothing to judge (DESIGN §39).

    The run is recorded as it starts, given the whole block, and closed as it ends (DESIGN §40).

    Returns:
        Why it failed, or None, and what it cost if the runtime reported it; None and None when it did not run.
    """
    if not rendered.left:
        log.info("overseer not run: the harness left it nothing to judge", extra={"dry_run": dry_run})
        return None, None
    run_id = overseer_runs.start(ctx.conn, tick_id)
    # The state block is the whole message: the prompt is in the overseer's definition, cached across ticks (DESIGN §6).
    failure, usage = _run_overseer(ctx, tick_id, run_id, rendered.block, rendered.title, dry_run=dry_run, log=log)
    overseer_runs.end(ctx.conn, run_id, failure)
    return failure, usage


def _harness_cursors(ctx: Context, tick_id: int, log: logs.TickAdapter, *, dry_run: bool) -> None:
    """Move the cursors past what needs no handling, a worker's comment and a reply the operator sent (DESIGN §37).

    A dry run moves none (D036). What it raises is logged, never the tick's outcome: what it recorded is undone with it,
    so every cursor is where the overseer left it.
    """
    if dry_run:
        return
    try:
        moved = harness_cursors.record(ctx.conn, tick_id, harness_cursors.moves(ctx, datetime.now(UTC)))
    except Exception as e:
        log.exception("the harness's cursor moves raised", extra={"error": str(e)})
        return
    if moved:
        log.info("harness moved cursors", extra={"cursors": [m.rationale() for m in moved]})


def _derive(ctx: Context, tick_id: int, log: logs.TickAdapter) -> list[phases.Derived] | None:
    """Derive §7's table from what the connectors observed, and record it beside the decisions (DESIGN §30).

    What it raises is logged, never the tick's outcome: the harness then decides nothing, every ticket is the
    overseer's, and every item the harness holds on an observation is kept.

    Returns:
        What it derived; None when it raised.
    """
    try:
        derived = phases.derive(ctx, datetime.now(UTC))
        phases.record(ctx.conn, tick_id, derived)
    except Exception as e:
        log.exception("deriving the phases raised", extra={"error": str(e)})
        return None
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


def _spawn(ctx: Context, tick_id: int, log: logs.TickAdapter) -> None:
    """Start the runs the overseer recorded and the harness's, after the overseer, in §7's order (DESIGN §37, §40).

    Each is checked against every guard again. What it raises is logged, never the tick's outcome: what it started
    stands, and what it did not is closed unstarted with the tick, and waits for a later tick to decide again.
    """
    try:
        spawns.make(ctx, tick_id, log)
    except Exception as e:
        log.exception("starting the runs after the overseer raised", extra={"error": str(e)})


def _record_overseer(ctx: Context, tick_id: int, log: logs.TickAdapter) -> None:
    """Record the phases the overseer left each derived subject at, as the tick closes (DESIGN §30)."""
    try:
        phases.record_overseer(ctx.conn, tick_id)
    except Exception as e:
        log.exception("recording the overseer's phases raised", extra={"error": str(e)})


def _query(ctx: Context, tick_id: int, now: datetime, log: logs.TickAdapter) -> None:
    """Record whether tick `tick_id` runs the tracker query, and, when it does, the query the `tracker` source read.

    The harness records a query the state block shows `fresh` at `now`, before the overseer runs, so what it records
    is what the overseer reads (DESIGN §6 step 5). The overseer reads no tracker (§39): a query no source read fresh
    does not run this tick, and a ticket it would find waits for the read that finds it, the next tick's query due
    again.
    """
    found = observations.fresh_query(ctx, now) if _query_due(ctx, now) else None
    db.set_tick_query(ctx.conn, tick_id, due=found is not None)
    if found is not None:
        named = duties.record_queried(ctx.conn, tick_id, ctx.repo, found)
        log.info("recorded the query a source read", extra={"tickets": named})


def _query_due(ctx: Context, now: datetime) -> bool:
    """Whether this tick runs the tracker query (DESIGN §7, Spacing the query).

    Every tick does with `tracker.query_every_minutes` at 0. Otherwise one does once that long has passed since the
    newest live `ok` tick that ran it started, or when none has.

    Returns:
        True if the query is due this tick.
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
    # A comment on an artifact by an author the operator does not list waits for them to send it on (DESIGN §38).
    for untrusted in artifact_authority.untrusted(ctx.conn, frozenset(ctx.config.artifacts.authorized_authors)):
        _harness_item(ctx, tick_id, untrusted.ticket_key, artifact_authority.REASON, untrusted.detail)
    _record_drafts(ctx, tick_id)
    for failed in chore_view.failed_items(ctx.conn, ctx.config, ctx.workspace):
        _harness_item(ctx, tick_id, None, chore_view.FAILED_REASON, failed.detail, chore=failed.chore)
    _record_connector_failed(ctx, tick_id)
    if archive_unpushed is not None:
        _harness_item(ctx, tick_id, None, archive.REASON, archive_unpushed)
    _record_git_items(ctx, tick_id)


def _record_from_causes(
    ctx: Context,
    tick_id: int,
    derived: Sequence[phases.Derived] | None,
    log: logs.TickAdapter,
) -> None:
    """Record the items the harness raises from their causes, from the tick's derivation `derived` (DESIGN §37).

    What it raises is logged, never the tick's outcome: every such item open is then recorded again as it was listed,
    so a fault of the harness's drops none.
    """
    try:
        found = harness_items.raised(ctx, derived, datetime.now(UTC))
    except Exception as e:
        log.exception("the harness's items from their causes raised", extra={"error": str(e)})
        found = harness_items.kept(ctx.conn)
    for item in found:
        _harness_item(ctx, tick_id, item.ticket_key, item.reason, item.detail, repo=item.repo, pr=item.pr)


def _record_git_items(ctx: Context, tick_id: int) -> None:
    """Record the items git raises: a clone missing or left to prune slots (§18), and a git too old for the hooks."""
    for repo in ctx.workspace.repos:
        # A tick never clones: a repository in the map with no clone waits for the operator (DESIGN §18).
        if not repo.cloned:
            detail = f"{repo.path} has no clone; run `canopy workspace sync` in {ctx.repo_root}"
            _harness_item(ctx, tick_id, None, "repo_missing", detail, repo=repo.name)
        elif keys := hostgit.maintenance_left_on(ctx.runner, repo.path):
            detail = (
                f"git's automatic maintenance is on in {repo.path} ({', '.join(keys)} not set), and can prune what "
                f"running slots use; run `canopy workspace sync` in {ctx.repo_root}"
            )
            _harness_item(ctx, tick_id, None, attention.MAINTENANCE_ON, detail, repo=repo.name)
    if (old := commit_hooks.git_too_old(ctx.config, ctx.runner)) is not None:
        _harness_item(ctx, tick_id, None, attention.GIT_TOO_OLD, old)


def _record_drafts(ctx: Context, tick_id: int) -> None:
    """Record the items of the drafts that wait on the operator: a run's replies (§29), and a review's (§34)."""
    for draft in drafted.waiting(ctx.conn):
        _harness_item(ctx, tick_id, draft.ticket_key, drafted.WAITING_REASON, draft.detail, repo=draft.repo)
    # A review the operator asked for, and a draft staged or of unknown outcome, are about a PR no ticket owns; a held
    # finding is about its ticket's own PR (§21).
    for review in review_waiting.items(ctx.conn):
        _harness_item(ctx, tick_id, review.ticket, review.reason, review.detail, pr=review.pr)


def _harness_item(
    ctx: Context,
    tick_id: int,
    key: str | None,
    reason: str,
    detail: str,
    *,
    repo: str | None = None,
    chore: str | None = None,
    pr: str | None = None,
) -> None:
    """Record an attention item the harness raises, marked as its own (DESIGN §37, TRUST_MODEL T5)."""
    action = f"{attention.ACTION_PREFIX}{reason}"
    db.record_decision(
        ctx.conn,
        tick_id,
        key,
        action,
        detail,
        repo=repo,
        chore=chore,
        pr=pr,
        decider=Decider.HARNESS,
    )


def _record_connector_failed(ctx: Context, tick_id: int) -> None:
    """Record one item for every source whose run this tick read less than it was asked, each named in its detail."""
    sources = connector_runs.failures(ctx.conn, tick_id)
    if sources:
        _harness_item(ctx, tick_id, None, connector_runs.FAILED_REASON, "; ".join(s.detail for s in sources))


def _halt(ctx: Context, tick_id: int, log: logs.TickAdapter, *, overseer: bool) -> tuple[TickStatus, str] | None:
    """Check what the overseer needs before paying for it: free disk, its tools' server, its model (DESIGN §6 step 5).

    The server and model checks are the overseer's, made only with `overseer`, for a tick that runs it (DESIGN §39).
    A check that fails records the attention item named for the status the tick closes with.

    Returns:
        That status and the tick's summary, or None when every check passes.
    """
    low = _check_disk(ctx, log)
    if low is not None:
        status, summary, then = TickStatus.DISK_LOW, low, "Free space there, and the next tick runs it"
    elif not overseer:
        return None
    elif (unavailable := _check_server(ctx, tick_id, log)) is not None:
        status, summary = TickStatus.CANOPY_UNAVAILABLE, unavailable
        then = "Make `canopy _mcp` start where the loop runs"
    elif (refused := _check_model(ctx, log)) is not None:
        status, summary = refused
        then = "The next tick looks it up again"
    else:
        return None
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


def _check_server(ctx: Context, tick_id: int, log: logs.TickAdapter) -> str | None:
    """Start `canopy _mcp` as the runtime would for the overseer, in its cwd, and ask it to `initialize` (DESIGN §6).

    An interpreter that is gone (an uninstall, a cleared cache) fails to start as a missing one does. The server exits
    once its stdin closes, after answering.

    Returns:
        Why the overseer would have no tools, or None when the server answers.
    """
    hello: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": canopy_mcp.PROTOCOL_VERSIONS[0],
            "capabilities": {},
            "clientInfo": {"name": "canopy-tick", "version": db.CANOPY_VERSION},
        },
    }
    try:
        result = ctx.runner.run(
            mcp.COMMAND,
            cwd=ctx.repo_root,
            env={TICK_ID_ENV: str(tick_id)},
            stdin=json.dumps(hello) + "\n",
            timeout=SERVER_CHECK_TIMEOUT_SECONDS,
        )
    except procs.ProcError as e:
        failure = f"`canopy _mcp` does not start for the overseer: {e}"
    else:
        if result.timed_out:
            failure = f"`canopy _mcp` did not answer initialize in {SERVER_CHECK_TIMEOUT_SECONDS} seconds"
        elif result.returncode != 0:
            said = one_line(result.stderr or result.stdout)[-300:]
            failure = f"`canopy _mcp` exited {result.returncode}" + (f": {said}" if said else "")
        elif not _initialized(result.stdout):
            said = one_line(result.stdout)[:300]
            failure = "`canopy _mcp` did not answer initialize" + (f": {said}" if said else "")
        else:
            return None
    log.error("overseer not started", extra={"reason": failure})
    return failure


def _check_model(ctx: Context, log: logs.TickAdapter) -> tuple[TickStatus, str] | None:
    """Look the overseer's chosen model up in the runtime's list, as a worker's dispatch does (DESIGN §13).

    The model is the one `runtime.models` chooses for the agent `runtime.overseer_cmd` runs; the overseer works on no
    one ticket, so no override reaches it. It is never fallen back from: an overseer on a model nobody chose would
    decide for the loop unseen.

    Returns:
        The status the tick closes with, `model_missing` or `model_list_failed`, and why, or None when no model is
        chosen or the runtime lists it.
    """
    model = agent_models.of_template(ctx.config.runtime.models, ctx.config.runtime.overseer_cmd)
    if model is None:
        return None
    try:
        agent_models.check(ctx.runner, ctx.workspace.root, model, version=ctx.config.runtime.version)
    except agent_models.ModelError as e:
        refused = e
    else:
        return None
    log.error("overseer not started", extra={"reason": refused.reason})
    missing = refused.guard == agent_models.MISSING
    return TickStatus.MODEL_MISSING if missing else TickStatus.MODEL_LIST_FAILED, refused.reason


def _initialized(out: str) -> bool:
    """Whether `out`, what `canopy _mcp` printed, opens with its answer to `initialize`, as canopy's server.

    Returns:
        True when its first line is a JSON-RPC result for request 0 from a server named canopy.
    """
    first = out.partition("\n")[0]
    try:
        answer = json.loads(first)
    except json.JSONDecodeError:
        return False
    result = answer.get("result") if isinstance(answer, dict) and answer.get("id") == 0 else None
    info = result.get("serverInfo") if isinstance(result, dict) else None
    return isinstance(info, dict) and info.get("name") == mcp.SERVER


def _run_overseer(
    ctx: Context,
    tick_id: int,
    run_id: int,
    block: str,
    title: str,
    *,
    dry_run: bool,
    log: logs.TickAdapter,
) -> tuple[str | None, Usage | None]:
    """Run `overseer_cmd` as run `run_id`, with the state block `block` as its prompt, and `title` as its `{title}`.

    Output goes to `<state_dir>/ticks/<id>.log` as the overseer prints it, its stderr after it once it ends, and the
    block to `<id>.prompt` beside it first, for the transcript's first model call (DESIGN §22). What its events report
    so far is recorded on the tick as they come, so a running tick shows its session and spend; the session and cost
    again when the overseer ends, failed or not.

    Returns:
        Why it failed, with the errors the runtime reported unless it timed out, None on success, and what it cost if
        the runtime reported it.
    """
    # The runtime reads the repository's config too: it must not define an agent of canopy's (D044).
    failure = project_config.refusal([ctx.repo_root], version=ctx.config.runtime.version)
    if failure is not None:
        log.error("overseer not started", extra={"reason": failure, "dry_run": dry_run})
        return failure, None
    try:
        definitions_dir = definitions.ensure(ctx.state_dir, ctx.config)
    except definitions.DefinitionsError as e:
        log.error("overseer not started", extra={"reason": str(e), "dry_run": dry_run})  # noqa: TRY400
        return str(e), None
    command = render_command(ctx.config.runtime.overseer_cmd, block, definitions_dir, title)
    # What the definitions just rendered hold for it, as `_check_model` found it listed.
    model = agent_models.of_template(ctx.config.runtime.models, ctx.config.runtime.overseer_cmd)
    db.set_tick_model(ctx.conn, tick_id, model.name if model is not None else None)
    overseer_runs.set_model(ctx.conn, run_id, model.name if model is not None else None)
    argv = command.argv
    timeout_minutes = ctx.config.runtime.overseer_timeout_minutes
    # Its tools, in its process's environment alone (DESIGN §27). A call may take as long as the overseer may: a
    # dispatch can wait on a lease, and one the runtime gave up on would still be served, holding up each call after.
    served = servers.env(
        {mcp.SERVER: mcp.COMMAND},
        version=ctx.config.runtime.version,
        cwd=ctx.repo_root,
        timeout_seconds=timeout_minutes * 60,
    )
    log.info("running overseer", extra={"cmd": argv[0], "timeout_minutes": timeout_minutes})
    out_dir = ctx.state_dir / "ticks"
    out_dir.mkdir(parents=True, exist_ok=True)
    logs.write_private(out_dir / f"{tick_id}.prompt", block)
    out_path = out_dir / f"{tick_id}.log"
    with logs.open_private(out_path) as out:
        watch = progress.Progress(
            ctx.conn,
            "ticks",
            tick_id,
            out,
            log,
            agent="overseer",
            fields={},
            version=ctx.config.runtime.version,
        )
        env = {TICK_ID_ENV: str(tick_id), **served}
        try:
            with run_offers.probing(
                ctx.conn,
                "ticks",
                tick_id,
                ctx.runner,
                argv,
                version=ctx.config.runtime.version,
                cwd=ctx.repo_root,
                env=env,
                log=log,
            ):
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

    output = stdout.read(result.stdout, version=ctx.config.runtime.version)
    db.set_tick_report(
        ctx.conn,
        tick_id,
        output.session_id,
        output.usage,
        digest=definitions_dir.name,
        tools=output.tools,
    )
    overseer_runs.report(ctx.conn, run_id, output.session_id, output.usage)
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
