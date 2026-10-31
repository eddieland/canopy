"""How the derivation agreed with the overseer over a window, per row of §7's table (DESIGN §30, §37; ROADMAP M38).

A row of the phase table moves into the harness only on a measurement showing the derivation right on it: a day of the
loop in shadow, each disagreement read and attributed (§37, SCENARIOS S68). Each tick already records what it derived
and the phase the overseer left each subject at, and `phases.compare` reads one tick's agreement from them; this reads
every tick of a window so, per row, and lists each disagreement with the overseer's own rationale beside it, so the
operator can say which side was right. It also counts what the connectors cost, in runs and seconds, which S68 records
beside the agreement.

Only live ticks that closed `ok` and ran their overseer are read: a failed run's decisions may stop partway, a dry run
moves no phase, and a tick that ran no overseer left it nothing to compare. A ticket counts under every row that held
for it or one of its units; one with no row is counted under `closed` when the tracker said it was closed, else under
`none`. A situation is a ticket under a row: the same PR decided again each tick is one situation, however many ticks
decided it (MEASUREMENTS 2026-10-15 F26), so the count is a floor. A disagreement is grouped by its ticket and the
comparison's words, with the ticks it held across and the overseer's latest rationale.
"""

from __future__ import annotations

import itertools
import json
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from canopy.core import db, records, spend, sql
from canopy.core.vocab import ConnectorRunStatus, Decider, Phase, TickStatus
from canopy.loop import phases

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

#: The row a ticket with no row held counts under: `closed` when the tracker said it was closed, else `none`.
CLOSED = "closed"
NONE = "none"
#: The rows in the order the report lists them: the vocabulary's, then the two above.
ROW_ORDER: Sequence[str] = (*(str(p) for p in Phase), CLOSED, NONE)


@dataclass(frozen=True)
class RowCounts:
    """How one row's tickets compared with the overseer over the window."""

    row: str
    #: Each ticket in each tick the row held for, compared: its decisions.
    decisions: int
    agrees: int
    disagrees: int
    #: The distinct tickets the row held for, and those of them that disagreed in some tick.
    situations: int
    disagreeing: int


@dataclass(frozen=True)
class Disagreement:
    """One ticket's disagreement, grouped across the ticks it held in by the comparison's words."""

    ticket_key: str
    #: The rows that held for it in its latest tick.
    rows: Sequence[str]
    #: The comparison's words: what the overseer set or decided, and what the rows allowed.
    why: str
    ticks: int
    first_tick: int
    last_tick: int
    #: The overseer's rationale for its decisions on the ticket in the latest tick; empty when it recorded none.
    rationale: str


@dataclass(frozen=True)
class SourceCost:
    """What one connector source cost over the window."""

    source: str
    kind: str
    #: Its runs in the window's ticks, and in the loop's polls between them (DESIGN §6).
    tick_runs: int
    poll_runs: int
    failed: int
    #: The median run's seconds, and the seconds its runs took per tick of the window that ran it; None with no run.
    median_seconds: float | None
    seconds_per_tick: float | None


@dataclass(frozen=True)
class Agreement:
    """The derivation against the overseer over a window, `[since, until)`."""

    since: str
    until: str
    days: int
    #: The ticks compared: live, closed `ok`, and with their overseer run.
    ticks: int
    #: Each ticket in each tick compared.
    decisions: int
    #: Each ticket in each tick with a stale subject, counted apart, never as a disagreement; and the distinct tickets.
    stale: int
    stale_tickets: int
    #: Per row, in `ROW_ORDER`, those that held at least once.
    rows: Sequence[RowCounts] = ()
    #: Newest first.
    disagreements: Sequence[Disagreement] = ()
    sources: Sequence[SourceCost] = field(default_factory=tuple)

    def as_json(self) -> dict[str, object]:
        """Return the agreement as one JSON object.

        Returns:
            `since`, `until`, `days`, `ticks`, `decisions`, `stale`, `stale_tickets`, then `rows`, `disagreements`,
            and `sources`, each a list of objects with its dataclass's fields.
        """
        return {
            "since": self.since,
            "until": self.until,
            "days": self.days,
            "ticks": self.ticks,
            "decisions": self.decisions,
            "stale": self.stale,
            "stale_tickets": self.stale_tickets,
            "rows": [vars(r) for r in self.rows],
            "disagreements": [{**vars(d), "rows": list(d.rows)} for d in self.disagreements],
            "sources": [vars(s) for s in self.sources],
        }


def agreement(conn: sqlite3.Connection, now: datetime, days: int) -> Agreement:
    """Read how the derivation agreed with the overseer in the ticks that started in the last `days` local days.

    The window is `canopy spend`'s (`spend.window`), and a tick is in it by when it started.

    Returns:
        The counts per row, each disagreement grouped, and each source's cost.
    """
    start, end = spend.window(now, days)
    since, until = db.format_time(start), db.format_time(end)
    ticks = (
        records.select(records.Tick)
        .where(
            "started_at >= ? AND started_at < ? AND status = ? AND NOT dry_run AND overseer_ran",
            since,
            until,
            TickStatus.OK,
        )
        .order_by("id")
        .all(conn)
    )
    tally = _Tally()
    for tick in ticks:
        tally.read(conn, tick.id)
    return Agreement(
        since=since,
        until=until,
        days=days,
        ticks=len(ticks),
        decisions=tally.decisions,
        stale=tally.stale,
        stale_tickets=len(tally.stale_tickets),
        rows=tally.rows(),
        disagreements=tally.grouped(),
        sources=_sources(conn, since, until),
    )


@dataclass
class _Tally:
    """The window's comparisons as they are read, tick by tick, oldest first."""

    decisions: int = 0
    stale: int = 0
    stale_tickets: set[str] = field(default_factory=set[str])
    verdicts: Counter[tuple[str, phases.Verdict]] = field(default_factory=Counter[tuple[str, phases.Verdict]])
    situations: dict[str, set[str]] = field(default_factory=dict[str, set[str]])
    disagreeing: dict[str, set[str]] = field(default_factory=dict[str, set[str]])
    # By ticket and the comparison's words: the rows, the ticks, and the rationale, each the latest tick's.
    found: dict[tuple[str, str], tuple[Sequence[str], list[int], str]] = field(
        default_factory=dict[tuple[str, str], tuple[Sequence[str], list[int], str]],
    )

    def read(self, conn: sqlite3.Connection, tick_id: int) -> None:
        """Add tick `tick_id`'s comparisons."""
        held = _rows_held(conn, tick_id)
        rationale = _rationales(conn, tick_id)
        for compared in phases.compare(conn, tick_id):
            key = compared.ticket_key
            self.decisions += 1
            if compared.verdict == "stale":
                self.stale += 1
                self.stale_tickets.add(key)
                continue
            rows = held.get(key, (NONE,))
            for row in rows:
                self.verdicts[row, compared.verdict] += 1
                self.situations.setdefault(row, set()).add(key)
                if compared.verdict == "disagrees":
                    self.disagreeing.setdefault(row, set()).add(key)
            if compared.verdict == "disagrees":
                why = compared.why or ""
                _, seen, _ = self.found.get((key, why), ((), [], ""))
                self.found[key, why] = (rows, [*seen, tick_id], rationale.get(key, ""))

    def rows(self) -> list[RowCounts]:
        """Return the counts of each row that held, in `ROW_ORDER`."""
        return [
            RowCounts(
                row=row,
                decisions=self.verdicts[row, "agrees"] + self.verdicts[row, "disagrees"],
                agrees=self.verdicts[row, "agrees"],
                disagrees=self.verdicts[row, "disagrees"],
                situations=len(self.situations[row]),
                disagreeing=len(self.disagreeing.get(row, ())),
            )
            for row in ROW_ORDER
            if row in self.situations
        ]

    def grouped(self) -> list[Disagreement]:
        """Return each disagreement, the one held in the newest tick first."""
        found = [
            Disagreement(
                ticket_key=key,
                rows=rows,
                why=why,
                ticks=len(seen),
                first_tick=seen[0],
                last_tick=seen[-1],
                rationale=rationale,
            )
            for (key, why), (rows, seen, rationale) in self.found.items()
        ]
        return sorted(found, key=lambda d: (-d.last_tick, d.ticket_key, d.why))


def _rows_held(conn: sqlite3.Connection, tick_id: int) -> dict[str, tuple[str, ...]]:
    """Each ticket's rows in tick `tick_id`: every phase that held for it or a unit, in the vocabulary's order.

    Returns:
        By ticket, its rows, or `closed` or `none` when none held.
    """
    held: dict[str, set[str]] = {}
    closed: set[str] = set()
    for row in records.select(records.Derivation).where("tick_id = ?", tick_id).all(conn):
        held.setdefault(row.ticket_key, set()).update(json.loads(row.phases))
        if row.closed:
            closed.add(row.ticket_key)
    return {
        key: tuple(r for r in ROW_ORDER if r in found) or ((CLOSED,) if key in closed else (NONE,))
        for key, found in held.items()
    }


def _rationales(conn: sqlite3.Connection, tick_id: int) -> dict[str, str]:
    """The rationale of each ticket's decisions in tick `tick_id` that are not the harness's, joined.

    Returns:
        By ticket, its rationales in the order recorded, each once.
    """
    found: dict[str, list[str]] = {}
    for d in db.decisions_for_tick(conn, tick_id):
        if d.ticket_key is None or d.decider is Decider.HARNESS or not d.rationale:
            continue
        said = found.setdefault(d.ticket_key, [])
        if d.rationale not in said:
            said.append(d.rationale)
    return {key: "; ".join(said) for key, said in found.items()}


@dataclass(frozen=True)
class _Run(records.View):
    """A connector run's source, kind, tick, status, and how long it took."""

    source: str
    kind: str
    tick_id: int | None
    status: ConnectorRunStatus
    seconds: float


def _sources(conn: sqlite3.Connection, since: str, until: str) -> list[SourceCost]:
    """What each source cost in the runs that started in `[since, until)`, a tick's and a poll's.

    Returns:
        One per source, by name.
    """
    query = (
        sql.select(
            "source, kind, tick_id, status, (julianday(ended_at) - julianday(started_at)) * 86400.0 AS seconds",
        )
        .from_("connector_runs")
        .where("started_at >= ? AND started_at < ?", since, until)
        .order_by("source, id")
    )
    by_source: dict[str, list[_Run]] = {}
    for run in records.fetch_all(conn, _Run, query):
        by_source.setdefault(run.source, []).append(run)
    return list(itertools.starmap(_cost, by_source.items()))


def _cost(source: str, runs: Sequence[_Run]) -> SourceCost:
    in_ticks = [r for r in runs if r.tick_id is not None]
    totals: dict[int, float] = {}
    for r in in_ticks:
        if r.tick_id is not None:
            totals[r.tick_id] = totals.get(r.tick_id, 0.0) + r.seconds
    return SourceCost(
        source=source,
        kind=runs[-1].kind,
        tick_runs=len(in_ticks),
        poll_runs=len(runs) - len(in_ticks),
        failed=sum(r.status is not ConnectorRunStatus.OK for r in runs),
        median_seconds=round(statistics.median(r.seconds for r in runs), 1) if runs else None,
        seconds_per_tick=round(sum(totals.values()) / len(totals), 1) if totals else None,
    )
