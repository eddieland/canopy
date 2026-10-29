"""The operator's comments on a ticket's plan (DESIGN §25, Commenting on a plan): threads on passages, and replies.

A thread belongs to the ticket, not to one plan, so it carries from plan to plan, and the web UI's editor anchors it
again on each by its passage's words: the quote, and up to 32 characters either side, whitespace collapsed, never a
position. Open threads become one operator message when the operator asks for changes, through `canopy reply`'s code;
nothing here sends anything. Only the web channel writes threads, behind its token (TRUST_MODEL T8), and each write
refuses inside canopy's own runs, as every operator verb does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import conversation, db, records
from canopy.core.conversation import Refused

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

# A comment or a reply has a reply's bound (DESIGN §22), as the UI's `MAX_COMMENT` does.
MAX_BODY = conversation.MAX_OPERATOR
# A passage may be a whole section of a plan; the text either side is the UI's `CONTEXT`.
MAX_QUOTE = 4000
MAX_CONTEXT = 32


@dataclass(frozen=True)
class Thread:
    """A comment on a passage of the ticket's plan, with its replies, oldest first."""

    thread: records.PlanThread
    replies: Sequence[records.PlanReply]


def threads(conn: sqlite3.Connection, key: str) -> list[Thread]:
    """Every thread on the ticket's plans, open and resolved, oldest first, each with its replies.

    Returns:
        The threads, in the order they were written.
    """
    found = records.select(records.PlanThread).where("ticket_key = ?", key).order_by("id").all(conn)
    replies = (
        records.select(records.PlanReply, "r")
        .join("plan_threads t ON t.id = r.thread_id")
        .where("t.ticket_key = ?", key)
        .order_by("r.id")
        .all(conn)
    )
    return [Thread(t, [r for r in replies if r.thread_id == t.id]) for t in found]


def add(conn: sqlite3.Connection, key: str, *, quote: str, prefix: str, suffix: str, body: str) -> Thread:
    """Comment on a passage of the ticket's plan: a new open thread.

    Returns:
        The thread, with no replies.

    Raises:
        Refused: `inside_run` inside one of canopy's own runs, `unknown` for a ticket canopy has no record of,
            `bad_anchor` for an empty passage or one, or the text either side, over its bound, and `bad_body` for an
            empty comment or one over 4000 characters.
    """
    conversation.check_operator()
    _check_anchor(quote, prefix, suffix)
    text = _body(body)
    with db.transaction(conn):
        if db.get_ticket(conn, key) is None:
            raise Refused("unknown", f"canopy has no record of {key}")
        [thread] = records.insert(
            records.PlanThread,
            ticket_key=key,
            quote=quote,
            prefix=prefix,
            suffix=suffix,
            body=text,
            created_at=db.now(),
        ).returned(conn)
    return Thread(thread, ())


def reply(conn: sqlite3.Connection, key: str, thread_id: int, body: str) -> records.PlanReply:
    """Reply in one of the ticket's threads.

    Returns:
        The reply.

    Raises:
        Refused: `inside_run`, `unknown` for a thread the ticket does not have, `bad_body` as for a comment.
    """
    conversation.check_operator()
    text = _body(body)
    with db.transaction(conn):
        _thread(conn, key, thread_id)
        [found] = records.insert(records.PlanReply, thread_id=thread_id, body=text, created_at=db.now()).returned(conn)
    return found


def change(
    conn: sqlite3.Connection,
    key: str,
    thread_id: int,
    *,
    body: str | None = None,
    reply_id: int | None = None,
    resolved: bool | None = None,
    anchor: tuple[str, str, str] | None = None,
) -> Thread:
    """Change one of the ticket's threads: its comment's words, or with `reply_id` a reply's, or whether it is resolved.

    `anchor`, the passage's quote and the text either side, moves the thread to its passage's words as they stand after
    the operator's edit of the plan, which the web UI's editor saves with it.

    Nothing marks a comment edited: the journal keeps its body alone, and only the operator writes there.

    Returns:
        The thread as it now stands, with its replies.

    Raises:
        Refused: `inside_run`, `unknown` for a thread or reply the ticket does not have, `bad_body` as for a comment,
            or for a reply named with no words to give it, and `bad_anchor` as for a comment.
    """
    conversation.check_operator()
    if anchor is not None:
        _check_anchor(*anchor)
    if reply_id is not None and body is None:
        raise Refused("bad_body", f"name the words for reply {reply_id}, or leave out the reply")
    text = _body(body) if body is not None else None
    with db.transaction(conn):
        _thread(conn, key, thread_id)
        if text is not None and reply_id is not None:
            changed = (
                records.update(records.PlanReply)
                .set(body=text)
                .where("id = ? AND thread_id = ?", reply_id, thread_id)
                .run(conn)
                .rowcount
            )
            if not changed:
                raise Refused("unknown", f"thread {thread_id} of {key} has no reply {reply_id}")
        elif text is not None:
            records.update(records.PlanThread).set(body=text).where("id = ?", thread_id).run(conn)
        if anchor is not None:
            quote, prefix, suffix = anchor
            moved = records.update(records.PlanThread).set(quote=quote, prefix=prefix, suffix=suffix)
            moved.where("id = ?", thread_id).run(conn)
        if resolved is not None:
            # Resolving it again keeps when it was first resolved.
            resolving = records.update(records.PlanThread).set_to(
                "resolved_at = CASE WHEN ? THEN coalesce(resolved_at, ?) END",
                resolved,
                db.now(),
            )
            resolving.where("id = ?", thread_id).run(conn)
    [found] = [t for t in threads(conn, key) if t.thread.id == thread_id]
    return found


def delete(conn: sqlite3.Connection, key: str, thread_id: int) -> None:
    """Delete one of the ticket's threads and its replies.

    Raises:
        Refused: `inside_run`, `unknown` for a thread the ticket does not have.
    """
    conversation.check_operator()
    with db.transaction(conn):
        _thread(conn, key, thread_id)
        records.delete(records.PlanReply).where("thread_id = ?", thread_id).run(conn)
        records.delete(records.PlanThread).where("id = ?", thread_id).run(conn)


def _thread(conn: sqlite3.Connection, key: str, thread_id: int) -> records.PlanThread:
    """The thread `thread_id`, refused unless it is the ticket's: a path names both.

    Returns:
        The thread's row.

    Raises:
        Refused: (`unknown`) the ticket has no such thread.
    """
    found = records.select(records.PlanThread).where("id = ? AND ticket_key = ?", thread_id, key).one(conn)
    if found is None:
        raise Refused("unknown", f"{key} has no plan comment {thread_id}")
    return found


def _check_anchor(quote: str, prefix: str, suffix: str) -> None:
    """Refuse a passage no comment can be on.

    Raises:
        Refused: (`bad_anchor`) the passage is empty or over its bound, or the text either side is over its.
    """
    if not quote.strip() or len(quote) > MAX_QUOTE:
        raise Refused("bad_anchor", f"a comment's passage is 1 to {MAX_QUOTE} characters")
    if len(prefix) > MAX_CONTEXT or len(suffix) > MAX_CONTEXT:
        raise Refused("bad_anchor", f"the text either side of a passage is at most {MAX_CONTEXT} characters")


def _body(body: str) -> str:
    """A comment's or a reply's words, trimmed, refused as a reply's are.

    Returns:
        The words, trimmed of whitespace at either end.

    Raises:
        Refused: (`bad_body`) it is empty, or over 4000 characters.
    """
    text = body.strip()
    if not text:
        raise Refused("bad_body", "the comment is empty")
    if len(text) > MAX_BODY:
        raise Refused("bad_body", f"the comment is {len(text)} characters; the most is {MAX_BODY}")
    return text
