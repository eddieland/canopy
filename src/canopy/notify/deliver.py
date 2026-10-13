"""Delivering to notification sinks at the end of each tick (DESIGN §6 step 7, §20).

For each sink, in name order: gather its attention diff if it takes `attention`, its events after its cursor in the
groups it takes, and a digest if one is due; render one message in its format; run its command with the message on
stdin. Exit 0 within the timeout is a delivery, recorded in the journal; anything else changes nothing but the sink's
failure count, so the next tick tries again. Sinks run one after another under the tick lock.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import db, outbox
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
_POINT_GROUPS = (outbox.LOOP, outbox.RUNS, outbox.CHORES, outbox.REVIEWS)


@dataclass(frozen=True)
class Delivery:
    """How one sink's delivery went: `delivered`, `nothing` to send, or `failed` with why."""

    sink: str
    outcome: str
    detail: str = ""


def publish(ctx: Context, items: list[Item], path: Path, log: logs.TickAdapter) -> list[Delivery]:
    """Deliver to every configured sink, after recording the loop's own events. Never raises: the tick is closed."""
    sinks = ctx.config.notify.all_sinks()
    for name in journal.forget_sinks(ctx.conn, sinks):
        log.info("notification sink removed from the config; forgot it", extra={"sink": name})
    now = datetime.now(UTC)
    if ctx.config.notify.takes(outbox.LOOP):
        _record_loop_events(ctx)
    deliveries = [_deliver(ctx, name, sink, items, path=path, now=now, log=log) for name, sink in sinks.items()]
    journal.prune_events(ctx.conn, now)
    return deliveries


def send(ctx: Context, sink: Sink, text: str) -> str | None:
    """Run the sink's command with `text` on stdin. Returns None on exit 0, else why it failed."""
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


def test(ctx: Context, names: list[str]) -> list[Delivery]:
    """Send a test message to each sink in `names` now, outside any tick, changing nothing in the journal."""
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
    """Every configured sink as the journal sees it, in name order."""
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
                row["last_delivery_at"],
                int(row["failures"]),
                row["last_error"],
                journal.waiting(ctx.conn, int(row["cursor"]), groups),
            )
        )
    return found


def _record_loop_events(ctx: Context) -> None:
    """Record `loop.failing` once when the latest ticks all failed, and `loop.recovered` at the first `ok` after it."""
    latest = ctx.conn.execute(
        "SELECT id, status FROM ticks WHERE status != 'running' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if latest is None:
        return
    tick_id, status = int(latest[0]), str(latest[1])
    # Pruning always keeps the newest of these (journal.prune_events), so a long streak is never taken for a new one.
    last = ctx.conn.execute(
        "SELECT kind FROM notify_events WHERE kind IN ('loop.failing', 'loop.recovered') ORDER BY id DESC LIMIT 1"
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


def _failed_before(conn: sqlite3.Connection, tick_id: int) -> int:
    """How many ended ticks before `tick_id` failed since the last `ok` one: the whole streak, however long."""
    return int(
        conn.execute(
            "SELECT count(*) FROM ticks WHERE id < ? AND status NOT IN ('running', 'ok') "
            "AND id > coalesce((SELECT max(id) FROM ticks WHERE id < ? AND status = 'ok'), 0)",
            (tick_id, tick_id),
        ).fetchone()[0]
    )


def _deliver(
    ctx: Context, name: str, sink: Sink, items: list[Item], *, path: Path, now: datetime, log: logs.TickAdapter
) -> Delivery:
    row = journal.ensure_sink(ctx.conn, name)
    groups = [g for g in sink.events if g in _POINT_GROUPS]
    # Read first: a detached `_run` may record an event while this sink is served, and the cursor must not pass it.
    cursor = journal.newest_event_id(ctx.conn)
    events = [message.Event.of(e) for e in journal.events_after(ctx.conn, int(row["cursor"]), groups, cursor)]
    change = journal.diff(ctx.conn, name, items) if "attention" in sink.events else None
    digest = None
    if _digest_due(row, sink, now) and sink.digest_every_minutes is not None:
        # The first digest covers one interval back.
        first = db.format_time(now - timedelta(minutes=sink.digest_every_minutes))
        since = str(row["last_digest_at"] or first)
        digest = message.digest(ctx.conn, items, since=since, now=now)
    msg = message.Message(name, ctx.repo, path, change, len(items), events, digest, now)
    if msg.is_empty():
        # Nothing to say; the cursor still moves past events of groups this sink does not take.
        ctx.conn.execute("UPDATE notify_sinks SET cursor = max(cursor, ?) WHERE name = ?", (cursor, name))
        return Delivery(name, "nothing")
    fields = {
        "sink": name,
        "added": len(change.added) if change else 0,
        "resolved": len(change.resolved) if change else 0,
        "events": len(events),
        "digest": digest is not None,
    }
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


def _digest_due(row: sqlite3.Row, sink: Sink, now: datetime) -> bool:
    if sink.digest_every_minutes is None:
        return False
    if row["last_digest_at"] is None:
        return True
    return now - db.parse_time(str(row["last_digest_at"])) >= timedelta(minutes=sink.digest_every_minutes)
