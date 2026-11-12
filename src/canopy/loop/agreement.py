"""How the derivation agreed with the overseer over a window, per row of §7's table (DESIGN §30, §37; ROADMAP M38).

A row of the phase table moves into the harness only on a measurement showing the derivation right on it: a day of the
loop in shadow, each disagreement read and attributed (§37, SCENARIOS S68). Each tick already records what it derived
and the phase the overseer left each subject at, and `phases.compare` reads one tick's agreement from them; this reads
every tick of a window so, per row, and lists each disagreement with the overseer's own rationale beside it, so the
operator can say which side was right. The operator's review requests are one more row, `review_request`, compared by
`requested_reviews.compare` from what each tick derived for them (§21), each counted as a ticket is, by its PR's URL.
It also counts what the connectors cost, in runs and seconds, which S68 records beside the agreement.

Only live ticks that closed `ok` and ran their overseer are read: a failed run's decisions may stop partway, a dry run
moves no phase, and a tick that ran no overseer left it nothing to compare. A ticket counts under every row that held
for it or one of its units; one with no row is counted under `closed` when the tracker said it was closed, else under
`none`. A situation is a ticket under a row: the same PR decided again each tick is one situation, however many ticks
decided it (MEASUREMENTS 2026-10-15 F26), so the count is a floor. A disagreement is grouped by its ticket and the
comparison's words, with the ticks it held across and the overseer's latest rationale.

Two things make a row's count read for what the harness would take. A ticket under several rows counts against each,
whichever the disagreement was about, so each row is counted again over the tickets it alone held for, the only ones
the harness takes whole (§37). And a disagreement about the phase alone, the overseer's decision one the rows that held
allow, is counted apart from one about what it did (`phases.Mismatch`).
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
from canopy.loop import phases, requested_reviews

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

#: The row each of the operator's open review requests counts under (DESIGN §21, §37).
REQUEST = "review_request"
#: The row a ticket with no row held counts under: `closed` when the tracker said it was closed, else `none`.
CLOSED = "closed"
NONE = "none"
#: The rows in the order the report lists them: the vocabulary's, then the three above.
ROW_ORDER: Sequence[str] = (*(str(p) for p in Phase), REQUEST, CLOSED, NONE)


@dataclass(frozen=True)
class RowCounts:
    """How one row's tickets compared with the overseer over the window."""

    row: str
    #: Each ticket in each tick the row held for, compared: its decisions.
    decisions: int
    agrees: int
    disagrees: int
    #: Of `disagrees`, those about the phase alone: the overseer's decision was one the rows that held allow.
    phase_only: int
    #: The distinct tickets the row held for, and those of them that disagreed in some tick.
    situations: int
    disagreeing: int
    #: Of `disagreeing`, those whose every disagreement was about the phase alone.
    disagreeing_phase_only: int


@dataclass(frozen=True)
class Disagreement:
    """One subject's disagreement, grouped across the ticks it held in by the comparison's words."""

    #: The ticket, or for a review request, its PR's URL.
    ticket_key: str
    #: The rows that held for it in its latest tick.
    rows: Sequence[str]
    #: The comparison's words: what the overseer set or decided, and what the rows allowed.
    why: str
    #: What it is about: the phase alone, the decision, or both.
    mismatch: phases.Mismatch
    ticks: int
    first_tick: int
    last_tick: int
    #: The overseer's rationale for its decisions on the subject in the latest tick; empty when it recorded none.
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
    #: Each ticket and review request in each tick compared.
    decisions: int
    #: Each ticket or request in each tick with a stale subject, counted apart, never as a disagreement.
    stale: int
    #: The distinct tickets among them.
    stale_tickets: int
    #: The distinct review requests among them, by their PRs' URLs.
    stale_requests: int
    #: Per row, in `ROW_ORDER`, those that held at least once.
    rows: Sequence[RowCounts] = ()
    #: The same, over the tickets each row alone held for: no other row held for the ticket or one of its units.
    alone: Sequence[RowCounts] = ()
    #: Newest first.
    disagreements: Sequence[Disagreement] = ()
    sources: Sequence[SourceCost] = field(default_factory=tuple)

    def as_json(self) -> dict[str, object]:
        """Return the agreement as one JSON object.

        Returns:
            `since`, `until`, `days`, `ticks`, `decisions`, `stale`, `stale_tickets`, `stale_requests`, then `rows`,
            `alone`, `disagreements`, and `sources`, each a list of objects with its dataclass's fields.
        """
        return {
            "since": self.since,
            "until": self.until,
            "days": self.days,
            "ticks": self.ticks,
            "decisions": self.decisions,
            "stale": self.stale,
            "stale_tickets": self.stale_tickets,
            "stale_requests": self.stale_requests,
            "rows": [vars(r) for r in self.rows],
            "alone": [vars(r) for r in self.alone],
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
        stale_requests=len(tally.stale_requests),
        rows=tally.every.rows(),
        alone=tally.alone.rows(),
        disagreements=tally.grouped(),
        sources=_sources(conn, since, until),
    )


@dataclass
class _Counts:
    """The subjects compared under each row, as they are read."""

    verdicts: Counter[tuple[str, phases.Verdict]] = field(default_factory=Counter[tuple[str, phases.Verdict]])
    phase_only: Counter[str] = field(default_factory=Counter[str])
    situations: dict[str, set[str]] = field(default_factory=dict[str, set[str]])
    disagreeing: dict[str, set[str]] = field(default_factory=dict[str, set[str]])
    # Of the disagreeing, those with a disagreement about what the overseer did, not its phase alone.
    acted: dict[str, set[str]] = field(default_factory=dict[str, set[str]])

    def add(self, key: str, rows: Sequence[str], compared: phases.Compared) -> None:
        """Count subject `key`'s comparison under each of `rows`."""
        for row in rows:
            self.verdicts[row, compared.verdict] += 1
            self.situations.setdefault(row, set()).add(key)
            if compared.mismatch is None:
                continue
            self.disagreeing.setdefault(row, set()).add(key)
            if compared.mismatch == "phase":
                self.phase_only[row] += 1
            else:
                self.acted.setdefault(row, set()).add(key)

    def rows(self) -> list[RowCounts]:
        """Return the counts of each row that held, in `ROW_ORDER`."""
        return [
            RowCounts(
                row=row,
                decisions=self.verdicts[row, "agrees"] + self.verdicts[row, "disagrees"],
                agrees=self.verdicts[row, "agrees"],
                disagrees=self.verdicts[row, "disagrees"],
                phase_only=self.phase_only[row],
                situations=len(self.situations[row]),
                disagreeing=len(self.disagreeing.get(row, ())),
                disagreeing_phase_only=len(self.disagreeing.get(row, set()) - self.acted.get(row, set())),
            )
            for row in ROW_ORDER
            if row in self.situations
        ]


@dataclass
class _Tally:
    """The window's comparisons as they are read, tick by tick, oldest first."""

    decisions: int = 0
    stale: int = 0
    stale_tickets: set[str] = field(default_factory=set[str])
    stale_requests: set[str] = field(default_factory=set[str])
    #: Each subject under every row that held for it, and under its row when that was its only one.
    every: _Counts = field(default_factory=_Counts)
    alone: _Counts = field(default_factory=_Counts)
    # By ticket and the comparison's words: the rows, the ticks, the rationale, and what it is about, each the latest
    # tick's.
    found: dict[tuple[str, str], tuple[Sequence[str], list[int], str, phases.Mismatch]] = field(
        default_factory=dict[tuple[str, str], tuple[Sequence[str], list[int], str, phases.Mismatch]],
    )

    def read(self, conn: sqlite3.Connection, tick_id: int) -> None:
        """Add tick `tick_id`'s comparisons: its tickets', then its review requests'."""
        held = _rows_held(conn, tick_id)
        rationale = _rationales(conn, tick_id)
        for compared in phases.compare(conn, tick_id):
            key = compared.ticket_key
            self.add(tick_id, key, held.get(key, (NONE,)), compared, rationale=rationale.get(key, ""))
        for asked in requested_reviews.compare(conn, tick_id):
            # A request has no phase the overseer sets: a disagreement on one is about what it did.
            mismatch: phases.Mismatch | None = "action" if asked.verdict == "disagrees" else None
            compared = phases.Compared(asked.pr_url, asked.verdict, asked.why, mismatch)
            self.add(tick_id, asked.pr_url, (REQUEST,), compared, rationale=rationale.get(asked.pr_url, ""))

    def add(
        self,
        tick_id: int,
        key: str,
        rows: Sequence[str],
        compared: phases.Compared,
        *,
        rationale: str,
    ) -> None:
        """Add one subject's comparison in tick `tick_id`: a ticket's, or a request's, keyed by its PR's URL."""
        self.decisions += 1
        if compared.verdict == "stale":
            self.stale += 1
            (self.stale_requests if REQUEST in rows else self.stale_tickets).add(key)
            return
        self.every.add(key, rows, compared)
        if len(rows) == 1:
            self.alone.add(key, rows, compared)
        if compared.mismatch is not None:
            said = compared.why or ""
            _, seen, _, _ = self.found.get((key, said), ((), [], "", compared.mismatch))
            self.found[key, said] = (rows, [*seen, tick_id], rationale, compared.mismatch)

    def grouped(self) -> list[Disagreement]:
        """Return each disagreement, the one held in the newest tick first."""
        found = [
            Disagreement(
                ticket_key=key,
                rows=rows,
                why=why,
                mismatch=mismatch,
                ticks=len(seen),
                first_tick=seen[0],
                last_tick=seen[-1],
                rationale=rationale,
            )
            for (key, why), (rows, seen, rationale, mismatch) in self.found.items()
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
    """The rationale of each ticket's decisions in tick `tick_id` that are not the harness's, joined, and each PR's.

    A decision about a PR is the PR's, and its ticket's too when it names one: a review the operator asked for of a
    ticket's own PR is compared by the PR (`requested_reviews.compare`).

    Returns:
        By ticket, and by the PR's URL, its rationales in the order recorded, each once.
    """
    found: dict[str, list[str]] = {}
    for d in db.decisions_for_tick(conn, tick_id):
        if d.decider is Decider.HARNESS or not d.rationale:
            continue
        for subject in (d.ticket_key, d.pr):
            if subject is None:
                continue
            said = found.setdefault(subject, [])
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
