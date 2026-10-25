"""What a tick did about the operator's messages, said in each ticket's conversation (DESIGN §22, Messages).

The first `ok` tick to read an operator message on a ticket records a note there, in canopy's words: what it decided
about the ticket, each decision with its reason, but a cursor the harness moved past what needs no handling. Without
it, a message the overseer handled by waiting, or could not act on yet, stays the last word in the conversation until a
run ends, with nothing saying it was read.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from canopy.core import conversation, db, sql
from canopy.core.items import one_line
from canopy.loop import harness

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

    from canopy.core import records

#: The most characters of one decision's reason a note carries; the tick's page has it whole.
MAX_REASON = 300
# What a note says the overseer's own decisions did (`canopy decide`).
_SAID: Mapping[str, str] = {"wait": "waiting", "done": "done", "skip": "skipped"}
# A dispatch's rationale is canopy's own, and starts with the run it started (`canopy dispatch`).
_STARTED = re.compile(r"run (\d+):")


def note(conn: sqlite3.Connection, tick_id: int) -> dict[str, int]:
    """Record a note on each ticket whose operator messages tick `tick_id` is the first `ok` tick to read.

    Call it in the transaction that closes the tick `ok`, and never for a dry run, which starts nothing. The messages
    it read past what the live `ok` tick before it read are the ones no note answers yet. Each note answers the
    newest of its ticket's, and says what this tick decided about the ticket.

    Returns:
        The id of each note recorded, by ticket key.
    """
    tick = db.get_tick(conn, tick_id)
    if tick is None or tick.message_id is None:
        return {}
    unanswered = (
        sql.select("id, subject_id")
        .from_("messages")
        .where(
            "subject_kind = ? AND source = 'operator' AND id > ? AND id <= ?",
            conversation.TICKET,
            _noted_up_to(conn, tick_id),
            tick.message_id,
        )
        .order_by("id")
    )
    rows = sql.execute(conn, unanswered).fetchall()
    read: defaultdict[str, list[int]] = defaultdict(list)
    for row in rows:
        read[str(row["subject_id"])].append(int(row["id"]))
    # A cursor the harness moved decided nothing about the ticket, so the note leaves it out.
    decisions = [d for d in db.decisions_for_tick(conn, tick_id) if d.action != harness.CURSOR_ACTION]
    return {
        key: conversation.note(
            conn,
            key,
            body(tick_id, key, ids, [d for d in decisions if d.ticket_key == key]),
            answers=ids[-1],
        )
        for key, ids in sorted(read.items())
    }


def _noted_up_to(conn: sqlite3.Connection, tick_id: int) -> int:
    # The newest message the live `ok` tick before this one read, which its notes answered for. A dry run's does not
    # count: it notes nothing, so what it read is still unanswered.
    noted = (
        sql.select("message_id")
        .from_("ticks")
        .where("status = 'ok' AND dry_run = 0 AND id < ? AND message_id IS NOT NULL", tick_id)
        .order_by("id DESC")
        .limit(1)
    )
    row = sql.execute(conn, noted).fetchone()
    return 0 if row is None else int(row[0])


def body(tick_id: int, key: str, read: Sequence[int], decisions: Sequence[records.Decision]) -> str:
    """What a note says: the tick, the messages it read, and what it decided about the ticket, in order.

    Returns:
        One sentence, `Tick 12 read message 40: started run 57 (resume).`, or that it decided nothing about `key`.
    """
    said = f"Tick {tick_id} read {_messages(read)}"
    did = [_decided(d) for d in decisions]
    if not did:
        return f"{said} and decided nothing about {key}."
    return f"{said}: {'; '.join(did)}."


def _messages(ids: Sequence[int]) -> str:
    if len(ids) == 1:
        return f"message {ids[0]}"
    return f"messages {', '.join(map(str, ids[:-1]))} and {ids[-1]}"


def _decided(decision: records.Decision) -> str:
    # What one decision did, in a few words, with its reason cut to MAX_REASON.
    family, _, detail = decision.action.partition(":")
    started = _STARTED.match(decision.rationale)
    if family == "dispatch" and started is not None:
        return f"started run {started.group(1)} ({detail})"
    match family:
        case "wait" | "done" | "skip":
            said = _SAID[family]
        case "refused":
            said = f"refused {detail}"
        case "attention":
            said = f"needs you ({detail})"
        case _:
            said = decision.action
    return f"{said}: {_reason(decision.rationale)}"


def _reason(rationale: str) -> str:
    # A reason on one line, cut to MAX_REASON, without the full stop the note's sentence ends with.
    text = one_line(conversation.printable(rationale)).rstrip(".")
    return text if len(text) <= MAX_REASON else f"{text[: MAX_REASON - 1]}…"
