"""What a new approval of an epic's plan does to its members (DESIGN §43, When its plan changes).

The approval compares the plan's ids with the plan approved before it (`epic_outline.compare`), and meets each member
the change reaches where it stands, in the approval's own transaction, with the dispatch lock held, so no dispatch
decides between the two:

- a plan still `proposed` is superseded as stale, naming the ids that reached it;
- an approved plan whose ticket has no branch yet holds its `implement` (`epic_changed`, checked at dispatch) until the
  operator approves the plan again or asks for a new one;
- a run in flight, or a ticket with a branch, is never paused or touched.

Each keeps the ids that reached it as its pending notice, which its next plan, `implement`, or `resume` is told once, as
data (`told`), and the operator's approval of its plan clears (`approved`). The ids are data read from plans the
operator approved, never an instruction (TRUST_MODEL T1). A member with nothing written against the older plan, no
plan, run, branch, or notice, is left as it is: its first plan reads the new one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from canopy.core import db, epic_outline, records
from canopy.core.vocab import PlanStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Sequence
    from collections.abc import Set as AbstractSet

#: How an approval met a member it reached, as `Reached` names the ways.
type Way = Literal["stale", "held", "told"]


@dataclass(frozen=True)
class Reached:
    """The members an approval of an epic's plan reached, by ticket key, each way (DESIGN §43)."""

    #: Those whose plan waited on the operator, superseded as stale: their next plan is told the ids.
    stale: Sequence[str] = ()
    #: Those whose approved plan's `implement` now waits on the operator (`epic_changed`).
    held: Sequence[str] = ()
    #: Those left as they are, at work, with a branch, or waiting to be planned again: their next run is told.
    told: Sequence[str] = ()

    def any(self) -> bool:
        """Return whether the approval reached any member."""
        return bool(self.stale or self.held or self.told)


@dataclass(frozen=True)
class Pending:
    """A member's pending notice: the ids changes of its epic's plan reached it by, which its work has not taken in."""

    epic_id: int
    ids: Sequence[str]


def reach(
    conn: sqlite3.Connection,
    epic_id: int,
    change: epic_outline.Change,
    *,
    before: epic_outline.Outline,
    after: epic_outline.Outline,
) -> Reached:
    """Meet each member of epic `epic_id` that `change` reaches where it stands. Call inside the approval's transaction.

    `before` is the plan approved before, `after` the one being approved. A member's entries are those it was
    registered against that `before` holds: one whose every entry an earlier approval dropped is a member of no entry,
    which every change reaches.

    Returns:
        The members it reached, each way, in the order they were added.
    """
    ways: dict[Way, list[str]] = {"stale": [], "held": [], "told": []}
    members = records.select(records.EpicMember).where("epic_id = ? AND removed_at IS NULL", epic_id)
    for member in members.order_by("id").all(conn):
        registered = records.select(records.EpicMemberEntry).where("member_id = ?", member.id).all(conn)
        entries = frozenset(r.entry for r in registered if r.entry in before.entries)
        ids = epic_outline.reaching(change, entries, before=before, after=after)
        if not ids:
            continue
        way = _meet(conn, member, ids)
        if way is not None:
            ways[way].append(member.ticket_key)
    return Reached(stale=tuple(ways["stale"]), held=tuple(ways["held"]), told=tuple(ways["told"]))


def pending(conn: sqlite3.Connection, key: str) -> Pending | None:
    """Return ticket `key`'s pending notice, or None when it is a member of no epic or has none."""
    member = _membership(conn, key)
    if member is None or not member.changed_ids:
        return None
    return Pending(epic_id=member.epic_id, ids=epic_outline.ordered(_split(member.changed_ids)))


def told(conn: sqlite3.Connection, key: str, ids: Iterable[str]) -> None:
    """Take `ids` out of ticket `key`'s pending notice: a run was told them. Call inside the run's insert.

    An approval since the run's prompt was rendered may have added others, which stay for its next run.
    """
    member = _membership(conn, key)
    if member is None or not member.changed_ids:
        return
    _set_pending(conn, member, _split(member.changed_ids) - frozenset(ids))


def approved(conn: sqlite3.Connection, key: str) -> None:
    """Clear ticket `key`'s pending notice: the operator approved its plan, with the epic's plan as it is approved now.

    Call inside the approval's transaction.
    """
    member = _membership(conn, key)
    if member is not None and member.changed_ids:
        _set_pending(conn, member, frozenset())


def _meet(conn: sqlite3.Connection, member: records.EpicMember, ids: AbstractSet[str]) -> Way | None:
    """Meet `member`, reached by `ids`, where it stands, and add them to its pending notice.

    Returns:
        The way it met it; None when nothing of it was written against the older plan, which leaves it as it is.
    """
    key = member.ticket_key
    ticket = db.get_ticket(conn, key)
    plan = records.select(records.Plan).where("ticket_key = ? AND status != ?", key, PlanStatus.SUPERSEDED).one(conn)
    notice = _split(member.changed_ids)
    way: Way | None
    if db.running_run_of(conn, key) is not None or (ticket is not None and ticket.branch):
        # Never paused or touched: what it builds keeps to its own approved plan, and its next run is told.
        way = "told"
    elif plan is not None and plan.status is PlanStatus.PROPOSED:
        update = records.update(records.Plan).set(status=PlanStatus.SUPERSEDED, epic_changed_ids=_joined(ids))
        update.where("id = ?", plan.id).run(conn)
        way = "stale"
    elif plan is not None and plan.status is PlanStatus.APPROVED:
        way = "held"
    else:
        way = "told" if notice else None
    if way is not None:
        _set_pending(conn, member, notice | ids)
    return way


def _membership(conn: sqlite3.Connection, key: str) -> records.EpicMember | None:
    """Return ticket `key`'s membership of an epic, or None while it is a member of none."""
    return records.select(records.EpicMember).where("ticket_key = ? AND removed_at IS NULL", key).one(conn)


def _set_pending(conn: sqlite3.Connection, member: records.EpicMember, ids: AbstractSet[str]) -> None:
    """Replace `member`'s pending notice with `ids`, None when there are none."""
    update = records.update(records.EpicMember).set(changed_ids=_joined(ids) if ids else None)
    update.where("id = ?", member.id).run(conn)


def _joined(ids: Iterable[str]) -> str:
    """Return `ids` as a column holds them: in the plan's order, space-separated."""
    return " ".join(epic_outline.ordered(ids))


def _split(text: str | None) -> frozenset[str]:
    """Return the ids a column holds, none for None."""
    return frozenset(text.split()) if text else frozenset()
