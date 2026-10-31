"""How often running agents' cards went stale, by role, over a window (DESIGN §41, ROADMAP M65).

A run's row counts each time its card went from fresh to stale as a tool call found it (`cards.record_call`), and
whether the card as it stands was counted so. A run that ended with its card stale and not yet counted, as one that went
quiet past the minutes and then ended, lapses once more as it ended: its row holds when it ended, so that last lapse is
read from the row, by the same measure, whichever path ended the run. `canopy cards` prints the counts per role: each
run kind of a worker's or a planner's run as the journal names it, `review`, and `task`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, LiteralString

from canopy.core import cards, db, records, spend, sql
from canopy.core.vocab import RunKind

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

#: The roles that are not a run kind: a review's run, and a one-off task's.
REVIEW = "review"
TASK = "task"


@dataclass(frozen=True)
class RoleLapses:
    """How the cards of one role's runs that started in a window went stale."""

    #: A worker's or a planner's run kind, `review`, or `task`.
    role: str
    #: The runs that started in the window.
    runs: int
    #: Those that recorded a card, and those whose card, or the run with none, went stale at least once.
    carded: int
    lapsed: int
    #: Every lapse of those runs, each counted once, from fresh to stale.
    lapses: int
    #: The runs that have ended, and those of them that ended with their card, or no card, stale.
    ended: int
    ended_stale: int

    def as_json(self) -> dict[str, object]:
        """Return the counts as one JSON object.

        Returns:
            `role`, `runs`, `carded`, `lapsed`, `lapses`, `ended`, and `ended_stale`.
        """
        return {
            "role": self.role,
            "runs": self.runs,
            "carded": self.carded,
            "lapsed": self.lapsed,
            "lapses": self.lapses,
            "ended": self.ended,
            "ended_stale": self.ended_stale,
        }


@dataclass(frozen=True)
class Lapses:
    """The lapses of the runs that started in a window, `[since, until)`, by role."""

    since: str
    until: str
    days: int
    #: Each role a run of the window had: the run kinds in their vocabulary's order, then `review`, then `task`.
    roles: Sequence[RoleLapses] = ()

    def as_json(self) -> dict[str, object]:
        """Return the counts as one JSON object.

        Returns:
            `since`, `until`, `days`, and `roles`, each as `RoleLapses.as_json` gives it.
        """
        return {
            "since": self.since,
            "until": self.until,
            "days": self.days,
            "roles": [r.as_json() for r in self.roles],
        }


def counts(conn: sqlite3.Connection, now: datetime, days: int) -> Lapses:
    """Count the lapses of the runs that started in the last `days` local days, today's so far included.

    The window is `canopy spend`'s and `canopy checklist`'s (`spend.window`), and a run is in it by when it started. A
    run still running counts the lapses found so far, and is not counted ended.

    Returns:
        A count per role a run of the window had.
    """
    start, end = spend.window(now, days)
    since, until = db.format_time(start), db.format_time(end)
    ran = _ran(conn, since, until)
    order = [str(k) for k in RunKind] + [REVIEW, TASK]
    roles = sorted({r.role for r in ran}, key=lambda role: (order.index(role) if role in order else len(order), role))
    found = tuple(_counted(role, [r for r in ran if r.role == role]) for role in roles)
    return Lapses(since=since, until=until, days=days, roles=found)


def lapses_of(ran: Ran) -> tuple[int, bool]:
    """How many times a run's card went stale, and whether it ended stale.

    Its row's count, and one more when it ended with its card stale and not yet counted so.

    Returns:
        The lapses, and whether the run has ended with its card, or no card, stale.
    """
    if ran.ended_at is None:
        return ran.card_lapses, False
    stale = cards.went_stale(ran.started_at, ran.card_at, ran.card_calls, ran.tool_calls, db.parse_time(ran.ended_at))
    return ran.card_lapses + (1 if stale and not ran.card_stale else 0), stale


@dataclass(frozen=True)
class Ran(records.View):
    """What a run's row says of its card's lapses, with its role."""

    role: str
    started_at: str
    ended_at: str | None
    tool_calls: int
    card_at: str | None
    card_calls: int | None
    card_lapses: int
    card_stale: bool


#: What `_ran` reads of each run after its role.
_COLUMNS = sql.frag("started_at, ended_at, tool_calls, card_at, card_calls, card_lapses, card_stale")
#: A run in the window, by when it started.
_WINDOW: LiteralString = "started_at >= ? AND started_at < ?"


def _ran(conn: sqlite3.Connection, since: str, until: str) -> list[Ran]:
    """Every run that started in `[since, until)`: a worker's or a planner's by its kind, a review's, and a task's.

    Returns:
        The runs.
    """
    tables: Iterable[tuple[Literal["review_runs", "task_runs"], str]] = (("review_runs", REVIEW), ("task_runs", TASK))
    each = [sql.select("kind AS role, {}", _COLUMNS).from_("runs").where(_WINDOW, since, until)]
    each += [
        sql.select("? AS role, {}", role, _COLUMNS).from_(table).where(_WINDOW, since, until) for table, role in tables
    ]
    return records.fetch_all(conn, Ran, sql.union(*each, every=True))


def _counted(role: str, ran: Sequence[Ran]) -> RoleLapses:
    """The counts of one role's runs.

    Returns:
        Its counts.
    """
    each = [lapses_of(r) for r in ran]
    return RoleLapses(
        role=role,
        runs=len(ran),
        carded=sum(r.card_at is not None for r in ran),
        lapsed=sum(lapses > 0 for lapses, _ in each),
        lapses=sum(lapses for lapses, _ in each),
        ended=sum(r.ended_at is not None for r in ran),
        ended_stale=sum(stale for _, stale in each),
    )
