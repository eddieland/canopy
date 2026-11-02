"""Feedback a unit's `review` cursor passed with no worker sent to it, and why (DESIGN §7).

The overseer names each feedback item its `ticket-set` moves the cursor past, with a reason (`loop.claims` checks the
names against what the connectors observed); the harness names one on a resolved thread. Recorded here once the move is,
so "seen, and chosen not to act on" is in the journal beside the cursor, not only in a decision's rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db, records

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable

    from canopy.core.vocab import Decider, PassReason


@dataclass(frozen=True)
class Passed:
    """A feedback item a `review` cursor passes with no worker sent to it: which, why, and on whose word."""

    item: records.ObservedReview
    reason: PassReason
    decider: Decider


def record(conn: sqlite3.Connection, tick_id: int, key: str, repo: str | None, passed: Iterable[Passed]) -> None:
    """Record each of `passed`, of ticket `key`'s unit in `repo`, as passed in tick `tick_id`.

    One passed before, after a forget moved its cursor back, takes its newest reason. Call inside the transaction that
    moves the cursor.
    """
    now = db.now()
    for p in passed:
        number = p.item.number
        if number is None:
            # The journal numbers every item it observes; one without could not have been named, nor passed.
            continue
        records.insert(
            records.PassedReview,
            pr_url=p.item.pr_url,
            item=p.item.item,
            id=p.item.id,
            number=number,
            ticket_key=key,
            repo=repo,
            tick_id=tick_id,
            reason=p.reason,
            decider=p.decider,
            passed_at=now,
        ).or_replace().run(conn)
