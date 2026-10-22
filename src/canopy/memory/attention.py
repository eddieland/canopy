"""The attention items memory raises (DESIGN §14, §28), every tick their cause holds, for the operator alone.

`memory_proposal`, about a ticket marked done, while a proposal from its runs waits: a merge has checked the work it
came from. `lesson_review`, one item naming the lessons due, longest overdue first, and `lesson_wrong`, one naming the
lessons a run reported wrong since their last renewal: both only at `use`, since no run reads a lesson before. An item
names at most `MAX_NAMED` and counts the rest. None arises while `memory.proposals` is off. The overseer never sees
them: they are harness reasons (`attention.HARNESS_REASONS`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from canopy.core import db, memory, sql
from canopy.core.vocab import MemoryMode

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

    from canopy.core.config import Config

# The most ids one item names; the rest are counted, so a workspace with many lessons due raises one short item.
MAX_NAMED = 10


@dataclass(frozen=True)
class Item:
    """One item to raise: its ticket, or None for one about the workspace, its reason, and its detail."""

    ticket_key: str | None
    reason: str
    detail: str


def items(conn: sqlite3.Connection, config: Config, now: datetime | None = None) -> list[Item]:
    """Return the memory items whose cause holds now.

    Returns:
        A `memory_proposal` per done ticket with a proposal pending, by ticket; then at `use` one `lesson_review` and
        one `lesson_wrong` when any lesson calls for it.
    """
    mode = config.memory.proposals
    if mode is MemoryMode.OFF:
        return []
    found: list[Item] = []
    remembered = sql.select("ticket_key").from_("memories")
    done = {
        str(r["key"])
        for r in sql.execute(
            conn,
            sql.select("key").from_("tickets").where("done = 1").where("key IN ({})", remembered),
        )
    }
    by_ticket: dict[str, list[int]] = {}
    for p in memory.pending_proposals(conn):
        if p.ticket_key in done:
            by_ticket.setdefault(p.ticket_key, []).append(p.id)
    for key, ids in sorted(by_ticket.items()):
        detail = (
            f"{_named('proposal', ids)} from {key}'s runs wait on you, and its work is done: "
            "`canopy memory proposals`, then promote or reject each"
        )
        found.append(Item(key, memory.PROPOSAL_REASON, detail))
    if mode is not MemoryMode.USE:
        return found
    stamp = db.format_time(now or datetime.now(UTC))
    lessons = memory.active_lessons(conn)
    overdue = [m for m in lessons if m.review_at is not None and m.review_at <= stamp]
    due = [m.id for m in sorted(overdue, key=lambda m: (m.review_at or "", m.id))]
    if due:
        detail = (
            f"{_named('lesson', due)} {'is' if len(due) == 1 else 'are'} due for review: renew each with "
            "`canopy memory renew ID`, pin it for good with `canopy memory pin ID`, graduate it into a repository's "
            "AGENTS.md or a skill, or forget it"
        )
        found.append(Item(None, memory.REVIEW_REASON, detail))
    wrong = [f"{m.id} (run {m.wrong_run_id})" for m in lessons if m.wrong_at is not None]
    if wrong:
        detail = (
            f"a run reported lesson{'s' if len(wrong) > 1 else ''} {_listed(wrong)} wrong: read it with "
            "`canopy memory lessons`, then renew or forget it"
        )
        found.append(Item(None, memory.WRONG_REASON, detail))
    return found


def _named(what: str, ids: Sequence[int]) -> str:
    return f"{what} {ids[0]}" if len(ids) == 1 else f"{what}s {_listed([str(i) for i in ids])}"


def _listed(names: Sequence[str]) -> str:
    more = len(names) - MAX_NAMED
    # Never `and 1 more`: naming the last one takes no more room than counting it.
    if more <= 1:
        return ", ".join(names)
    return f"{', '.join(names[:MAX_NAMED])}, and {more} more"
