"""What the overseer owes every tick, checked in code when it ends (DESIGN §6 step 5).

The prompt says how to do each duty; this checks only that each was done, from the decisions the overseer recorded.
A duty the overseer left undone fails the tick, as a missing done line does: the attention list stands, the query stays
due, and the next tick's state block still carries every ticket left out, so nothing omitted is lost or taken as
resolved. What the check cannot see is whether a decision was right, or whether the query was read to the end: it
holds the overseer to doing each duty, not to doing it well.

The query is the one duty the harness does itself, when a source read it within `connect.max_age_minutes`: the tick
records its result before the overseer runs (`record_queried`), so the overseer owes no `canopy queried`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import conversation, db
from canopy.core.vocab import Decider

if TYPE_CHECKING:
    import sqlite3

    from canopy.core import chore_view, records

# The decision `canopy queried` records, or the harness for a query a source read: the tick ran the tracker query, and
# which open tickets it returned. Its rationale is `queried_rationale`'s, which `queried_keys` reads back.
QUERIED_ACTION = "queried"
_QUERIED_NONE = "the query returned no open ticket"
_QUERIED_SOME = "the query returned these open tickets: "
# How many omitted tickets the failure names before it counts the rest.
_NAMED = 10
# The reasons a skip with no key gives, its rationale's first word: the overseer could not see the world this tick.
# Where a `tracker` source reads the tracker, the overseer reads none, so it has no `tracker_unsupported` to give;
# where the `vcs` source reads GitHub beside it, it has no server to give `mcp_unavailable` for either (DESIGN §39,
# `canopy.loop.tools`).
MCP_UNAVAILABLE = "mcp_unavailable"
TRACKER_UNSUPPORTED = "tracker_unsupported"
TICK_WIDE_SKIPS = (MCP_UNAVAILABLE, TRACKER_UNSUPPORTED)


@dataclass(frozen=True)
class Duties:
    """What a tick's state block asked of the overseer.

    `tickets` are the block's tickets, each owed a decision. The tickets `canopy queried` names are owed one too, read
    when the tick ends, except the block's `stopped` and `recently_done`, and those the harness decided or dispatches
    this tick (DESIGN §37), which are owed nothing. `chores` are the block's chores due and not running, each owed
    `chore run` or `chore wait`; one with no `when` is the harness's, and not in the block. `harness` is the newest
    decision recorded before the overseer ran: those, and any the harness records after it, are never the overseer's,
    but a `queried` the harness recorded stands for the query as the overseer's would.
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
        query_due=query_due,
        tickets=frozenset(t.key for t in tickets),
        exempt=frozenset([*stopped, *(str(t["key"]) for t in recently_done), *decided]),
        chores=frozenset(c["name"] for c in chores if c["due"] and not c["running"]),
        harness=max((d.id for d in recorded), default=0),
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
    an attention item. The query is done by a `queried` the overseer recorded or the harness did, and each ticket
    either names is owed a decision. A ticket stopped while the overseer ran is owed nothing, as one stopped before it.
    A ticket that came into the journal any other way while it ran, such as one the operator started, is not owed one:
    the next tick's block carries it.

    Returns:
        One phrase per kind of duty left undone, empty when the overseer did every one.
    """
    # The harness's own, before the overseer ran or after (DESIGN §37), are never the overseer's; a `queried` it
    # recorded still stands for the query.
    made = db.decisions_for_tick(conn, tick_id)
    recorded = [d for d in made if d.id > duties.harness and d.decider is not Decider.HARNESS]
    queried = [d for d in made if d.action == QUERIED_ACTION]
    missing: list[str] = []
    if duties.query_due and not queried:
        missing.append("the tracker query was due and no `canopy queried` recorded it")
    found = {key for d in queried for key in queried_keys(d.rationale)}
    decided = {d.ticket_key for d in recorded if d.ticket_key is not None}
    exempt = duties.exempt | set(conversation.stopped(conn))
    tickets = sorted((duties.tickets | found) - exempt - decided)
    if tickets:
        named = ", ".join(tickets[:_NAMED]) + (f" and {len(tickets) - _NAMED} more" if len(tickets) > _NAMED else "")
        missing.append(f"no decision for {named}")
    chores = sorted(duties.chores - {d.chore for d in recorded if d.chore is not None})
    if chores:
        missing.append(f"no run or wait for chore {', '.join(chores)}")
    return missing
