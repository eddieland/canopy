"""The attention items the overseer keeps: recorded once, naming what each is about, and held until that ends it.

Three reasons are judgment the overseer keeps (DESIGN §14, §37): `needs_author`, a comment or review that needs a
human; `multi_repo`, a ticket of several pieces across repositories; and `notice_rerun`, a check a notice held that
needs a rerun canopy cannot start. Each is recorded once, marked `kept`, about a ticket, naming in `item` the journal
number (§35) of what it is about where it names one. It is held from the `ok` tick that recorded it, whatever later
ticks record or leave out, until what it names ends it:

- a `needs_author` naming an item: its ticket's comment cursor, or the review cursor of the unit whose PR it is on,
  passes that item, so the overseer has handled it;
- a `needs_author` and a `multi_repo`: the operator answers on the ticket after it, a message that answers questions;
- a `notice_rerun`: a newer run of the check run it names is observed on its PR;
- any of them: its ticket is done, or the operator stopped it.

The overseer cannot end one itself, but by moving a cursor past the item it names (TRUST_MODEL T1). A record that names
nothing that could end it is refused (`unnamed`): one about no ticket, a `notice_rerun` that names no check run, or an
item that is not one of its subject's. Chosen conservatively, for the operator to change: a reply on the tracker ends
none, nor does a comment on one of the ticket's artifacts; the operator's own message does.

A record from a dry run counts only while its tick is the latest `ok` one, so a dry run changes nothing the next live
tick reads (D036). Before these were kept, the overseer recorded each every tick its cause held; such a record is not
`kept`, and the list reads it as it did then (`loop.attention`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from canopy.core import conversation, db, item_numbers, records, sql
from canopy.core.items import ACTION_PREFIX
from canopy.core.vocab import NumberedItem

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable, Mapping, Sequence

NEEDS_AUTHOR = "needs_author"
MULTI_REPO = "multi_repo"
NOTICE_RERUN = "notice_rerun"
#: The reasons the overseer keeps.
KEPT: frozenset[str] = frozenset({NEEDS_AUTHOR, MULTI_REPO, NOTICE_RERUN})
#: The reasons whose record may name an item: what a `needs_author` waits on, and the check a `notice_rerun` holds.
NAMING: frozenset[str] = frozenset({NEEDS_AUTHOR, NOTICE_RERUN})
#: What a `needs_author` may wait on: a comment on its ticket, or a review item or review run on one of its PRs.
_AUTHOR_ITEMS: frozenset[NumberedItem] = frozenset(
    {NumberedItem.COMMENT, NumberedItem.REVIEW, NumberedItem.REVIEW_COMMENT, NumberedItem.REVIEW_RUN},
)


@dataclass(frozen=True)
class Held:
    """A record of an item the overseer keeps, still held: nothing it names has ended it."""

    ticket_key: str
    reason: str
    #: The repository of the ticket's unit it is about.
    repo: str | None
    #: The journal number of what it names; None for one about its ticket alone.
    item: int | None
    #: What the operator needs to know, as the overseer worded it.
    detail: str
    #: When it was recorded.
    at: str


def unnamed(
    conn: sqlite3.Connection,
    *,
    key: str | None,
    reason: str,
    repo: str | None,
    item: int | None,
) -> str | None:
    """Why a record of `reason`, one of `KEPT`, names nothing that could end it; None when it names something.

    `key` is its ticket, `repo` its unit's repository, and `item` the journal number it names.

    Returns:
        What it lacks, in a sentence the refusal carries; None for a record the harness can hold.
    """
    if key is None:
        return f"{reason} is held until something about its ticket ends it: name the ticket"
    if item is not None and reason not in NAMING:
        return f"{reason} is about its ticket alone, and names no item"
    if item is None:
        if reason == NOTICE_RERUN:
            return "notice_rerun is held until a newer run of its check is observed: name the check run's number"
        return None
    found = item_numbers.named(conn, [item]).get(item)
    if found is None:
        return f"item {item} names nothing the journal observed"
    return _foreign(conn, found, key=key, reason=reason, repo=repo)


def _foreign(
    conn: sqlite3.Connection,
    item: records.ItemNumber,
    *,
    key: str,
    reason: str,
    repo: str | None,
) -> str | None:
    """Why `item` is not what a record of `reason` about ticket `key`, and unit `repo` if named, may name.

    Returns:
        What is wrong with it; None when it is a comment on the ticket, or an item of its kind on one of its units' PRs.
    """
    wanted = _AUTHOR_ITEMS if reason == NEEDS_AUTHOR else frozenset({NumberedItem.CHECK_RUN})
    if item.kind not in wanted:
        return f"item {item.number} is a {item.kind}, which no {reason} names"
    if item.kind is NumberedItem.COMMENT:
        return None if item.subject == key else f"item {item.number} is a comment on another ticket"
    if item.subject in {u.pr_url for u in db.units(conn, key) if repo is None or u.repo == repo}:
        return None
    return f"item {item.number} is on {item.subject}, the PR of no unit of {key}" + (f" in {repo}" if repo else "")


def held(conn: sqlite3.Connection) -> list[Held]:
    """Every record of an item the overseer keeps that nothing it names has ended yet, oldest first.

    Returns:
        Each such record from an `ok` tick: a live one, or the latest `ok` tick when that one was a dry run.
    """
    rows = records.fetch_all(
        conn,
        records.Decision,
        sql.select("*")
        .from_("decisions")
        .where("kept = 1 AND ticket_key IS NOT NULL")
        # Each kept record looks up its own tick, and the latest `ok` tick is found from the newest back, so the read
        # costs the records held, not every tick the journal has recorded.
        .where(
            "EXISTS (SELECT 1 FROM ticks t WHERE t.id = decisions.tick_id AND t.status = 'ok' AND (t.dry_run = 0 OR "
            "t.id = (SELECT id FROM ticks WHERE status = 'ok' ORDER BY id DESC LIMIT 1)))",
        )
        .order_by("id"),
    )
    if not rows:
        return []
    keys = {str(r.ticket_key) for r in rows}
    gone = ended_tickets(conn, keys)
    named = item_numbers.named(conn, {r.item for r in rows if r.item is not None})
    answers = _answers(conn, keys)
    return [
        Held(str(r.ticket_key), r.action.removeprefix(ACTION_PREFIX), r.repo, r.item, r.rationale, r.created_at)
        for r in rows
        if r.ticket_key not in gone and not _ended(conn, r, named, answers.get(str(r.ticket_key), ()))
    ]


def ended_tickets(conn: sqlite3.Connection, keys: Collection[str]) -> set[str]:
    """Which of tickets `keys` no item the overseer recorded is about any longer: done, or stopped by the operator.

    Returns:
        Their keys.
    """
    if not keys:
        return set()
    done = sql.select("key").from_("tickets").where("done = 1").where_in("key", keys)
    stopped = (
        sql.select("subject_id")
        .from_("starts")
        .where("subject_kind = ? AND status = 'stopped'", conversation.TICKET)
        .where_in("subject_id", keys)
    )
    return {str(r[0]) for r in sql.execute(conn, done)} | {str(r[0]) for r in sql.execute(conn, stopped)}


def _answers(conn: sqlite3.Connection, keys: Collection[str]) -> dict[str, list[str]]:
    """When the operator answered on each of tickets `keys`: their messages that answer questions, not a verb's.

    Returns:
        Each message's time, by ticket.
    """
    messages = (
        records.select(records.Message)
        .where("subject_kind = ? AND source = 'operator'", conversation.TICKET)
        .where_in("subject_id", keys)
        .all(conn)
    )
    found: dict[str, list[str]] = {}
    for m in messages:
        if conversation.answers_questions(m):
            found.setdefault(m.subject_id, []).append(m.at)
    return found


def _ended(
    conn: sqlite3.Connection,
    record: records.Decision,
    named: Mapping[int, records.ItemNumber],
    answers: Iterable[str],
) -> bool:
    """Whether what `record` names has ended it, `answers` being when the operator answered on its ticket.

    Returns:
        True once its own cause is gone; never for a reason not kept.
    """
    reason = record.action.removeprefix(ACTION_PREFIX)
    after = db.parse_time(record.created_at)
    answered = any(db.parse_time(at) > after for at in answers)
    item = named.get(record.item) if record.item is not None else None
    if reason == NEEDS_AUTHOR:
        return answered or (item is not None and _passed(conn, str(record.ticket_key), item))
    if reason == MULTI_REPO:
        return answered
    if reason == NOTICE_RERUN:
        # A check run the journal no longer holds names no check: it stays, until its ticket is done or stopped.
        return item is not None and _rerun(conn, item)
    return False


def _passed(conn: sqlite3.Connection, key: str, item: records.ItemNumber) -> bool:
    """Whether ticket `key`'s cursor of `item`'s kind passes it: its comment cursor, or its PR's unit's review cursor.

    Returns:
        True when that cursor is at or past the item.
    """
    match item.kind:
        case NumberedItem.COMMENT:
            query = sql.select("comment_cursor").from_("tickets").where("key = ?", key)
        case NumberedItem.REVIEW | NumberedItem.REVIEW_COMMENT | NumberedItem.REVIEW_RUN:
            units = sql.select("review_cursor").from_("ticket_units")
            query = units.where("ticket_key = ? AND pr_url = ?", key, item.subject)
        case NumberedItem.CHECK_RUN:
            return False
        case _:
            assert_never(item.kind)
    return any(r[0] is not None and int(r[0]) >= item.number for r in sql.execute(conn, query))


def _rerun(conn: sqlite3.Connection, item: records.ItemNumber) -> bool:
    """Whether a newer run of the check run `item` names is observed on its PR: a run of its name, numbered after it.

    Returns:
        True once one is.
    """
    if item.kind is not NumberedItem.CHECK_RUN:
        return False
    runs: Sequence[tuple[str, int | None, int | None]] = [
        (str(r[0]), r[1], r[2])
        for table in (
            sql.select("name, run_id, number").from_("observed_check_runs").where("pr_url = ?", item.subject),
            sql.select("name, run_id, number").from_("observed_checks").where("pr_url = ?", item.subject),
        )
        for r in sql.execute(conn, table)
    ]
    names = {name for name, run_id, _ in runs if str(run_id) == item.id}
    return any(name in names and number is not None and number > item.number for name, _, number in runs)
