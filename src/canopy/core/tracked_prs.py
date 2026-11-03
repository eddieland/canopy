"""The PRs canopy tracked in a window (DESIGN §11): each PR a run's result named, and the ticket that owns it.

Reads only. The journal keeps no PR's creation time, so a PR shows from the start of the first run whose result named
it, which is when it first shows in the journal. The reports read this: the monthly report counts the PRs each month
first showed, and the CI page names the ticket and the phase of each PR it lists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import contract, records, sql

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

    from canopy.core.vocab import Phase


@dataclass(frozen=True)
class TrackedPr:
    """A PR a run's result named, as the reports list it."""

    url: str
    #: When the first run whose result named it started, a journal time: the window's run or one before it.
    first_named: str
    #: When the last run before the window's end whose result named it started, a journal time.
    last_named: str
    #: The ticket that owns it: its unit's, else the ticket of the first run that named it.
    ticket: str
    #: Its unit's phase (DESIGN §7); None for a PR no unit holds, or one whose unit has no phase yet.
    phase: Phase | None


def tracked(conn: sqlite3.Connection, since: str, until: str) -> dict[str, TrackedPr]:
    """The PRs a run that started in `[since, until)`, each a journal time, named in its result.

    Each is dated by the first run that ever named it, which may have started before `since`, so a PR a window's run
    pushed to again is in it, though it first showed earlier.

    Returns:
        Each PR by URL, the first named first.
    """
    return read(conn, until).tracked(since, until)


@dataclass(frozen=True)
class Naming:
    """A run whose result named PRs."""

    ticket: str
    #: When it started, a journal time.
    started_at: str
    #: The PRs its result named, by URL.
    prs: Sequence[str]


@dataclass(frozen=True)
class Namings:
    """Every run that started before a time and named PRs, read once, for the PRs any window ending by then tracked.

    A report of many windows reads this once rather than every run's result for each window.
    """

    #: The time it was read to, a journal time: no window it answers for ends after it.
    until: str
    #: The runs, the earliest started first.
    runs: Sequence[Naming]
    #: The unit that holds each PR the runs named, by URL.
    units: Mapping[str, records.TicketUnit]

    def tracked(self, since: str, until: str) -> dict[str, TrackedPr]:
        """The PRs a run that started in `[since, until)` named, as the module's `tracked` gives them.

        Returns:
            Each PR by URL, the first named first.

        Raises:
            ValueError: When `until` is after the time it was read to.
        """
        if until > self.until:
            msg = f"read to {self.until}, asked to {until}"
            raise ValueError(msg)
        first: dict[str, tuple[str, str]] = {}
        last: dict[str, str] = {}
        seen: set[str] = set()
        for run in self.runs:
            if run.started_at >= until:
                break
            for url in run.prs:
                first.setdefault(url, (run.ticket, run.started_at))
                last[url] = run.started_at
                if run.started_at >= since:
                    seen.add(url)
        return {
            url: TrackedPr(
                url=url,
                first_named=started,
                last_named=last[url],
                ticket=unit.ticket_key if (unit := self.units.get(url)) is not None else key,
                phase=None if unit is None else unit.phase,
            )
            for url, (key, started) in first.items()
            if url in seen
        }


def read(conn: sqlite3.Connection, until: str) -> Namings:
    """Every run that started before `until`, a journal time, and named PRs in its result, and the units holding them.

    Returns:
        Them, to ask `tracked` of for any window that ends by `until`.
    """
    runs: list[Naming] = []
    pushed = (
        sql.select("ticket_key, started_at, result_json")
        .from_("runs")
        .where("started_at < ? AND result_json IS NOT NULL", until)
        .order_by("started_at, id")
    )
    for key, started, result in sql.execute(conn, pushed):
        named = tuple(contract.stored_prs(contract.stored_object(result)))
        if named:
            runs.append(Naming(ticket=str(key), started_at=str(started), prs=named))
    urls = sorted({url for run in runs for url in run.prs})
    units = (
        records.select(records.TicketUnit)
        .where("pr_url IN (SELECT value FROM json_each(?))", json.dumps(urls))
        .all(conn)
    )
    return Namings(until=until, runs=runs, units={u.pr_url: u for u in units if u.pr_url is not None})
