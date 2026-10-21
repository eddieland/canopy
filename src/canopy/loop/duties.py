"""What the overseer owes every tick, checked in code when it ends (DESIGN §6 step 5).

The prompt says how to do each duty; this checks only that each was done, from the decisions the overseer recorded.
A duty the overseer left undone fails the tick, as a missing done line does: the attention list stands, the query stays
due, and the next tick's state block still carries every ticket left out, so nothing omitted is lost or taken as
resolved. What the check cannot see is whether a decision was right, or whether the query was read to the end: it
holds the overseer to doing each duty, not to doing it well.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import conversation, db

if TYPE_CHECKING:
    import sqlite3

    from canopy.core import chore_view, records

# The decision `canopy queried` records: the tick ran the tracker query, and which open tickets it returned. Its
# rationale is `queried_rationale`'s, which `queried_keys` reads back.
QUERIED_ACTION = "queried"
_QUERIED_NONE = "the query returned no open ticket"
_QUERIED_SOME = "the query returned these open tickets: "
# How many omitted tickets the failure names before it counts the rest.
_NAMED = 10
# The reasons a skip with no key gives, its rationale's first word: the overseer could not see the world this tick.
TICK_WIDE_SKIPS = ("mcp_unavailable", "tracker_unsupported")


@dataclass(frozen=True)
class Duties:
    """What a tick's state block asked of the overseer.

    `tickets` are the block's tickets, each owed a decision. The tickets `canopy queried` names are owed one too, read
    when the tick ends, except the block's `stopped` and `recently_done`, which are owed nothing. `chores` are the
    chores due and not running, each owed `chore run` or `chore wait`. `harness` is the newest decision recorded before
    the overseer ran: those are the harness's, and never count as the overseer's.
    """

    query_due: bool
    tickets: frozenset[str]
    exempt: frozenset[str]
    chores: frozenset[str]
    harness: int


def owed(
    conn: sqlite3.Connection,
    tick_id: int,
    *,
    query_due: bool,
    tickets: Iterable[records.Ticket],
    stopped: Iterable[str],
    recently_done: Iterable[sqlite3.Row],
    chores: Iterable[chore_view.ChoreSummary],
) -> Duties:
    """What the state block rendered from these asks of the overseer, read just before it runs.

    Returns:
        The tick's duties.
    """
    recorded = db.decisions_for_tick(conn, tick_id)
    return Duties(
        query_due=query_due,
        tickets=frozenset(t.key for t in tickets),
        exempt=frozenset([*stopped, *(str(t["key"]) for t in recently_done)]),
        chores=frozenset(c["name"] for c in chores if c["due"] and not c["running"]),
        harness=max((d.id for d in recorded), default=0),
    )


def tick_wide(rationale: str) -> bool:
    """Whether a skip's rationale gives a tick-wide reason, as `mcp_unavailable: <which>` does.

    Returns:
        True when the rationale's text before its first colon is one of `TICK_WIDE_SKIPS`.
    """
    return rationale.split(":", 1)[0].strip() in TICK_WIDE_SKIPS


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
    an attention item. A mirror is not one: it copies a comment and decides nothing. A ticket stopped while the
    overseer ran is owed nothing, as one stopped before it. A ticket that came into the journal any other way while it
    ran, such as one the operator started, is not owed one: the next tick's block carries it.

    Returns:
        One phrase per kind of duty left undone, empty when the overseer did every one.
    """
    recorded = [d for d in db.decisions_for_tick(conn, tick_id) if d.id > duties.harness]
    queried = [d for d in recorded if d.action == QUERIED_ACTION]
    missing: list[str] = []
    if duties.query_due and not queried:
        missing.append("the tracker query was due and no `canopy queried` recorded it")
    found = {key for d in queried for key in queried_keys(d.rationale)}
    decided = {d.ticket_key for d in recorded if d.ticket_key is not None and d.action != conversation.MIRROR_ACTION}
    exempt = duties.exempt | set(conversation.stopped(conn))
    tickets = sorted((duties.tickets | found) - exempt - decided)
    if tickets:
        named = ", ".join(tickets[:_NAMED]) + (f" and {len(tickets) - _NAMED} more" if len(tickets) > _NAMED else "")
        missing.append(f"no decision for {named}")
    chores = sorted(duties.chores - {d.chore for d in recorded if d.chore is not None})
    if chores:
        missing.append(f"no run or wait for chore {', '.join(chores)}")
    return missing
