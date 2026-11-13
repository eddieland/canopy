"""Journal numbers (DESIGN §35): what a cursor names, one order for every kind of item it passes.

Each comment, review, review comment, comment on a PR's conversation, and completed check run takes the next number
when a source first observes it, and keeps it across later reads of its subject, which replace the observation's row
but never its number; a canopy review run takes one when it ends. An item is newer than a cursor when its number is
larger: it was first observed after the item the cursor names. Neither the source's ids, which no tracker orders, nor
its times, which a late submission backdates, give that order.

A review item's number also records the live tick, closed `ok`, whose overseer was first shown its text and decided
its ticket, so the state block shows a body once (DESIGN §30): as it closes, a tick marks what it showed of each ticket
the overseer decided, and a dry run marks nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from canopy.core import records, sql
from canopy.core.vocab import NumberedItem, ReviewItem

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection


def take(conn: sqlite3.Connection, kind: NumberedItem, subject: str, ident: str | int, *, at: str) -> int:
    """The journal number of an item, taking the next one at `at` when it has none: it is first observed, or ended.

    `subject` is a ticket's key for a comment, a PR's URL for the rest; `ident` the source's id for the item, or
    canopy's own for a review run. Call inside the transaction that records the item.

    Returns:
        Its number.
    """
    found = str(ident)
    records.insert(records.ItemNumber, kind=kind, subject=subject, id=found, numbered_at=at).or_ignore().run(conn)
    row = sql.execute(
        conn,
        sql.select("number").from_("item_numbers").where("subject = ? AND kind = ? AND id = ?", subject, kind, found),
    ).fetchone()
    return int(row[0])


def of_review(item: ReviewItem) -> NumberedItem:
    """The kind a review item of `item`'s kind is numbered as.

    Returns:
        It.
    """
    match item:
        case ReviewItem.REVIEW:
            return NumberedItem.REVIEW
        case ReviewItem.COMMENT:
            return NumberedItem.REVIEW_COMMENT
        case ReviewItem.PR_COMMENT:
            return NumberedItem.PR_COMMENT
        case _:
            assert_never(item)


def called(item: ReviewItem) -> str:
    """What a review item of `item`'s kind is called where canopy names one for a person or an agent.

    Returns:
        `review`, `review comment`, or `PR comment`.
    """
    match item:
        case ReviewItem.REVIEW:
            return "review"
        case ReviewItem.COMMENT:
            return "review comment"
        case ReviewItem.PR_COMMENT:
            return "PR comment"
        case _:
            assert_never(item)


def newer(number: int | None, cursor: int | None) -> bool:
    """Whether an item numbered `number` is newer than `cursor`: first observed after the item the cursor names.

    An item with no number is newer than any cursor, so nothing a cursor passes is lost; the journal numbers every one.

    Returns:
        True with no cursor, or a number past it.
    """
    return cursor is None or number is None or number > cursor


def shown(conn: sqlite3.Connection, subjects: Collection[str]) -> set[int]:
    """The review items of the PRs `subjects` whose text an overseer was shown, by number (DESIGN §30).

    Returns:
        Each such number.
    """
    query = records.select(records.ItemNumber).where("shown_tick_id IS NOT NULL").where_in("subject", subjects)
    return {n.number for n in query.all(conn)}


def mark_shown(conn: sqlite3.Connection, tick_id: int, numbers: Collection[int]) -> None:
    """Record that tick `tick_id`, closing `ok`, showed the overseer the text of the items `numbers`.

    One marked by an earlier tick keeps that tick: what matters is that its text was shown once. Call inside the
    transaction that closes the tick, so a tick that dies as it closes marks nothing.
    """
    if not numbers:
        return
    update = records.update(records.ItemNumber).set(shown_tick_id=tick_id).where("shown_tick_id IS NULL")
    update.where_in("number", numbers).run(conn)


def named(conn: sqlite3.Connection, numbers: Collection[int]) -> dict[int, records.ItemNumber]:
    """The items `numbers` name, as cursors hold them.

    Returns:
        Each item numbered, by its number; a number that names none is left out.
    """
    query = records.select(records.ItemNumber).where_in("number", numbers)
    return {n.number: n for n in query.all(conn)}


def describe(item: records.ItemNumber) -> str:
    """Say what a cursor's number names in the source's terms, for a live read that has no numbers (DESIGN §35).

    Returns:
        Its kind, the source's id for it, and when it was numbered: first observed, or a review run's end.
    """
    when = "ended" if item.kind is NumberedItem.REVIEW_RUN else "first observed"
    return f"{item.kind.value.replace('_', ' ')} {item.id}, {when} {item.numbered_at}"
