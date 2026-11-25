"""How long an external event waits for the tick that acts on it (DESIGN §6, §39; ROADMAP M39's re-measurement).

An external event is an item a source observed on a ticket, carrying the source's own time: a tracker comment on the
ticket, not one of the workers' own (D069), and a review, review comment, or PR comment of one of its units' PRs. A
check run of such a PR, observed completed, and a commit status's run, observed ended, are counted too, but the contract
gives neither a time of its own, so only canopy's part of its wait is known. An item a source first observed is known
to canopy from its journal number (§35), a status run, which takes none, from when a source first observed it ended; a
review or a review comment with no time, and an item on a PR no ticket's unit names, are not counted.

An item a connector backfilled is counted apart, in no other count: one first observed by canopy's first read of its
kind on its subject, its PR or, for a tracker comment, its ticket, the first journal number of that kind there, and
made before canopy first observed any item of its kind. It was there before canopy read its kind at all, as when a
release begins to read a kind, so its wait is the release's, not the loop's. An item first in its kind on a PR canopy
was already reading that kind on, such as a PR's first review, is a wait like any other. The journal keeps no read that
found nothing, so the items of the first read in a workspace to observe any of a kind are counted apart too, even when
canopy had read that kind long before. A CI run has no source time to tell one by, so none is backfilled.

The tick that acted on an item is the first live tick, by when it started, that recorded a decision about the item's
ticket at or after canopy first observed the item: the harness's or the overseer's, but not a cursor the harness moved
(`harness.CURSOR_ACTION`), which decides nothing about the ticket, nor a refusal. A dry run acts on nothing. An item no
tick has acted on yet is counted as not acted on, never dropped.

The tick had the item from when it started, or from when its own read observed it, if that was later: an item a
tick's own read of the sources first observed is credited to that tick, not the next. The latency is from the item's
time at its source to then, and canopy's own part of it from when canopy first observed the item to then. Read only,
over a window of local days by the item's source time (`spend.window`), a check or status run's by when it was first
observed; split, when asked, by that time's local day or local hour of the day, every kind together.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Literal, assert_never

from canopy.core import db, health, records, spend, sql
from canopy.core.vocab import ReviewItem
from canopy.loop import harness

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from canopy.loop import tick


class Kind(StrEnum):
    """What an item counted is: a journal number's kind (`NumberedItem`), or a commit status's run, which takes none."""

    COMMENT = "comment"
    REVIEW = "review"
    REVIEW_COMMENT = "review_comment"
    PR_COMMENT = "pr_comment"
    CHECK_RUN = "check_run"
    STATUS_RUN = "status_run"


#: How a report may split its items: by local day of the window, or by local hour of the day across it.
type By = Literal["day", "hour"]

#: The kinds of item counted, in the order the report lists them: a review run is canopy's own, never external.
KINDS: Final[Sequence[Kind]] = tuple(Kind)
#: The splits a report may ask for.
BY: Final[Sequence[By]] = ("day", "hour")
#: What `ticks.woken_by` says of a tick a poll of the connectors woke (DESIGN §39).
POLL: Final[tick.WokenBy] = "poll"
#: The share of the items whose latency the high figure is at or above.
_HIGH: Final = 0.9
#: The hours of a day, as a split by hour names them.
_HOURS: Final = tuple(f"{hour:02d}" for hour in range(24))
#: When canopy first observed any item of each kind, joined as `f` to an item's journal number, `n`.
_FIRST_OF_KIND: Final = (
    "(SELECT kind, min(numbered_at) AS first_at FROM item_numbers GROUP BY kind) f ON f.kind = n.kind"
)
#: Whether an item with a journal number, `n`, was backfilled: first observed in the first read of its kind on its
#: subject, and made, at its source time, the `{}`, before canopy first observed any item of its kind. NULL, so false,
#: for an item with no number.
_BACKFILLED: Final = (
    "n.numbered_at = (SELECT min(s.numbered_at) FROM item_numbers s WHERE s.subject = n.subject AND s.kind = n.kind) "
    "AND {} < f.first_at"
)


@dataclass(frozen=True)
class Item:
    """One external event in the window, as measured: what it is, when it was had, and how long it waited."""

    kind: Kind
    ticket: str
    #: The source's own time; None for a check or status run, whose contract gives none.
    source_at: str | None
    #: When canopy first observed it.
    observed_at: str
    #: Whether a connector backfilled it: counted apart, in no other count.
    backfilled: bool
    #: When the tick that acted on it had it; None when no tick has acted on it.
    acted_at: str | None
    #: The seconds from the source's time to `acted_at`; None without either.
    latency: float | None
    #: The seconds from canopy first observing it to `acted_at`; None when no tick has acted on it.
    observed: float | None
    #: Whether a poll of the connectors woke the tick that acted on it.
    by_poll: bool

    @property
    def at(self) -> str:
        """The time the window and a split read it by: its source time, or a check or status run's observation."""
        return self.observed_at if self.source_at is None else self.source_at

    def as_json(self) -> dict[str, object]:
        """Return the item as one JSON object.

        Returns:
            Its fields, each journal time as the journal holds it, and `latency_s` and `observed_s` in seconds to a
            tenth, or null.
        """
        return {
            "kind": str(self.kind),
            "ticket": self.ticket,
            "source_at": self.source_at,
            "observed_at": self.observed_at,
            "backfilled": self.backfilled,
            "acted_at": self.acted_at,
            "by_poll": self.by_poll,
            "latency_s": _tenths(self.latency),
            "observed_s": _tenths(self.observed),
        }


@dataclass(frozen=True)
class KindLatency:
    """The items of one kind in the window, how many a tick acted on, and how long they waited for it.

    Each duration is in seconds; None when no item it reads has one. A backfilled item is in no count but its own.
    """

    #: The kind of item, a `Kind`; `all` for every kind together.
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
    #: The items a connector backfilled, left out of every other count.
    backfilled: int = 0

    @property
    def not_acted(self) -> int:
        """The items no tick has acted on yet."""
        return self.items - self.acted

    def as_json(self) -> dict[str, object]:
        """Return the counts and durations as one JSON object.

        Returns:
            `kind`, `items`, `acted`, `by_poll`, `not_acted`, `backfilled`, and `median_s`, `p90_s`, and
            `observed_median_s`, each in seconds to a tenth, or null.
        """
        return {
            "kind": self.kind,
            "items": self.items,
            "acted": self.acted,
            "by_poll": self.by_poll,
            "not_acted": self.not_acted,
            "backfilled": self.backfilled,
            "median_s": _tenths(self.median),
            "p90_s": _tenths(self.p90),
            "observed_median_s": _tenths(self.observed_median),
        }


@dataclass(frozen=True)
class Bucket:
    """The items of one local day of the window, or of one local hour of the day across it, every kind together."""

    #: The day, `YYYY-MM-DD`, or the hour, `00` to `23`.
    at: str
    total: KindLatency

    def as_json(self) -> dict[str, object]:
        """Return the bucket as one JSON object.

        Returns:
            `at`, then its counts and durations as `KindLatency.as_json` gives them, but for the kind.
        """
        counts = self.total.as_json()
        del counts["kind"]
        return {"at": self.at, **counts}


@dataclass(frozen=True)
class Latencies:
    """How long the external events of a window, `[since, until)`, waited for the tick that acted on them."""

    since: str
    until: str
    days: int
    #: A row per kind, in `KINDS`' order, each kind there whether or not the window holds one.
    kinds: Sequence[KindLatency]
    #: Every kind together: its latency reads the items with a source time, so no check or status run.
    total: KindLatency
    #: Each item of the window, oldest first, a backfilled one included.
    items: Sequence[Item] = ()
    #: How `buckets` splits the items; None for no split.
    by: By | None = None
    #: A row per local day of the window, or per local hour of the day, each whether or not it holds an item.
    buckets: Sequence[Bucket] = ()

    def as_json(self) -> dict[str, object]:
        """Return the report as one JSON object.

        Returns:
            `since`, `until`, `days`, `kinds`, a list of each kind's row, and `total`, as `KindLatency.as_json` gives;
            `by` and `buckets`, each bucket's row as `Bucket.as_json` gives, when split; and `items`, each item as
            `Item.as_json` gives.
        """
        found: dict[str, object] = {
            "since": self.since,
            "until": self.until,
            "days": self.days,
            "kinds": [k.as_json() for k in self.kinds],
            "total": self.total.as_json(),
        }
        if self.by is not None:
            found["by"] = self.by
            found["buckets"] = [b.as_json() for b in self.buckets]
        found["items"] = [i.as_json() for i in self.items]
        return found


@dataclass(frozen=True)
class _Item(records.View):
    """An external event in the window, as its query reads it: what it is, and when its source and canopy had it."""

    kind: Kind
    ticket: str
    #: The source's own time; None for a check or status run, whose contract gives none.
    source_at: str | None
    observed_at: str
    #: Whether a connector backfilled it.
    backfilled: bool


@dataclass(frozen=True)
class _Acted(records.View):
    """The tick that acted on an item: when it started, and what started it."""

    started_at: str
    woken_by: str | None


def measure(conn: sqlite3.Connection, now: datetime, days: int, by: By | None = None) -> Latencies:
    """Measure the external events of the last `days` local days, today's so far included.

    Returns:
        A row per kind of item, one for every kind together, each item, and, split `by`, a row per bucket.
    """
    start, end = spend.window(now, days)
    since, until = db.format_time(start), db.format_time(end)
    items = [_measured(conn, item) for item in records.fetch_all(conn, _Item, _items(since, until))]
    kinds = tuple(_row(str(kind), [i for i in items if i.kind is kind]) for kind in KINDS)
    return Latencies(
        since=since,
        until=until,
        days=days,
        kinds=kinds,
        total=_row("all", items),
        items=items,
        by=by,
        buckets=() if by is None else _buckets(items, by, start, days),
    )


def _items(since: str, until: str) -> sql.Select:
    """The query of the external events whose source time, or a CI run's first observation, is in the window.

    Returns:
        It, of `_Item`'s columns, oldest first.
    """
    # A review item's or a CI run's ticket is the ticket one of whose units names its PR, and an item's first
    # observation its journal number's (§35): a read replaces a review's row, and its `observed_at` with it.
    comments = (
        sql.select(
            "? AS kind, c.ticket AS ticket, c.commented_at AS source_at, "
            "coalesce(n.numbered_at, c.observed_at) AS observed_at, "
            "CASE WHEN {} THEN 1 ELSE 0 END AS backfilled",
            Kind.COMMENT,
            sql.frag(_BACKFILLED, sql.frag("c.commented_at")),
        )
        .from_("observed_comments c")
        .left_join("item_numbers n ON n.number = c.number")
        .left_join(_FIRST_OF_KIND)
        # A comment carrying the workers' marks is canopy's own (D069), no external event.
        .where("c.source != ?", "worker")
        # An ignored comment has no number, so no first observation to measure from.
        .where("c.ignored = 0")
    )
    reviews = (
        sql.select(
            "CASE r.item WHEN ? THEN ? WHEN ? THEN ? ELSE ? END AS kind, "
            "(SELECT min(u.ticket_key) FROM ticket_units u WHERE u.pr_url = r.pr_url) AS ticket, "
            "r.created_at AS source_at, coalesce(n.numbered_at, r.observed_at) AS observed_at, "
            "CASE WHEN {} THEN 1 ELSE 0 END AS backfilled",
            ReviewItem.REVIEW,
            Kind.REVIEW,
            ReviewItem.COMMENT,
            Kind.REVIEW_COMMENT,
            Kind.PR_COMMENT,
            sql.frag(_BACKFILLED, sql.frag("r.created_at")),
        )
        .from_("observed_reviews r")
        .left_join("item_numbers n ON n.number = r.number")
        .left_join(_FIRST_OF_KIND)
        .where("r.created_at IS NOT NULL")
        # An ignored comment has no number, so no first observation to measure from.
        .where("r.ignored = 0 OR r.number IS NOT NULL")
    )
    # A CI run has no source time, so nothing to tell a backfilled one by.
    checks = (
        sql.select(
            "? AS kind, (SELECT min(u.ticket_key) FROM ticket_units u WHERE u.pr_url = k.pr_url) AS ticket, "
            "NULL AS source_at, coalesce(n.numbered_at, k.observed_at) AS observed_at, 0 AS backfilled",
            Kind.CHECK_RUN,
        )
        .from_("observed_check_runs k")
        .left_join("item_numbers n ON n.number = k.number")
    )
    # A status run's row is first observed running, then rewritten when a source first observes it ended: its
    # `observed_at` is then that, as a check run's is.
    statuses = (
        sql.select(
            "? AS kind, (SELECT min(u.ticket_key) FROM ticket_units u WHERE u.pr_url = s.pr_url) AS ticket, "
            "NULL AS source_at, s.observed_at AS observed_at, 0 AS backfilled",
            Kind.STATUS_RUN,
        )
        .from_("observed_status_runs s")
        .where("s.conclusion IS NOT NULL")
    )
    return (
        sql.select("kind, ticket, source_at, observed_at, backfilled")
        .from_("({}) AS i", sql.union(comments, reviews, checks, statuses, every=True))
        .where("ticket IS NOT NULL")
        .where("coalesce(source_at, observed_at) >= ? AND coalesce(source_at, observed_at) < ?", since, until)
        .order_by("coalesce(source_at, observed_at), kind")
    )


def _measured(conn: sqlite3.Connection, item: _Item) -> Item:
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
    found = Item(
        kind=item.kind,
        ticket=item.ticket,
        source_at=item.source_at,
        observed_at=item.observed_at,
        backfilled=item.backfilled,
        acted_at=None,
        latency=None,
        observed=None,
        by_poll=False,
    )
    if acted is None:
        return found
    observed = db.parse_time(item.observed_at)
    had = max(db.parse_time(acted.started_at), observed)
    return replace(
        found,
        acted_at=db.format_time(had),
        latency=None if item.source_at is None else (had - db.parse_time(item.source_at)).total_seconds(),
        observed=(had - observed).total_seconds(),
        by_poll=acted.woken_by == POLL,
    )


def _row(kind: str, items: Sequence[Item]) -> KindLatency:
    """Count and measure `items`, of one kind, or of every kind, as one row, a backfilled item only as one.

    Returns:
        The row.
    """
    counted = [i for i in items if not i.backfilled]
    acted = [i for i in counted if i.observed is not None]
    latencies = sorted(i.latency for i in acted if i.latency is not None)
    observed = [i.observed for i in acted if i.observed is not None]
    return KindLatency(
        kind=kind,
        items=len(counted),
        acted=len(acted),
        by_poll=sum(i.by_poll for i in acted),
        median=statistics.median(latencies) if latencies else None,
        p90=latencies[math.ceil(_HIGH * len(latencies)) - 1] if latencies else None,
        observed_median=statistics.median(observed) if observed else None,
        backfilled=len(items) - len(counted),
    )


def _buckets(items: Sequence[Item], by: By, start: datetime, days: int) -> tuple[Bucket, ...]:
    """Split `items` by the local day, or local hour of the day, of the time the window reads each by.

    Returns:
        A bucket per day of the window, or per hour of the day, in order, each whether or not it holds an item.
    """
    match by:
        case "day":
            names = tuple(spend.day_starts(start, days))
            of = [spend.local_day(i.at) for i in items]
        case "hour":
            names = _HOURS
            of = [f"{db.parse_time(i.at).astimezone().hour:02d}" for i in items]
        case _:
            assert_never(by)
    return tuple(
        Bucket(at=name, total=_row("all", [i for i, at in zip(items, of, strict=True) if at == name])) for name in names
    )


def _tenths(seconds: float | None) -> float | None:
    # A duration for JSON: to a tenth of a second, as the journal's milliseconds overstate.
    return None if seconds is None else round(seconds, 1)
