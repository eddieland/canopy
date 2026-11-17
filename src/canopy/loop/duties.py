"""What the overseer owes every tick, checked in code when it ends (DESIGN §6 step 5).

The prompt says how to do each duty; this checks only that each was done, from the decisions the overseer recorded.
A duty the overseer left undone fails the tick, as a missing done line does: the attention list stands, and the next
tick's state block still carries every ticket left out, so nothing omitted is lost or taken as resolved. What the check
cannot see is whether a decision was right: it holds the overseer to doing each duty, not to doing it well.

The tracker query is the harness's, never the overseer's: the tick records the `tracker` source's read of it, when one
was within `connect.max_age_minutes`, before the overseer runs (`record_queried`), and each ticket it found is owed a
decision. A tick of an older release recorded the overseer's `canopy queried` as the same decision, which
`last_queried` still reads.

A tick that runs the overseer once per subject (DESIGN §40) checks each run when it ends, against its subject's duty
alone (`of_subject`): a decision for its ticket, or a run or wait for each due chore from the chores' run.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from canopy.core import conversation, db, recorded_runs
from canopy.core.vocab import Decider

if TYPE_CHECKING:
    import sqlite3

    from canopy.core import chore_view, records

#: The decision the harness records for a query a source read, as `canopy queried` did before it: the tick ran the
#: tracker query, and which open tickets it returned. Its rationale is `queried_rationale`'s, which `queried_keys` reads
#: back.
QUERIED_ACTION = "queried"
_QUERIED_NONE = "the query returned no open ticket"
_QUERIED_SOME = "the query returned these open tickets: "
#: How many omitted tickets the failure names before it counts the rest.
_NAMED = 10
#: What a verb refused `decided` records, about the ticket it named: never a decision of that ticket's (§37, §40).
_REFUSED_DECIDED = "refused:decided"


@dataclass(frozen=True)
class Duties:
    """What a tick's state block asked of the overseer.

    `tickets` are the block's tickets, each owed a decision. The tickets the query found are owed one too, read
    when the tick ends, except the block's `stopped` and `recently_done`, and those the harness decided or dispatches
    this tick (DESIGN §37), which are owed nothing. `chores` are the block's chores due and not running, each owed
    `chore run` or `chore wait`; one with no `when` is the harness's, and not in the block. `harness` is the newest
    decision recorded before the overseer ran: those, and any the harness records after it, are never the overseer's.
    """

    tickets: frozenset[str]
    exempt: frozenset[str]
    chores: frozenset[str]
    harness: int
    #: Whether the tickets the query found are owed too: not by a run given one subject (DESIGN §40).
    queried: bool = True


def owed(
    conn: sqlite3.Connection,
    tick_id: int,
    *,
    tickets: Iterable[records.Ticket],
    stopped: Iterable[str],
    recently_done: Iterable[sqlite3.Row],
    decided: Iterable[str] = (),
    chores: Iterable[chore_view.ChoreSummary],
) -> Duties:
    """What the state block rendered from these asks of the overseer, read just before it runs.

    `decided` are the tickets the harness decided this tick or dispatches after the overseer, which the block names
    instead of listing (DESIGN §37).

    Returns:
        The tick's duties.
    """
    recorded = db.decisions_for_tick(conn, tick_id)
    return Duties(
        tickets=frozenset(t.key for t in tickets),
        exempt=frozenset([*stopped, *(str(t["key"]) for t in recently_done), *decided]),
        chores=frozenset(c["name"] for c in chores if c["due"] and not c["running"]),
        harness=max((d.id for d in recorded), default=0),
    )


def owed_tickets(conn: sqlite3.Connection, tick_id: int, duties: Duties) -> list[str]:
    """The tickets owed a decision in tick `tick_id`: the block's and the query's, but those exempt or stopped.

    Returns:
        Their keys, sorted.
    """
    found = {
        key
        for d in db.decisions_for_tick(conn, tick_id)
        if d.action == QUERIED_ACTION
        for key in queried_keys(d.rationale)
    }
    return sorted((duties.tickets | found) - duties.exempt - set(conversation.stopped(conn)))


def of_subject(duties: Duties, *, ticket: str | None = None, chores: bool = False) -> Duties:
    """What a run given one subject owes of the tick's `duties` (DESIGN §40): its `ticket`'s decision, or the chores'.

    A run given a PR owes no duty the harness checks, as a PR the overseer reviews is owed none today.

    Returns:
        The duties, cut to that subject.
    """
    return replace(
        duties,
        tickets=frozenset() if ticket is None else frozenset({ticket}),
        chores=duties.chores if chores else frozenset(),
        queried=False,
    )


def record_queried(conn: sqlite3.Connection, tick_id: int, repo: str, keys: Iterable[str]) -> int:
    """Record that tick `tick_id` ran the tracker query, touching each open ticket it returned into the journal.

    Into the journal at once, so the next tick's block carries each one even if this tick ends without deciding it.

    Returns:
        How many tickets it named, each once.
    """
    found = list(dict.fromkeys(keys))
    for key in found:
        db.touch_ticket(conn, key, repo)
    db.record_decision(conn, tick_id, None, QUERIED_ACTION, queried_rationale(found))
    return len(found)


def queried_rationale(keys: Sequence[str]) -> str:
    """The rationale of a `queried` decision naming `keys`, which `queried_keys` reads back.

    Returns:
        A sentence naming each key, in order, or saying there were none.
    """
    return f"{_QUERIED_SOME}{' '.join(keys)}" if keys else _QUERIED_NONE


def queried_keys(rationale: str) -> list[str]:
    """The ticket keys a `queried` decision's rationale names.

    Returns:
        The keys, in order; none for a rationale `queried_rationale` did not write.
    """
    return rationale.removeprefix(_QUERIED_SOME).split() if rationale.startswith(_QUERIED_SOME) else []


def last_queried(conn: sqlite3.Connection) -> set[str]:
    """The open tickets the newest `ok` tick that ran the tracker query found, whatever tick it was.

    Returns:
        Each key its `queried` decisions name; none before any tick has recorded one.
    """
    return {key for d in db.last_tick_decisions(conn, QUERIED_ACTION) for key in queried_keys(d.rationale)}


def undone(conn: sqlite3.Connection, tick_id: int, duties: Duties) -> list[str]:
    """Each duty the overseer left undone this tick, in the procedure's order.

    A ticket's decision is any the overseer recorded about it: a `decide`, a dispatch or review and their refusals, or
    an attention item; or a run it asked for that the tick has yet to start, whose decision is recorded as it starts
    (DESIGN §40), as a run given one subject is checked before the tick starts any. Each ticket the query found, in
    the `queried` the harness recorded, is owed one too. A ticket stopped while the overseer ran is owed nothing, as
    one stopped before it. A ticket that came into the journal any other way while it ran, such as one the operator
    started, is not owed one: the next tick's block carries it.

    Returns:
        One phrase per kind of duty left undone, empty when the overseer did every one.
    """
    # The harness's own, before the overseer ran or after (DESIGN §37), are never the overseer's.
    made = db.decisions_for_tick(conn, tick_id)
    # A refusal `decided` names a ticket the overseer was not given: no decision of its own.
    recorded = [
        d for d in made if d.id > duties.harness and d.decider is not Decider.HARNESS and d.action != _REFUSED_DECIDED
    ]
    missing: list[str] = []
    found = (
        {key for d in made if d.action == QUERIED_ACTION for key in queried_keys(d.rationale)}
        if duties.queried
        else set()
    )
    asked = recorded_runs.of_tick(conn, tick_id)
    decided = {d.ticket_key for d in [*recorded, *asked] if d.ticket_key is not None}
    exempt = duties.exempt | set(conversation.stopped(conn))
    tickets = sorted((duties.tickets | found) - exempt - decided)
    if tickets:
        named = ", ".join(tickets[:_NAMED]) + (f" and {len(tickets) - _NAMED} more" if len(tickets) > _NAMED else "")
        missing.append(f"no decision for {named}")
    chores = sorted(duties.chores - {d.chore for d in [*recorded, *asked] if d.chore is not None})
    if chores:
        missing.append(f"no run or wait for chore {', '.join(chores)}")
    return missing
