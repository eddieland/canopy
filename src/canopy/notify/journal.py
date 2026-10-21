"""What the journal holds for notification sinks (DESIGN §20).

Each sink's cursor and failures, the attention items it was told about, and the event outbox.
"""

from __future__ import annotations

import operator
import sqlite3
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from canopy.core import db, records, sql
from canopy.core.items import Item, fingerprint, subject

# Events every sink has passed are deleted once they are this old.
KEEP_EVENTS = timedelta(days=7)


def newest_event_id(conn: sqlite3.Connection) -> int:
    """The highest event id ever given out, pruned or not: AUTOINCREMENT never gives it out again.

    Returns:
        The id, or 0 before the first event.
    """
    row = sql.execute(conn, sql.select("seq").from_("sqlite_sequence").where("name = 'notify_events'")).fetchone()
    return int(row[0]) if row is not None else 0


def sink(conn: sqlite3.Connection, name: str) -> records.NotifySink | None:
    """Return sink `name`'s row, or None if it has never been published to."""
    return records.fetch_one(conn, records.NotifySink, sql.select("*").from_("notify_sinks").where("name = ?", name))


def ensure_sink(conn: sqlite3.Connection, name: str) -> records.NotifySink:
    """Return sink `name`'s row, creating it with its cursor at the newest event: a new sink gets no backlog.

    Raises:
        RuntimeError: The row is missing right after it was inserted.
    """
    sql.execute(
        conn,
        sql.insert("notify_sinks", name=name, cursor=newest_event_id(conn), created_at=db.now()).on_conflict(
            "(name) DO NOTHING",
        ),
    )
    row = sink(conn, name)
    if row is None:
        raise RuntimeError(f"sink {name} vanished")
    return row


def forget_sinks(conn: sqlite3.Connection, keep: Iterable[str]) -> list[str]:
    """Delete the rows of sinks no longer configured, and what they were told.

    Returns:
        The names forgotten, sorted.
    """
    kept = set(keep)
    names = {str(r[0]) for r in sql.execute(conn, sql.select("name").from_("notify_sinks"))}
    names |= {str(r[0]) for r in sql.execute(conn, sql.select("sink").unique().from_("notifications"))}
    gone = sorted(names - kept)
    with db.transaction(conn):
        for name in gone:
            sql.execute(conn, sql.delete("notify_sinks").where("name = ?", name))
            sql.execute(conn, sql.delete("notifications").where("sink = ?", name))
    return gone


def events_after(
    conn: sqlite3.Connection,
    cursor: int,
    groups: Sequence[str],
    upto: int | None = None,
) -> list[records.NotifyEvent]:
    """Return the events after `cursor`, and up to `upto` if given, in `groups`, oldest first."""
    if not groups:
        return []
    q = (
        sql.select("*")
        .from_("notify_events")
        .where("id > ?", cursor)
        .where("id <= ?", upto if upto is not None else newest_event_id(conn))
        .where_in("grp", groups)
        .order_by("id")
    )
    return records.fetch_all(conn, records.NotifyEvent, q)


def prune_events(conn: sqlite3.Connection, now: datetime) -> int:
    """Delete events every sink has passed that are older than `KEEP_EVENTS`.

    Returns:
        How many were deleted. The newest `loop.failing` or `loop.recovered` event is kept.
    """
    cursors = [int(r[0]) for r in sql.execute(conn, sql.select("cursor").from_("notify_sinks"))]
    passed = min(cursors) if cursors else newest_event_id(conn)
    # The newest `loop.failing` or `loop.recovered` stays: it is how a long streak is told from a new one.
    marker = sql.execute(
        conn,
        sql.select("coalesce(max(id), 0)").from_("notify_events").where("kind IN ('loop.failing', 'loop.recovered')"),
    ).fetchone()[0]
    cur = sql.execute(
        conn,
        sql.delete("notify_events")
        .where("id <= ?", passed)
        .where("at < ?", db.format_time(now - KEEP_EVENTS))
        .where("id != ?", marker),
    )
    return cur.rowcount


@dataclass(frozen=True)
class Diff:
    """What changed for one sink since its last delivery: new items, and items it was told of that are gone."""

    added: Sequence[Item]
    resolved: Sequence[tuple[str, str]]  # (subject, reason)
    resolved_fingerprints: Sequence[str]
    resolved_items: Sequence[tuple[str | None, str, str | None]]  # (ticket key, reason, repo)
    # Whether each resolved item left because the operator dismissed it rather than because its cause is gone.
    resolved_dismissed: Sequence[bool] = ()

    def __bool__(self) -> bool:
        """Whether anything changed.

        Returns:
            True when there are new items or resolved ones.
        """
        return bool(self.added or self.resolved)


def item_fingerprint(item: Item) -> str:
    """How the journal identifies `item` across ticks.

    Returns:
        The fingerprint of its ticket key, reason, and repository.
    """
    return fingerprint(item.ticket_key, item.reason, item.repo)


def diff(conn: sqlite3.Connection, sink_name: str, items: Sequence[Item], dismissed: Collection[str] = ()) -> Diff:
    """Compare `items` with the open items already delivered to sink `sink_name`.

    `dismissed` holds the fingerprints of chore findings the operator dismissed: still open, but off the list.

    Returns:
        The items the sink was not told of, and those it was told of that are no longer open, by subject and reason,
        each marked whether it was dismissed.
    """
    told = {
        str(r["fingerprint"]): (r["ticket_key"], str(r["reason"]), r["repo"])
        for r in sql.execute(
            conn,
            sql.select("fingerprint, ticket_key, reason, repo").from_("notifications").where("sink = ?", sink_name),
        )
    }
    now_open = {item_fingerprint(i) for i in items}
    added = [i for i in items if item_fingerprint(i) not in told]
    gone = sorted(
        ((subject(key, repo), reason, fp, (key, reason, repo)) for fp, (key, reason, repo) in told.items()),
        key=operator.itemgetter(0, 1),
    )
    gone = [g for g in gone if g[2] not in now_open]
    return Diff(
        added,
        [(g[0], g[1]) for g in gone],
        [g[2] for g in gone],
        [g[3] for g in gone],
        [g[2] in dismissed for g in gone],
    )


def mark_delivered(conn: sqlite3.Connection, sink_name: str, change: Diff | None, *, cursor: int, digest: bool) -> None:
    """Record a delivery: the diff's new items told, its resolved ones forgotten, the cursor moved, failures reset."""
    ts = db.now()
    with db.transaction(conn):
        if change is not None:
            sql.execute(
                conn,
                sql.delete("notifications")
                .where("sink = ?", sink_name)
                .where_in("fingerprint", change.resolved_fingerprints),
            )
            sql.execute_many(
                conn,
                sql.insert_rows(
                    "notifications",
                    ("sink", "fingerprint", "ticket_key", "reason", "repo", "sent_at"),
                ).or_replace(),
                [(sink_name, item_fingerprint(i), i.ticket_key, i.reason, i.repo, ts) for i in change.added],
            )
        sql.execute(
            conn,
            sql.update("notify_sinks")
            .set_to("cursor = max(cursor, ?)", cursor)
            .set(last_delivery_at=ts, failures=0, last_error=None)
            .where("name = ?", sink_name),
        )
        if digest:
            sql.execute(conn, sql.update("notify_sinks").set(last_digest_at=ts).where("name = ?", sink_name))


def mark_failed(conn: sqlite3.Connection, sink_name: str, error: str) -> int:
    """Count a failed delivery.

    Returns:
        How many deliveries in a row have failed, or 0 when the sink has no row.
    """
    sql.execute(
        conn,
        sql.update("notify_sinks")
        .set_to("failures = failures + 1")
        .set(last_error=error[-500:])
        .where("name = ?", sink_name),
    )
    row = sink(conn, sink_name)
    return row.failures if row is not None else 0


def waiting(conn: sqlite3.Connection, cursor: int, groups: Sequence[str]) -> int:
    """How many events in `groups` wait for a sink whose cursor is `cursor`.

    Returns:
        The count of events after `cursor`, up to the newest.
    """
    return len(events_after(conn, cursor, groups))
