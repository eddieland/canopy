"""A queue label added after a `not authorized:` failure: the operator's "try again" (DESIGN §14).

A worker that finds its ticket closed, or carrying no queue label, changes nothing and reports `failed` with a summary
that starts `not authorized:` (D051). A failed run holds its ticket until a human says to try again; for this failure
the operator says it by adding the label. So the hold lifts once the `tracker` source observes a queue label on the open
ticket that it says was added after the run ended: the run's `worker_failed` item goes that tick, and the overseer's
state block carries the label's add time on the run, so it decides from the phase again. A label whose add time the
source does not report lifts nothing, nor does one added before the run ended.

The summary is the worker's, so a worker could claim this failure falsely. All that would buy it is the hold lifting
once someone adds a queue label after it ended, which authorizes runs on the ticket anyway.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from canopy.core import contract, records
from canopy.core.vocab import RunStatus, TicketState

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from collections.abc import Set as AbstractSet

#: How a worker's summary starts when its ticket was closed or carried no queue label (`prompts.plan_authorization`).
NOT_AUTHORIZED: Final = "not authorized:"


def lifted(conn: sqlite3.Connection, labels: AbstractSet[str], runs: Mapping[str, records.Run]) -> dict[str, str]:
    """The tickets whose latest run, in `runs` by key, a queue label in `labels` added since has lifted the hold of.

    Returns:
        Each such ticket's key, with when the newest such label was added, as the journal writes a time.
    """
    refused = {key: run for key, run in runs.items() if _not_authorized(run)}
    if not refused:
        return {}
    found: dict[str, str] = {}
    for ticket in records.select(records.ObservedTicket).where_in("key", sorted(refused)).all(conn):
        added = _added_since(ticket, labels, str(refused[ticket.key].ended_at))
        if added is not None:
            found[ticket.key] = added
    return found


def _not_authorized(run: records.Run) -> bool:
    if run.status is not RunStatus.FAILED or run.ended_at is None:
        return False
    summary = contract.stored_object(run.result_json).get("summary")
    return isinstance(summary, str) and summary.lstrip().lower().startswith(NOT_AUTHORIZED)


def _added_since(ticket: records.ObservedTicket, labels: AbstractSet[str], ended: str) -> str | None:
    """When the newest queue label on an open observed ticket was added after `ended`.

    Both times are as the journal writes one (`observe` stores a label's so), so they compare as text.

    Returns:
        The time, or None when the ticket is closed or no such label's add time is after `ended`.
    """
    if ticket.state is TicketState.CLOSED:
        return None
    found: object = json.loads(ticket.labels)
    times = [
        added
        for label in (found if isinstance(found, list) else [])
        if isinstance(label, dict)
        and label.get("name") in labels
        and isinstance(added := label.get("added_at"), str)
        and added > ended
    ]
    return max(times, default=None)
