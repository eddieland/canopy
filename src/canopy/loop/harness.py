"""The harness decides what needs no judgment (DESIGN §37, ROADMAP M38): its decisions, recorded before the overseer.

Each tick, after the derivation (§30), the harness takes a ticket whole when every row of §7 that holds for it and for
each of its units is one it decides, and none rests on a stale observation. It records the ticket's decision, marked as
its own (`decisions.decider`), and the phase that row names, and the state block names it instead of listing the
ticket. One row it does not decide, anywhere on the ticket, leaves the ticket whole to the overseer, which reads the
derivation's rows beside the observations. So does a ticket that is not a fresh, open candidate, and one with an item
the overseer holds open on the attention list, which it keeps only by recording it again each tick (D020).

The rows it decides are `ROWS`: only those it reads from its own journal alone, which need no measurement (§37, The
evidence gate). A row that rests on what a connector observed joins them only by a PR citing the measurement that shows
the derivation right on it; no switch in config turns one on.

Whatever the overseer records about a ticket the harness decided, through a tool or its command, is refused `decided`
(`loop.tools`), and the duties check owes it nothing about one (§6).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from canopy.core import conversation, db, records, sql
from canopy.core.vocab import Decider, Phase
from canopy.loop import attention

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context
    from canopy.loop.phases import Derived


@dataclass(frozen=True)
class Row:
    """A row of §7 the harness decides: what it records for it, and on which tickets."""

    #: What it records, as `canopy decide` would.
    action: str
    #: Why, the decision's rationale.
    why: str
    #: Whether only a private ticket's row is read from the journal alone (§22): a public one's is the tracker's.
    private_only: bool = False


#: The rows the harness decides, each read from its own journal alone. `running`: a worker of the ticket is running,
#: in `runs`. `needs_human` on a private ticket: its latest run ended `blocked` and no operator message came after,
#: both in the journal; a public ticket's rests on the tracker's label, which a connector observes.
ROWS: Mapping[Phase, Row] = {
    Phase.RUNNING: Row("wait", "a worker of it is running"),
    Phase.NEEDS_HUMAN: Row("wait", "its latest run asked the operator, who has not answered", private_only=True),
}


@dataclass(frozen=True)
class Decision:
    """A ticket the harness decides this tick: what it records, and the phase it sets."""

    key: str
    phase: Phase
    action: str
    rationale: str


class Decided(TypedDict):
    """A ticket the harness decided this tick, as the state block names it: its key, action, and why."""

    ticket: str
    action: str
    why: str


def decide(ctx: Context, derived: Iterable[Derived]) -> list[Decision]:
    """Decide each ticket every row of whose derivation is one of `ROWS`, from the tick's derivation `derived`.

    Returns:
        A decision per ticket the harness takes, by key; none for a ticket left to the overseer.
    """
    by_ticket: dict[str, list[Derived]] = {}
    for d in derived:
        by_ticket.setdefault(d.ticket_key, []).append(d)
    kept = held(ctx.conn)
    found: list[Decision] = []
    for key in sorted(by_ticket):
        if key in kept:
            continue
        decision = _decided(ctx.conn, key, by_ticket[key])
        if decision is not None:
            found.append(decision)
    return found


def held(conn: sqlite3.Connection) -> set[str]:
    """The tickets with an item the overseer holds open on the attention list: each stays the overseer's whole.

    An item the overseer recorded stays open only while it records it again (D020), so taking its ticket would drop it.

    Returns:
        Their keys.
    """
    items = attention.current(conn)
    return {i.ticket_key for i in items if i.ticket_key is not None and i.reason not in attention.HARNESS_REASONS}


def record(conn: sqlite3.Connection, tick_id: int, repo: str, decisions: Iterable[Decision]) -> None:
    """Record the harness's `decisions` in tick `tick_id`, each marked as its own, with its phase, in one transaction.

    `repo` is the workspace root a ticket the journal touches is recorded under. A dry run records them too: they are
    decisions, not actions, and its corpus holds who made each (D036).
    """
    with db.transaction(conn):
        for d in decisions:
            db.touch_ticket(conn, d.key, repo)
            db.change_ticket(conn, d.key, "phase", d.phase)
            db.record_decision(conn, tick_id, d.key, d.action, d.rationale, decider=Decider.HARNESS)


def recorded(conn: sqlite3.Connection, tick_id: int) -> list[records.Decision]:
    """The decisions the harness recorded about tickets in tick `tick_id`: its own, not the attention items it raises.

    Returns:
        Them, in the order they were recorded.
    """
    return records.fetch_all(
        conn,
        records.Decision,
        sql.select("*")
        .from_("decisions")
        .where("tick_id = ? AND decider = ? AND ticket_key IS NOT NULL", tick_id, Decider.HARNESS)
        .where("action NOT LIKE ?", f"{attention.ACTION_PREFIX}%")
        .order_by("id"),
    )


def decided(conn: sqlite3.Connection, tick_id: int, key: str) -> bool:
    """Whether the harness decided ticket `key` in tick `tick_id`.

    Returns:
        True when it recorded a decision about it there, not counting an attention item.
    """
    return any(d.ticket_key == key for d in recorded(conn, tick_id))


def section(decisions: Iterable[records.Decision]) -> list[Decided]:
    """The state block's `harness`: each ticket the harness decided, so the overseer leaves it out (DESIGN §37).

    Returns:
        One entry per decision, in the order they were recorded.
    """
    return [{"ticket": str(d.ticket_key), "action": d.action, "why": d.rationale} for d in decisions]


def _decided(conn: sqlite3.Connection, key: str, subjects: Sequence[Derived]) -> Decision | None:
    """The harness's decision about ticket `key`, from its derived `subjects`: its own row first, then its units'.

    Returns:
        The decision, or None when the ticket is left to the overseer.
    """
    own = subjects[0]
    if own.repo is not None or own.stale is not None or own.closed or not own.candidate or not own.phases:
        return None
    private = conversation.is_started(conversation.start_of(conn, key))
    if not all(_takes(s, private=private) for s in subjects):
        return None
    phase = own.phases[0]
    row = ROWS[phase]
    return Decision(key, phase, row.action, f"{phase}: {row.why}")


def _takes(subject: Derived, *, private: bool) -> bool:
    """Whether every row that held for `subject` is one the harness decides, on a ticket `private` or not.

    Returns:
        False for a stale subject, or one with a row not in `ROWS`.
    """
    if subject.stale is not None:
        return False
    return all(p in ROWS and (private or not ROWS[p].private_only) for p in subject.phases)
