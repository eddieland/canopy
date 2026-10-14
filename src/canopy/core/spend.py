"""What agent runs cost, by what they bought (DESIGN §11; ROADMAP M33), read by `canopy spend` and the web UI.

Reads only. Every cost is what the agent runtime reported (§13), summed by the UTC day a run started on: the overseer
of each tick, worker and split runs, chore runs, and review runs. A dry run's overseer is kept apart from the live
ones', and idle ticks' (§6, Idle pacing) are a series of their own within the live overseer's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import TYPE_CHECKING, Literal

from canopy.core import db

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

type Group = Literal["idle", "busy", "hand_run", "not_ok", "dry_run"]
type Kind = Literal["overseer", "workers", "chores", "reviews"]

# Every tick that ended is in exactly one group, in this order: a dry run first, whatever the loop said of it, then a
# live tick that did not close `ok`, then the loop's word on an `ok` one, idle or not, and last a tick no loop ran.
GROUPS: tuple[Group, ...] = ("idle", "busy", "hand_run", "not_ok", "dry_run")
KINDS: tuple[Kind, ...] = ("overseer", "workers", "chores", "reviews")
# The longest window `canopy spend` and the web UI read, in days; a year keeps the per-day lines bounded.
MAX_DAYS = 366
DEFAULT_DAYS = 7
# The idle ticks the web UI links to: the newest in the window.
IDLE_TICKS = 20

# Each agent run's table but the ticks', by the kind it counts as.
_TABLES: dict[Kind, str] = {"workers": "runs", "chores": "chore_runs", "reviews": "review_runs"}
# The overseer's series, each from the ticks.
_SERIES = ("overseer", "idle", "dry_run")


@dataclass(frozen=True)
class Costs:
    """What each kind of agent run cost, in US dollars; None for a kind none of whose runs reported a cost.

    `overseer` is the live ticks' overseers, `idle` the part of it idle ticks spent, and `dry_run` the dry runs'
    overseers, apart from it.
    """

    overseer: float | None = None
    idle: float | None = None
    dry_run: float | None = None
    workers: float | None = None
    chores: float | None = None
    reviews: float | None = None

    @property
    def total(self) -> float | None:
        """Everything, dry runs included, as the web UI's 24 hour and 30 day counters count it; None when none did."""
        return _sum([self.overseer, self.dry_run, self.workers, self.chores, self.reviews])


@dataclass(frozen=True)
class Day:
    """One UTC day's costs, `day` as `YYYY-MM-DD`."""

    day: str
    costs: Costs


@dataclass(frozen=True)
class TickGroup:
    """How many ended ticks of the window are in a group, and what their overseers cost."""

    group: Group
    ticks: int
    cost_usd: float | None


@dataclass(frozen=True)
class Woken:
    """How many of the loop's ticks one cause woke (`ticks.woken_by`, §6), and what their overseers cost."""

    by: str
    ticks: int
    cost_usd: float | None


@dataclass(frozen=True)
class Unpriced:
    """How many of a kind's ended runs in the window reported no cost, of how many."""

    kind: Kind
    runs: int
    unpriced: int


@dataclass(frozen=True)
class Breakdown:
    """The window's spend: per day, oldest first, every day in it listed; in total; and by what the ticks bought."""

    since: str
    days: int
    per_day: list[Day]
    totals: Costs
    ticks: list[TickGroup]
    woken: list[Woken]
    unpriced: list[Unpriced]
    idle_share: float | None = None


def window_start(now: datetime, days: int) -> datetime:
    """The window's start: midnight UTC, `days - 1` days before `now`'s day, so `days` UTC days end with today.

    Returns:
        An aware UTC datetime.
    """
    today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=days - 1)


def breakdown(conn: sqlite3.Connection, now: datetime, days: int) -> Breakdown:
    """What the last `days` UTC days cost, today's so far included, by day, by kind, and by what the ticks bought.

    Returns:
        The breakdown; a window with nothing in it lists each day with no costs.
    """
    start = window_start(now, days)
    since = db.format_time(start)
    rows = _tick_rows(conn, since)
    by_day: dict[str, dict[str, float | None]] = {}
    for kind, table in _TABLES.items():
        for day, cost in conn.execute(
            f"SELECT substr(started_at, 1, 10) AS day, SUM(cost_usd) FROM {table} "  # noqa: S608 (a fixed table)
            "WHERE started_at >= ? GROUP BY day",
            (since,),
        ):
            by_day.setdefault(str(day), {})[kind] = cost
    for row in rows:
        day = by_day.setdefault(row.day, {})
        for name in _SERIES:
            if _in_series(row, name):
                day[name] = _sum([day.get(name), row.cost_usd])
    names = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    per_day = [Day(day=d, costs=_costs(by_day.get(d, {}))) for d in names]
    totals = _costs({n: _sum([by_day.get(d, {}).get(n) for d in names]) for n in (*_SERIES, *_TABLES)})
    return Breakdown(
        since=since,
        days=days,
        per_day=per_day,
        totals=totals,
        ticks=_groups(rows),
        woken=_woken(rows),
        unpriced=_unpriced(conn, since, rows),
        idle_share=(totals.idle or 0.0) / totals.overseer if totals.overseer else None,
    )


def idle_ticks(conn: sqlite3.Connection, since: str, limit: int = IDLE_TICKS) -> list[sqlite3.Row]:
    """The newest live idle ticks that started at or after `since`, newest first, each with its `decisions` count.

    Returns:
        At most `limit` rows of `ticks`, as `db.recent_ticks` reads them.
    """
    return conn.execute(
        "SELECT t.*, (SELECT count(*) FROM decisions d WHERE d.tick_id = t.id) AS decisions FROM ticks t "
        "WHERE t.started_at >= ? AND t.dry_run = 0 AND t.idle = 1 ORDER BY t.id DESC LIMIT ?",
        (since, limit),
    ).fetchall()


@dataclass(frozen=True)
class _TickRow:
    """Ticks of one day that share a group, a status, and a cause: how many, and what their overseers cost."""

    day: str
    group: Group | None
    woken_by: str | None
    ticks: int
    cost_usd: float | None


def _tick_rows(conn: sqlite3.Connection, since: str) -> list[_TickRow]:
    rows = conn.execute(
        "SELECT substr(started_at, 1, 10) AS day, dry_run, status, idle, woken_by, count(*), SUM(cost_usd) "
        "FROM ticks WHERE started_at >= ? GROUP BY day, dry_run, status, idle, woken_by",
        (since,),
    ).fetchall()
    return [
        _TickRow(
            day=str(day),
            group=_group(str(status), idle, dry=bool(dry)),
            woken_by=None if woken is None else str(woken),
            ticks=int(count),
            cost_usd=cost,
        )
        for day, dry, status, idle, woken, count, cost in rows
    ]


# A still running tick is in no group yet.
def _group(status: str, idle: int | None, *, dry: bool) -> Group | None:
    if status == "running":
        return None
    if dry:
        return "dry_run"
    if status != "ok":
        return "not_ok"
    if idle is None:
        return "hand_run"
    return "idle" if idle else "busy"


# Whether a tick row's cost counts toward the `overseer`, `idle`, or `dry_run` cost of its day.
def _in_series(row: _TickRow, name: str) -> bool:
    if name == "dry_run":
        return row.group == "dry_run"
    if name == "idle":
        return row.group == "idle"
    return row.group != "dry_run"


def _groups(rows: list[_TickRow]) -> list[TickGroup]:
    return [
        TickGroup(
            group=g,
            ticks=sum(r.ticks for r in rows if r.group == g),
            cost_usd=_sum([r.cost_usd for r in rows if r.group == g]),
        )
        for g in GROUPS
    ]


# The live ticks the loop ran, by what ended the wait before each, the most common first.
def _woken(rows: list[_TickRow]) -> list[Woken]:
    causes = sorted({r.woken_by for r in rows if r.woken_by is not None and r.group not in {None, "dry_run"}})
    found = [
        Woken(
            by=cause,
            ticks=sum(r.ticks for r in rows if r.woken_by == cause and r.group not in {None, "dry_run"}),
            cost_usd=_sum([r.cost_usd for r in rows if r.woken_by == cause and r.group not in {None, "dry_run"}]),
        )
        for cause in causes
    ]
    return sorted(found, key=lambda w: -w.ticks)


def _unpriced(conn: sqlite3.Connection, since: str, rows: list[_TickRow]) -> list[Unpriced]:
    ended = [r for r in rows if r.group is not None]
    found = [
        Unpriced(
            kind="overseer",
            runs=sum(r.ticks for r in ended),
            # A grouped row's sum is NULL only when none of its ticks reported a cost; count those ticks one by one.
            unpriced=int(
                conn.execute(
                    "SELECT count(*) FROM ticks WHERE started_at >= ? AND status != 'running' AND cost_usd IS NULL",
                    (since,),
                ).fetchone()[0]
            ),
        )
    ]
    for kind, table in _TABLES.items():
        runs, unpriced = conn.execute(
            f"SELECT count(*), count(*) - count(cost_usd) FROM {table} "  # noqa: S608 (a fixed table)
            "WHERE started_at >= ? AND status != 'running'",
            (since,),
        ).fetchone()
        found.append(Unpriced(kind=kind, runs=int(runs), unpriced=int(unpriced)))
    return found


def _costs(found: dict[str, float | None]) -> Costs:
    return Costs(
        overseer=found.get("overseer"),
        idle=found.get("idle"),
        dry_run=found.get("dry_run"),
        workers=found.get("workers"),
        chores=found.get("chores"),
        reviews=found.get("reviews"),
    )


# The sum of the values that are not None; None when every one is.
def _sum(values: list[float | None]) -> float | None:
    parts = [float(v) for v in values if v is not None]
    return sum(parts) if parts else None
