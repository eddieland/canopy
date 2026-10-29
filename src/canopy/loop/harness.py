"""The harness decides what needs no judgment (DESIGN §37, ROADMAP M38): its decisions, recorded before the overseer.

Each tick, after the derivation (§30), the harness takes a ticket whole when every row of §7 that holds for it and for
each of its units is one it decides, and none rests on a stale observation. It records the ticket's decision, marked as
its own (`decisions.decider`), and the phase that row names, and the state block names it instead of listing the
ticket. One row it does not decide, anywhere on the ticket, leaves the ticket whole to the overseer, which reads the
derivation's rows beside the observations. So does a ticket that is not a fresh, open candidate, but for one whose
observation the `tracker` source left stale: the overseer reads no tracker where a source does (§39), so the harness
records its `wait`, naming what is old. Where the `vcs` source runs beside it, the overseer reads no GitHub either, so a
candidate with a PR, branches, or an open blocker's PR that source left stale is the harness's `wait` too, and so is one
with a unit's PR no source reads at all, its URL naming no PR, until the operator forgets its work. So does one with a
`merged` row while a `multi_repo` item is open on it: a repository's part may remain. An item the overseer holds
open on a ticket the harness takes stands while the overseer is not given the ticket (`attention.current`).

The rows it decides are `ROWS`: only those it reads from its own journal alone, which need no measurement (§37, The
evidence gate). A row that rests on what a connector observed joins them only by a PR citing the measurement that shows
the derivation right on it; no switch in config turns one on.

Whatever the overseer records about a ticket the harness decided, through a tool or its command, is refused `decided`
(`loop.tools`), and the duties check owes it nothing about one (§6). A cursor the harness moves, past what needs no
handling or what its own run handles (`loop.harness_cursors`), is its decision too, `CURSOR_ACTION`, but decides
nothing about the ticket.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from canopy.core import conversation, db, kept_items, records
from canopy.core.vocab import Decider, Phase
from canopy.loop import attention

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context
    from canopy.loop.phases import Derived


#: The decision a cursor the harness moved is recorded as (`loop.harness_cursors`): its own, about the ticket, yet no
#: decision of the ticket's.
CURSOR_ACTION = "cursor"


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
    #: None for a ticket whose observation is stale: no row was derived, so its phase stays as it was.
    phase: Phase | None
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
    merged = any(Phase.MERGED in d.phases for subjects in by_ticket.values() for d in subjects)
    apart = (
        {i.ticket_key for i in attention.current(ctx.conn) if i.reason == kept_items.MULTI_REPO} if merged else set()
    )
    found: list[Decision] = []
    for key in sorted(by_ticket):
        subjects = by_ticket[key]
        if key in apart and any(Phase.MERGED in s.phases for s in subjects):
            continue
        decision = _decided(ctx.conn, key, subjects)
        if decision is not None:
            found.append(decision)
    return found


def record(conn: sqlite3.Connection, tick_id: int, repo: str, decisions: Iterable[Decision]) -> None:
    """Record the harness's `decisions` in tick `tick_id`, each marked as its own, with its phase, in one transaction.

    `repo` is the workspace root a ticket the journal touches is recorded under. A dry run records them too: they are
    decisions, not actions, and its corpus holds who made each (D036).
    """
    with db.transaction(conn):
        for d in decisions:
            db.touch_ticket(conn, d.key, repo)
            if d.phase is not None:
                db.change_ticket(conn, d.key, "phase", d.phase)
            db.record_decision(conn, tick_id, d.key, d.action, d.rationale, decider=Decider.HARNESS)


def recorded(conn: sqlite3.Connection, tick_id: int) -> list[records.Decision]:
    """The decisions the harness recorded about tickets in tick `tick_id`: not its attention items, nor cursors moved.

    Returns:
        Them, in the order they were recorded.
    """
    return (
        records.select(records.Decision)
        .where("tick_id = ? AND decider = ? AND ticket_key IS NOT NULL", tick_id, Decider.HARNESS)
        .where("action NOT LIKE ? AND action != ?", f"{attention.ACTION_PREFIX}%", CURSOR_ACTION)
        .order_by("id")
        .all(conn)
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
    stale = _stale(subjects)
    if stale is not None:
        # The ticket waits for a read that is whole, and the source that left it stale has raised `connector_failed`
        # (§30). One marked done, which the query still finds, is owed nothing (§7).
        ticket = db.get_ticket(conn, key)
        if ticket is not None and ticket.done:
            return None
        what, source = stale
        if source is None:
            why = f"unobserved: {what}; no source reads it, so it waits until the operator forgets the ticket's work"
        else:
            why = f"stale: {what}; it waits for the {source} source to read it again"
        return Decision(key, None, "wait", why)
    if own.repo is not None or own.stale is not None or own.closed or not own.candidate or not own.phases:
        return None
    private = conversation.is_started(conversation.start_of(conn, key))
    if not all(_takes(s, private=private) for s in subjects):
        return None
    phase = own.phases[0]
    row = ROWS[phase]
    return Decision(key, phase, row.action, f"{phase}: {row.why}")


def _stale(subjects: Sequence[Derived]) -> tuple[str, str | None] | None:
    """What a ticket's decision rests on that a source left stale, or none reads, where the overseer reads it no longer.

    The overseer reads no tracker where a `tracker` source does, nor GitHub where the `vcs` source runs beside it
    (§39). The ticket's own observation is the `tracker` source's; on a candidate fresh, or stale only by what the
    `vcs` source reads, the first subject that source left stale, or that no source reads, is its. A closed or
    unlabeled ticket is decided without its PRs.

    Returns:
        What is stale, and the kind of source that left it so, None for what no source reads; None when nothing is.
    """
    own = subjects[0]
    if own.repo is None and own.stale is not None and own.stale_tracker:
        return own.stale, "tracker"
    if not (own.stale_vcs or (own.stale is None and own.candidate is True and not own.closed)):
        return None
    waited = (s for s in subjects if s.stale is not None and (s.stale_vcs or s.unobserved))
    return next(((str(s.stale), None if s.unobserved else "vcs") for s in waited), None)


def _takes(subject: Derived, *, private: bool) -> bool:
    """Whether every row that held for `subject` is one the harness decides, on a ticket `private` or not.

    Returns:
        False for a stale subject, or one with a row not in `ROWS`.
    """
    if subject.stale is not None:
        return False
    return all(p in ROWS and (private or not ROWS[p].private_only) for p in subject.phases)
