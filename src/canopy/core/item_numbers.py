"""Journal numbers (DESIGN §35): what a cursor names, one order for every kind of item it passes.

Each comment, review, review comment, and completed check run takes the next number when a source first observes it,
and keeps it across later reads of its subject, which replace the observation's row but never its number; a canopy
review run takes one when it ends. An item is newer than a cursor when its number is larger: it was first observed
after the item the cursor names. Neither the source's ids, which no tracker orders, nor its times, which a late
submission backdates, give that order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import records, sql
from canopy.core.vocab import NumberedItem

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
    sql.execute(conn, sql.insert("item_numbers", kind=kind, subject=subject, id=found, numbered_at=at).or_ignore())
    row = sql.execute(
        conn,
        sql.select("number").from_("item_numbers").where("subject = ? AND kind = ? AND id = ?", subject, kind, found),
    ).fetchone()
    return int(row[0])


def newer(number: int | None, cursor: int | None) -> bool:
    """Whether an item numbered `number` is newer than `cursor`: first observed after the item the cursor names.

    An item with no number is newer than any cursor, so nothing a cursor passes is lost; the journal numbers every one.

    Returns:
        True with no cursor, or a number past it.
    """
    return cursor is None or number is None or number > cursor


def named(conn: sqlite3.Connection, numbers: Collection[int]) -> dict[int, records.ItemNumber]:
    """The items `numbers` name, as cursors hold them.

    Returns:
        Each item numbered, by its number; a number that names none is left out.
    """
    query = sql.select("*").from_("item_numbers").where_in("number", numbers)
    return {n.number: n for n in records.fetch_all(conn, records.ItemNumber, query)}


def describe(item: records.ItemNumber) -> str:
    """Say what a cursor's number names in the source's terms, for a live read that has no numbers (DESIGN §35).

    Returns:
        Its kind, the source's id for it, and when it was numbered: first observed, or a review run's end.
    """
    when = "ended" if item.kind is NumberedItem.REVIEW_RUN else "first observed"
    return f"{item.kind.value.replace('_', ' ')} {item.id}, {when} {item.numbered_at}"
