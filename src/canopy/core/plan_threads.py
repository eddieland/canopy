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

# A comment or a reply has a reply's bound (DESIGN §22), as the UI's `MAX_COMMENT` does.
MAX_BODY = conversation.MAX_OPERATOR
# A passage may be a whole section of a plan; the text either side is the UI's `CONTEXT`.
MAX_QUOTE = 4000
MAX_CONTEXT = 32


@dataclass(frozen=True)
class Thread:
    """A comment on a passage of the ticket's plan, with its replies, oldest first."""

    thread: records.PlanThread
    replies: list[records.PlanReply]


def threads(conn: sqlite3.Connection, key: str) -> list[Thread]:
    """Every thread on the ticket's plans, open and resolved, oldest first, each with its replies.

    Returns:
        The threads, in the order they were written.
    """
    found = records.fetch_all(
        conn, records.PlanThread, "SELECT * FROM plan_threads WHERE ticket_key = ? ORDER BY id", (key,)
    )
    replies = records.fetch_all(
        conn,
        records.PlanReply,
        "SELECT r.* FROM plan_replies r JOIN plan_threads t ON t.id = r.thread_id WHERE t.ticket_key = ? ORDER BY r.id",
        (key,),
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
    if not quote.strip() or len(quote) > MAX_QUOTE:
        raise Refused("bad_anchor", f"a comment's passage is 1 to {MAX_QUOTE} characters")
    if len(prefix) > MAX_CONTEXT or len(suffix) > MAX_CONTEXT:
        raise Refused("bad_anchor", f"the text either side of a passage is at most {MAX_CONTEXT} characters")
    text = _body(body)
    with db.transaction(conn):
        if db.get_ticket(conn, key) is None:
            raise Refused("unknown", f"canopy has no record of {key}")
        [thread] = records.fetch_all(
            conn,
            records.PlanThread,
            "INSERT INTO plan_threads (ticket_key, quote, prefix, suffix, body, created_at) VALUES (?, ?, ?, ?, ?, ?) "
            "RETURNING *",
            (key, quote, prefix, suffix, text, db.now()),
        )
    return Thread(thread, [])


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
        [found] = records.fetch_all(
            conn,
            records.PlanReply,
            "INSERT INTO plan_replies (thread_id, body, created_at) VALUES (?, ?, ?) RETURNING *",
            (thread_id, text, db.now()),
        )
    return found


def change(
    conn: sqlite3.Connection,
    key: str,
    thread_id: int,
    *,
    body: str | None = None,
    reply_id: int | None = None,
    resolved: bool | None = None,
) -> Thread:
    """Change one of the ticket's threads: its comment's words, or with `reply_id` a reply's, or whether it is resolved.

    Nothing marks a comment edited: the journal keeps its body alone, and only the operator writes there.

    Returns:
        The thread as it now stands, with its replies.

    Raises:
        Refused: `inside_run`, `unknown` for a thread or reply the ticket does not have, `bad_body` as for a comment,
            or for a reply named with no words to give it.
    """
    conversation.check_operator()
    if reply_id is not None and body is None:
        raise Refused("bad_body", f"name the words for reply {reply_id}, or leave out the reply")
    text = _body(body) if body is not None else None
    with db.transaction(conn):
        _thread(conn, key, thread_id)
        if text is not None and reply_id is not None:
            changed = conn.execute(
                "UPDATE plan_replies SET body = ? WHERE id = ? AND thread_id = ?", (text, reply_id, thread_id)
            ).rowcount
            if not changed:
                raise Refused("unknown", f"thread {thread_id} of {key} has no reply {reply_id}")
        elif text is not None:
            conn.execute("UPDATE plan_threads SET body = ? WHERE id = ?", (text, thread_id))
        if resolved is not None:
            # Resolving it again keeps when it was first resolved.
            conn.execute(
                "UPDATE plan_threads SET resolved_at = CASE WHEN ? THEN coalesce(resolved_at, ?) END WHERE id = ?",
                (resolved, db.now(), thread_id),
            )
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
        conn.execute("DELETE FROM plan_replies WHERE thread_id = ?", (thread_id,))
        conn.execute("DELETE FROM plan_threads WHERE id = ?", (thread_id,))


def _thread(conn: sqlite3.Connection, key: str, thread_id: int) -> records.PlanThread:
    """The thread `thread_id`, refused unless it is the ticket's: a path names both.

    Returns:
        The thread's row.

    Raises:
        Refused: (`unknown`) the ticket has no such thread.
    """
    found = records.fetch_one(
        conn, records.PlanThread, "SELECT * FROM plan_threads WHERE id = ? AND ticket_key = ?", (thread_id, key)
    )
    if found is None:
        raise Refused("unknown", f"{key} has no plan comment {thread_id}")
    return found


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
