"""Delivering to notification sinks at the end of each tick (DESIGN §6 step 7, §20).

For each sink, in name order: gather its attention diff if it takes `attention`, its events after its cursor in the
groups it takes, and a digest if one is due; hold it if the sink batches and nothing in it is urgent; else render one
message in its format and run its command with the message on stdin. Exit 0 within the timeout is a delivery,
recorded in the journal; anything else changes nothing but the sink's failure count, so the next tick tries again.
Sinks run one after another under the tick lock.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import contract, db, outbox, records, spend, sql
from canopy.core.config import Sink, notify_words
from canopy.infra import procs
from canopy.notify import journal, message

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.core.items import Item
    from canopy.infra import logs

TIMEOUT_SECONDS = 60
# A sink that fails this many deliveries in a row raises `loop.sink_failing` once; so many failed ticks raise
# `loop.failing` once.
FAILING_AFTER = 3
_POINT_GROUPS = (outbox.LOOP, outbox.RUNS, outbox.CHORES, outbox.REVIEWS, outbox.TASKS)
# Events a batching sink sends at once, with whatever it held: the loop or a sink failing, or a plan waiting on the
# operator, which holds its ticket until they answer (DESIGN §25).
_URGENT_KINDS = frozenset({"loop.failing", "loop.sink_failing", "plan.proposed"})
# The events whose `blocked` run asked the operator a question: a ticket's run's, and a one-off task's (DESIGN §36).
_ASKING_KINDS = frozenset({"run.ended", "task.ended"})


@dataclass(frozen=True)
class Delivery:
    """How one sink's delivery went: `delivered`, `nothing` to send, `held` for its batch, or `failed` with why."""

    sink: str
    outcome: str
    detail: str = ""


def publish(
    ctx: Context,
    items: Sequence[Item],
    path: Path,
    log: logs.TickAdapter,
    *,
    dismissed: Collection[str] = (),
    ui: str | None = None,
) -> list[Delivery]:
    """Deliver to every configured sink, after recording the loop's own events. Never raises: the tick is closed.

    `dismissed` holds the fingerprints of chore findings the operator dismissed: a sink told of one hears why it left.
    `ui` is the web UI's address, ending in `/`, when the loop serves it: a `json` message then links to its pages.

    Returns:
        How each sink's delivery went, in name order.
    """
    sinks = ctx.config.notify.all_sinks()
    for name in journal.forget_sinks(ctx.conn, sinks):
        log.info("notification sink removed from the config; forgot it", extra={"sink": name})
    now = datetime.now(UTC)
    if ctx.config.notify.takes(outbox.LOOP):
        _record_loop_events(ctx)
        _record_budget_event(ctx, now)
    deliveries = [
        _deliver(ctx, name, sink, items, path=path, now=now, log=log, dismissed=dismissed, ui=ui)
        for name, sink in sinks.items()
    ]
    journal.prune_events(ctx.conn, now)
    return deliveries


def send(ctx: Context, sink: Sink, text: str) -> str | None:
    """Run the sink's command with `text` on stdin.

    Returns:
        None on exit 0, else why it failed: it could not start, timed out, or exited non-zero, with its stderr's tail.
    """
    argv = notify_words(sink.cmd)
    try:
        result = ctx.runner.run(argv, cwd=ctx.repo_root, stdin=text, timeout=TIMEOUT_SECONDS)
    except procs.ProcError as e:
        return f"could not start: {e}"
    if result.ok:
        return None
    status = "timed out" if result.timed_out else f"exited {result.returncode}"
    tail = result.stderr.strip()[-500:]
    return f"{status}: {tail}" if tail else status


def test(ctx: Context, names: Iterable[str]) -> list[Delivery]:
    """Send a test message to each sink in `names` now, outside any tick, changing nothing in the journal.

    Returns:
        How each sink's delivery went, in the order of `names`: `delivered`, or `failed` with why.
    """
    sinks = ctx.config.notify.all_sinks()
    results: list[Delivery] = []
    for name in names:
        sink = sinks[name]
        event = message.Event(0, "test", db.now(), {"text": f"canopy test message for {ctx.repo}; nothing is wrong"})
        msg = message.Message(name, ctx.repo, ctx.state_dir / "attention.md", None, 0, [event], None)
        failure = send(ctx, sink, msg.render(sink.format))
        results.append(Delivery(name, "delivered" if failure is None else "failed", failure or ""))
    return results


@dataclass(frozen=True)
class SinkStatus:
    """One sink for `canopy status`: its last delivery, its consecutive failures and last error, events waiting."""

    name: str
    last_delivery_at: str | None
    failures: int
    last_error: str | None
    waiting: int


def status(ctx: Context) -> list[SinkStatus]:
    """Every configured sink as the journal sees it, in name order.

    Returns:
        One status per sink. A sink the journal has no row for yet shows no delivery, no failures, and nothing waiting.
    """
    found: list[SinkStatus] = []
    for name, sink in ctx.config.notify.all_sinks().items():
        row = journal.sink(ctx.conn, name)
        groups = [g for g in sink.events if g in _POINT_GROUPS]
        if row is None:
            found.append(SinkStatus(name, None, 0, None, 0))
            continue
        found.append(
            SinkStatus(
                name,
                row.last_delivery_at,
                row.failures,
                row.last_error,
                journal.waiting(ctx.conn, row.cursor, groups),
            ),
        )
    return found


def _record_loop_events(ctx: Context) -> None:
    """Record `loop.failing` once when the latest ticks all failed, and `loop.recovered` at the first `ok` after it."""
    latest = sql.execute(
        ctx.conn,
        sql.select("id, status").from_("ticks").where("status != 'running'").order_by("id DESC").limit(1),
    ).fetchone()
    if latest is None:
        return
    tick_id, status = int(latest[0]), str(latest[1])
    # Pruning always keeps the newest of these (journal.prune_events), so a long streak is never taken for a new one.
    last = sql.execute(
        ctx.conn,
        sql.select("kind")
        .from_("notify_events")
        .where("kind IN ('loop.failing', 'loop.recovered')")
        .order_by("id DESC")
        .limit(1),
    ).fetchone()
    failing = last is not None and last[0] == "loop.failing"
    if status == "ok":
        if failing:
            db.record_event(ctx.conn, outbox.loop_recovered(_failed_before(ctx.conn, tick_id)))
        return
    streak = _failed_before(ctx.conn, tick_id + 1)
    if streak >= FAILING_AFTER and not failing:
        log_path = ctx.state_dir / "ticks" / f"{tick_id}.log"
        db.record_event(ctx.conn, outbox.loop_failing(streak, status, tick_id, str(log_path)))


def _record_budget_event(ctx: Context, now: datetime) -> None:
    """Record `loop.budget_reached` when the local month's spend reaches one of its alerts, 100% of the budget or more.

    One event for the highest alert reached, never one for each passed on the way, and only for an amount above the
    last told this month: a budget raised, or an alert added, past the month's spend is heard of once the spend reaches
    it, while one lowered or added below it is not, since the sink already heard of more.
    """
    found = spend.budget_month(ctx.conn, now, ctx.config.spend, state_dir=ctx.state_dir)
    if found is None or found.reached is None:
        return
    # Pruning always keeps the newest of these (journal.prune_events), so a month already told is never taken for new.
    last = sql.execute(
        ctx.conn,
        sql.select("fields")
        .from_("notify_events")
        .where("kind = ?", outbox.BUDGET_REACHED)
        .order_by("id DESC")
        .limit(1),
    ).fetchone()
    told = contract.stored_object(str(last[0])) if last is not None else {}
    budget, percent = told.get("budget"), told.get("percent")
    heard = budget * percent if isinstance(budget, int) and isinstance(percent, int) else 0
    if told.get("month") == found.month and heard >= found.budget_usd * found.reached:
        return
    db.record_event(ctx.conn, outbox.budget_reached(found, found.reached))


def _failed_before(conn: sqlite3.Connection, tick_id: int) -> int:
    """How many ended ticks before `tick_id` failed since the last `ok` one: the whole streak, however long.

    Returns:
        The count, 0 when the last ended tick before `tick_id` was `ok`.
    """
    last_ok = sql.select("max(id)").from_("ticks").where("id < ?", tick_id).where("status = 'ok'")
    q = (
        sql.select("count(*)")
        .from_("ticks")
        .where("id < ?", tick_id)
        .where("status NOT IN ('running', 'ok')")
        .where("id > coalesce(({}), 0)", last_ok)
    )
    return int(sql.execute(conn, q).fetchone()[0])


def _deliver(
    ctx: Context,
    name: str,
    sink: Sink,
    items: Sequence[Item],
    *,
    path: Path,
    now: datetime,
    log: logs.TickAdapter,
    dismissed: Collection[str],
    ui: str | None,
) -> Delivery:
    row = journal.ensure_sink(ctx.conn, name)
    groups = [g for g in sink.events if g in _POINT_GROUPS]
    # Read first: a detached `_run` may record an event while this sink is served, and the cursor must not pass it.
    cursor = journal.newest_event_id(ctx.conn)
    events = [message.Event.of(e) for e in journal.events_after(ctx.conn, row.cursor, groups, cursor)]
    change = journal.diff(ctx.conn, name, items, dismissed) if "attention" in sink.events else None
    digest = None
    if _digest_due(row, sink, now) and sink.digest_every_minutes is not None:
        # The first digest covers one interval back, or, under a spend floor, back to when the sink was added too, so
        # what it waits for adds up from there.
        first = db.format_time(now - timedelta(minutes=sink.digest_every_minutes))
        if sink.digest_min_usd is not None:
            first = min(first, row.created_at)
        since = row.last_digest_at or first
        digest = message.digest(ctx.conn, items, since=since, now=now, state_dir=ctx.state_dir)
        # canopy's runs alone: the operator's own sessions outside canopy are no news of the loop's to send.
        if sink.digest_min_usd is not None and (digest.costs.runs or 0.0) < sink.digest_min_usd:
            # It waits: `since` stays, so the next tick's digest counts this spend and whatever comes after it.
            digest = None
    msg = message.Message(
        name,
        ctx.repo,
        path,
        change,
        len(items),
        events,
        digest,
        now,
        titles=message.titles(ctx.conn),
        ui=ui,
    )
    if msg.is_empty():
        # Nothing to say; the cursor still moves past events of groups this sink does not take.
        (
            records.update(records.NotifySink)
            .set_to("cursor = max(cursor, ?)", cursor)
            .where("name = ?", name)
            .run(ctx.conn)
        )
        return Delivery(name, "nothing")
    fields = {
        "sink": name,
        "added": len(change.added) if change else 0,
        "resolved": len(change.resolved) if change else 0,
        "events": len(events),
        "digest": digest is not None,
    }
    if _batching(row, sink, now) and not _urgent(change, events):
        # Nothing moves: the next tick gathers all of this again, with whatever happened since.
        log.info("notification held", extra=fields)
        return Delivery(name, "held")
    failure = send(ctx, sink, msg.render(sink.format))
    if failure is None:
        journal.mark_delivered(ctx.conn, name, change, cursor=cursor, digest=digest is not None)
        log.info("notified", extra=fields)
        return Delivery(name, "delivered")
    # The count and its alert are one write, so a stop between them cannot skip the alert for this streak.
    with db.transaction(ctx.conn):
        failures = journal.mark_failed(ctx.conn, name, failure)
        if failures == FAILING_AFTER and ctx.config.notify.takes(outbox.LOOP):
            db.record_event(ctx.conn, outbox.sink_failing(name, failure))
    log.warning("notify command failed", extra={**fields, "error": failure, "failures": failures})
    return Delivery(name, "failed", failure)


def _batching(row: records.NotifySink, sink: Sink, now: datetime) -> bool:
    """Whether the sink is inside its batch window.

    Returns:
        True when it batches and its last delivery was less than `batch_minutes` ago; never before its first.
    """
    if sink.batch_minutes is None or row.last_delivery_at is None:
        return False
    return now - db.parse_time(row.last_delivery_at) < timedelta(minutes=sink.batch_minutes)


def _urgent(change: journal.Diff | None, events: Iterable[message.Event]) -> bool:
    """Whether a message needs the operator now, so a batching sink sends it at once.

    Returns:
        True for a new attention item, a blocked run's question, or the loop or a sink failing.
    """
    if change is not None and change.added:
        return True
    return any(
        e.kind in _URGENT_KINDS or (e.kind in _ASKING_KINDS and e.fields.get("status") == "blocked") for e in events
    )


def _digest_due(row: records.NotifySink, sink: Sink, now: datetime) -> bool:
    if sink.digest_every_minutes is None:
        return False
    if row.last_digest_at is None:
        return True
    return now - db.parse_time(row.last_digest_at) >= timedelta(minutes=sink.digest_every_minutes)
