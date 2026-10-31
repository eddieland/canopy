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
    first: dict[str, tuple[str, str]] = {}
    last: dict[str, str] = {}
    seen: set[str] = set()
    pushed = (
        sql.select("ticket_key, started_at, result_json")
        .from_("runs")
        .where("started_at < ? AND result_json IS NOT NULL", until)
        .order_by("started_at, id")
    )
    for key, started, result in sql.execute(conn, pushed):
        for url in contract.stored_prs(contract.stored_object(result)):
            first.setdefault(url, (str(key), str(started)))
            last[url] = str(started)
            if str(started) >= since:
                seen.add(url)
    urls = [url for url in first if url in seen]
    units = (
        records.select(records.TicketUnit)
        .where("pr_url IN (SELECT value FROM json_each(?))", json.dumps(urls))
        .all(conn)
    )
    owned = {u.pr_url: u for u in units if u.pr_url is not None}
    return {
        url: TrackedPr(
            url=url,
            first_named=first[url][1],
            last_named=last[url],
            ticket=owned[url].ticket_key if url in owned else first[url][0],
            phase=owned[url].phase if url in owned else None,
        )
        for url in urls
    }
