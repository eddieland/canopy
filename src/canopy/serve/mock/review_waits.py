"""GitHub's times on the mock journal's PRs (DESIGN §30), and the planner's estimates, for the Reviews page.

The reader began keeping a PR's times on Sep 15: each landed ticket's PR from then on was ready when its first worker
run ended and merged when the loop marked it done, so the reports page's figures are what its proxies gave before;
the PRs before then have none, and the Reviews page counts their reviews apart. PR 88, ABC-099's, was ready at 10:40
and asked alice for a review five minutes later; her first review came 27 minutes after that. The feedback plans the
operator approved on Sep 30 carry their planner's estimates: ABC-130's and ABC-131's small, ABC-132's medium.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import db, records
from canopy.core.vocab import PlanEffort, RunKind
from canopy.serve.mock import history
from canopy.serve.mock.reviews import PR_88

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

#: When the reader began keeping a PR's times: a PR read before it has none.
TIMES_FROM = datetime(2026, 9, 15, tzinfo=UTC)
# The planner's estimate of each approved feedback plan, by its ticket.
_EFFORTS = {"ABC-130": PlanEffort.SMALL, "ABC-131": PlanEffort.SMALL, "ABC-132": PlanEffort.MEDIUM}


def seed(conn: sqlite3.Connection, at: Callable[[int], str]) -> None:
    """Set the times of PR 88 and of each landed ticket's PR since `TIMES_FROM`, and the approved plans' estimates."""
    records.update(records.ObservedPr).set(created_at=at(-80), ready_at=at(-80), review_requested_at=at(-75)).where(
        "url = ?",
        PR_88,
    ).run(conn)
    for ticket in history.TICKETS:
        if ticket.closed or ticket.started < TIMES_FROM:
            continue
        first = next(r for r in ticket.runs if r.kind is RunKind.IMPLEMENT)
        ready = db.format_time(ticket.started + timedelta(hours=first.hours, minutes=first.minutes))
        done = db.format_time(ticket.done_at)
        records.update(records.ObservedPr).set(
            created_at=ready,
            ready_at=ready,
            merged_at=done,
            closed_at=done,
        ).where("url = ?", ticket.url).run(conn)
    for key, effort in _EFFORTS.items():
        records.update(records.FeedbackPlan).set(effort=effort).where("ticket_key = ?", key).run(conn)
