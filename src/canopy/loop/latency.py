"""How long an external event waits for the tick that acts on it (DESIGN §6, §39; ROADMAP M39's re-measurement).

An external event is an item a source observed on a ticket, carrying the source's own time: a tracker comment on the
ticket, not one of the workers' own (D069), and a review or a review comment of one of its units' PRs. A check run of
such a PR, observed completed, is counted too, but the contract gives it no time of its own, so only canopy's part of
its wait is known. An item a source first observed is known to canopy from its journal number (§35); a review or a
review comment with no time, and an item on a PR no ticket's unit names, are not counted.

The tick that acted on an item is the first live tick, by when it started, that recorded a decision about the item's
ticket at or after canopy first observed the item: the harness's or the overseer's, but not a cursor the harness moved
(`harness.CURSOR_ACTION`), which decides nothing about the ticket, nor a refusal. A dry run acts on nothing. An item no
tick has acted on yet is counted as not acted on, never dropped.

The tick had the item from when it started, or from when its own read observed it, if that was later: an item a
tick's own read of the sources first observed is credited to that tick, not the next. The latency is from the item's
time at its source to then, and canopy's own part of it from when canopy first observed the item to then. Read only,
over a window of local days by the item's source time (`spend.window`), a check run's by when it was first observed.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db, health, records, spend, sql
from canopy.core.vocab import NumberedItem, ReviewItem
from canopy.loop import harness

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from canopy.loop import tick

#: The kinds of item counted, in the order the report lists them: a review run is canopy's own, never external.
KINDS: Sequence[NumberedItem] = (
    NumberedItem.COMMENT,
    NumberedItem.REVIEW,
    NumberedItem.REVIEW_COMMENT,
    NumberedItem.CHECK_RUN,
)
#: What `ticks.woken_by` says of a tick a poll of the connectors woke (DESIGN §39).
POLL: tick.WokenBy = "poll"
#: The share of the items whose latency the high figure is at or above.
_HIGH = 0.9


@dataclass(frozen=True)
class KindLatency:
    """The items of one kind in the window, how many a tick acted on, and how long they waited for it.

    Each duration is in seconds; None when no item it reads has one.
    """

    #: The kind of item, a journal number's (`NumberedItem`); `all` for every kind together.
    kind: str
    items: int
    #: The items a tick acted on; the rest are not acted on yet.
    acted: int
    #: Of those, the items whose acting tick a poll woke.
    by_poll: int
    #: The median and 90th percentile, by the nearest rank, of the latency from the item's source time.
    median: float | None
    p90: float | None
    #: The median of canopy's own part, from when it first observed the item.
    observed_median: float | None

    @property
    def not_acted(self) -> int:
        """The items no tick has acted on yet."""
        return self.items - self.acted

    def as_json(self) -> dict[str, object]:
        """Return the counts and durations as one JSON object.

        Returns:
            `kind`, `items`, `acted`, `by_poll`, `not_acted`, and `median_s`, `p90_s`, and `observed_median_s`, each
            in seconds to a tenth, or null.
        """
        return {
            "kind": self.kind,
            "items": self.items,
            "acted": self.acted,
            "by_poll": self.by_poll,
            "not_acted": self.not_acted,
            "median_s": _tenths(self.median),
            "p90_s": _tenths(self.p90),
            "observed_median_s": _tenths(self.observed_median),
        }


@dataclass(frozen=True)
class Latencies:
    """How long the external events of a window, `[since, until)`, waited for the tick that acted on them."""

    since: str
    until: str
    days: int
    #: A row per kind, in `KINDS`' order, each kind there whether or not the window holds one.
    kinds: Sequence[KindLatency]
    #: Every kind together: its latency reads the items with a source time, so no check run.
    total: KindLatency

    def as_json(self) -> dict[str, object]:
        """Return the report as one JSON object.

        Returns:
            `since`, `until`, `days`, `kinds`, a list of each kind's row, and `total`, as `KindLatency.as_json` gives.
        """
        return {
            "since": self.since,
            "until": self.until,
            "days": self.days,
            "kinds": [k.as_json() for k in self.kinds],
            "total": self.total.as_json(),
        }


@dataclass(frozen=True)
class _Item(records.View):
    """An external event in the window: its kind, its ticket, and when its source and canopy first had it."""

    kind: NumberedItem
    ticket: str
    #: The source's own time; None for a check run, whose contract gives none.
    source_at: str | None
    observed_at: str


@dataclass(frozen=True)
class _Acted(records.View):
    """The tick that acted on an item: when it started, and what started it."""

    started_at: str
    woken_by: str | None


@dataclass(frozen=True)
class _Waited:
    """One item as measured: its kind, and, once a tick acted on it, how long it waited and what woke that tick."""

    kind: NumberedItem
    #: The seconds from the source's time; None for a check run, or an item not acted on.
    latency: float | None
    #: The seconds from canopy first observing it; None for an item not acted on.
    observed: float | None
    by_poll: bool


def measure(conn: sqlite3.Connection, now: datetime, days: int) -> Latencies:
    """Measure the external events of the last `days` local days, today's so far included.

    Returns:
        A row per kind of item, and one for every kind together.
    """
    start, end = spend.window(now, days)
    since, until = db.format_time(start), db.format_time(end)
    waited = [_waited(conn, item) for item in records.fetch_all(conn, _Item, _items(since, until))]
    kinds = tuple(_row(str(kind), [w for w in waited if w.kind is kind]) for kind in KINDS)
    return Latencies(since=since, until=until, days=days, kinds=kinds, total=_row("all", waited))


def _items(since: str, until: str) -> sql.Select:
    """The query of the external events whose source time, or a check run's first observation, is in the window.

    Returns:
        It, of `_Item`'s columns, oldest first.
    """
    # A review item's or a check run's ticket is the ticket one of whose units names its PR, and an item's first
    # observation its journal number's (§35): a read replaces a review's row, and its `observed_at` with it.
    comments = (
        sql.select(
            "? AS kind, c.ticket AS ticket, c.commented_at AS source_at, "
            "coalesce(n.numbered_at, c.observed_at) AS observed_at",
            NumberedItem.COMMENT,
        )
        .from_("observed_comments c")
        .left_join("item_numbers n ON n.number = c.number")
        # A comment carrying the workers' marks is canopy's own (D069), no external event.
        .where("c.source != ?", "worker")
    )
    reviews = (
        sql.select(
            "CASE WHEN r.item = ? THEN ? ELSE ? END AS kind, "
            "(SELECT min(u.ticket_key) FROM ticket_units u WHERE u.pr_url = r.pr_url) AS ticket, "
            "r.created_at AS source_at, coalesce(n.numbered_at, r.observed_at) AS observed_at",
            ReviewItem.REVIEW,
            NumberedItem.REVIEW,
            NumberedItem.REVIEW_COMMENT,
        )
        .from_("observed_reviews r")
        .left_join("item_numbers n ON n.number = r.number")
        .where("r.created_at IS NOT NULL")
    )
    checks = (
        sql.select(
            "? AS kind, (SELECT min(u.ticket_key) FROM ticket_units u WHERE u.pr_url = k.pr_url) AS ticket, "
            "NULL AS source_at, coalesce(n.numbered_at, k.observed_at) AS observed_at",
            NumberedItem.CHECK_RUN,
        )
        .from_("observed_check_runs k")
        .left_join("item_numbers n ON n.number = k.number")
    )
    return (
        sql.select("kind, ticket, source_at, observed_at")
        .from_("({}) AS i", sql.union(comments, reviews, checks, every=True))
        .where("ticket IS NOT NULL")
        .where("coalesce(source_at, observed_at) >= ? AND coalesce(source_at, observed_at) < ?", since, until)
        .order_by("coalesce(source_at, observed_at), kind")
    )


def _waited(conn: sqlite3.Connection, item: _Item) -> _Waited:
    """Measure one item against the first tick that acted on it.

    Returns:
        How long it waited, or no durations when no tick has acted on it.
    """
    query = (
        sql.select("t.started_at, t.woken_by")
        .from_("decisions d")
        .join("ticks t ON t.id = d.tick_id")
        .where("d.ticket_key = ? AND d.created_at >= ? AND t.dry_run = 0", item.ticket, item.observed_at)
        .where("d.action != ? AND d.action NOT LIKE ?", harness.CURSOR_ACTION, f"{health.REFUSED}%")
        .order_by("t.started_at, t.id")
        .limit(1)
    )
    acted = records.fetch_one(conn, _Acted, query)
    if acted is None:
        return _Waited(item.kind, latency=None, observed=None, by_poll=False)
    observed = db.parse_time(item.observed_at)
    had = max(db.parse_time(acted.started_at), observed)
    latency = None if item.source_at is None else (had - db.parse_time(item.source_at)).total_seconds()
    waited = (had - observed).total_seconds()
    return _Waited(item.kind, latency=latency, observed=waited, by_poll=acted.woken_by == POLL)


def _row(kind: str, waited: Sequence[_Waited]) -> KindLatency:
    """Count and measure `waited`, the items of one kind, or of every kind, as one row.

    Returns:
        The row.
    """
    acted = [w for w in waited if w.observed is not None]
    latencies = sorted(w.latency for w in acted if w.latency is not None)
    observed = [w.observed for w in acted if w.observed is not None]
    return KindLatency(
        kind=kind,
        items=len(waited),
        acted=len(acted),
        by_poll=sum(w.by_poll for w in acted),
        median=statistics.median(latencies) if latencies else None,
        p90=latencies[math.ceil(_HIGH * len(latencies)) - 1] if latencies else None,
        observed_median=statistics.median(observed) if observed else None,
    )


def _tenths(seconds: float | None) -> float | None:
    # A duration for JSON: to a tenth of a second, as the journal's milliseconds overstate.
    return None if seconds is None else round(seconds, 1)
