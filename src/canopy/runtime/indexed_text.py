"""What an index of the text of every session the runtime keeps reads (ROADMAP M72, stage 2).

The index (`canopy.core.session_index`) reads each session twice over: its head, a page at a time, in the order of its
update after a cursor, or newest first before one, and then the text of its messages, each part with its message, so a
hit names the message that held the words. A snippet reads that message again, from the record that keeps it, and the
index drops the sessions the record no longer keeps by every session's id. What the record is, and how its text is taken
apart, is the implementation's (D009); one whose text has no reader says why (`unindexed`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import one, pick, two

if TYPE_CHECKING:
    from canopy.runtime.implementation import Version
    from canopy.runtime.report import HeadPage, KeptIds, MessageText, SessionCursor, SessionHead, SessionTexts


def unindexed(*, version: Version) -> str | None:
    """Say why the text of the runtime `version` runs cannot be indexed, if it cannot.

    Returns:
        Why, in canopy's words; None when it can.
    """
    return pick(version, one.indexed_text, two.indexed_text).unindexed()


def heads(cursor: SessionCursor | None, *, newest_first: bool, limit: int, version: Version) -> HeadPage:
    """Read the sessions updated after `cursor`, or, `newest_first`, before it; with none, from the first or newest.

    Returns:
        At most `limit` rows, in the order read, each the session or None for one canopy cannot read; `missing` when the
        runtime keeps no session yet; `failed`, with why, when its record could not be read.
    """
    return pick(version, one.indexed_text, two.indexed_text).heads(cursor, newest_first=newest_first, limit=limit)


def texts(head: SessionHead, *, max_messages: int, max_chars: int, max_total: int, version: Version) -> SessionTexts:
    """Read the text of session `head`'s first `max_messages` messages, parts cut to `max_chars`, `max_total` in all.

    Returns:
        Each part, in the order of the messages, and whether the session held more; `missing` when its record no
        longer keeps it; `failed` when the record could not be read.
    """
    implementation = pick(version, one.indexed_text, two.indexed_text)
    return implementation.texts(head, max_messages=max_messages, max_chars=max_chars, max_total=max_total)


def message(
    record: str,
    session: str,
    message_id: str,
    *,
    max_chars: int,
    version: Version,
) -> list[MessageText] | None:
    """Read one message of session `session` again, from the record `record` names, each part cut to `max_chars`.

    Returns:
        Its parts; None when the record no longer keeps it, or could not be read.
    """
    implementation = pick(version, one.indexed_text, two.indexed_text)
    return implementation.message(record, session, message_id, max_chars=max_chars)


def kept(*, version: Version) -> KeptIds:
    """Read every session's id, by the record that keeps it.

    Returns:
        Each record's sessions, and the records that could not be read; `missing` when the runtime keeps no session
        yet; `failed` when its record could not be read.
    """
    return pick(version, one.indexed_text, two.indexed_text).kept()
