"""Whose comment on an artifact counts (DESIGN §38, ROADMAP M62): decided in code, from what the store said of it.

A comment counts by the message the `artifacts` source recorded of it in its ticket's conversation, once, as first read
(`artifact_feed`), and by `artifacts.authorized_authors`, read as config says now, as a tracker comment's `authorized`
mark is read from `trust.authorized_repliers`: listing an author, or dropping one, changes how each of their comments
counts from the next read on. Each comment's standing:

- `agent`: the store marks it an agent's (`kind: agent`), written with a token on behalf of whoever minted it, or it
  carries every one of the workers' marks (D069), whoever wrote it. Never authority, and nothing waits on it.
- `authorized`: a person's whose store id the operator lists. On a public ticket it is authority, as an authorized
  reply is: the overseer is shown it with the ticket's operator messages, a `resume` for `reply` may cite it by its
  message's id, and the ticket's worker hears it with them. A private ticket's only authority is the operator (§22).
- `untrusted`: any other person's. It is data, and raises `untrusted_artifact_comment` about its ticket until the
  operator sends it on, in a reply on the ticket after it, as an untrusted reviewer's feedback waits (D089).

A comment deleted since it was recorded counts for nothing: its author took it back. On a private ticket every person's
comment is untrusted, listed or not, since none is authority there.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, assert_never

from canopy.core import conversation, db, records, sql
from canopy.core.vocab import AuthorKind, StartStatus
from canopy.infra.text import printable
from canopy.runs import artifact_feed

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Sequence
    from collections.abc import Set as AbstractSet

#: The attention item an untrusted comment raises, about its ticket (DESIGN §14, §38).
REASON = "untrusted_artifact_comment"
#: How many authors an item's detail names; the rest are counted.
MAX_NAMED = 5


class Standing(StrEnum):
    """What a comment on an artifact counts for, decided in code (DESIGN §38)."""

    #: A person's whose id `artifacts.authorized_authors` lists: authority on a public ticket.
    AUTHORIZED = "authorized"
    #: Any other person's: data, waiting on the operator to send it on.
    UNTRUSTED = "untrusted"
    #: An agent's, or one with every one of the workers' marks: never authority, and waiting on nobody.
    AGENT = "agent"


def standing(comment: records.ObservedArtifactComment, authors: AbstractSet[str]) -> Standing:
    """Decide what a comment counts for, from its author's store id, the kind the store gave it, and its marks.

    Returns:
        Its standing. The marks and the agent's kind only take authority away (D069), whoever the author is.
    """
    if comment.marked:
        return Standing.AGENT
    match comment.author_kind:
        case AuthorKind.PERSON:
            return Standing.AUTHORIZED if comment.author in authors else Standing.UNTRUSTED
        case AuthorKind.AGENT:
            return Standing.AGENT
        case _:
            assert_never(comment.author_kind)


def authorized(
    conn: sqlite3.Connection,
    key: str,
    authors: AbstractSet[str],
    *,
    after: int = 0,
) -> list[records.Message]:
    """The messages of public ticket `key`'s comments that are authority, newer than message `after` and any forget.

    Returns:
        The messages, oldest first; none for a private ticket, which only the operator's messages authorize (§22).
    """
    if not authors or db.get_start(conn, conversation.TICKET, key) is not None:
        return []
    since = max(after, db.forgotten_message_id(conn, key))
    return [said.message for said in _said(conn, key, since) if standing(said.comment, authors) is Standing.AUTHORIZED]


@dataclass(frozen=True)
class Item:
    """An `untrusted_artifact_comment` item: its ticket and its detail."""

    ticket_key: str
    detail: str


def untrusted(conn: sqlite3.Connection, authors: AbstractSet[str]) -> list[Item]:
    """Return an `untrusted_artifact_comment` item for each ticket whose untrusted comments wait on the operator.

    A comment waits from its message in the ticket's conversation until the operator's reply on the ticket after it,
    a verb's instruction not counting, as an untrusted reviewer's feedback waits (D089); until the operator forgets
    the ticket's work; or until the ticket is done or stopped, or the comment deleted. Each item names the comments'
    authors and the newest message, never a comment's text, which reaches the operator's sinks only through
    `canopy show`.

    Returns:
        One item per ticket, by key.
    """
    query = (
        sql.select("m.*")
        .from_("observed_artifact_comments o")
        .join("observed_artifact_threads t ON t.id = o.thread_id")
        .join(
            "messages m ON m.subject_kind = ? AND m.subject_id = t.ticket AND m.comment_id = ? || o.id",
            conversation.TICKET,
            artifact_feed.COMMENT_ID_PREFIX,
        )
        .join("tickets k ON k.key = m.subject_id")
        .where("k.done = 0 AND m.id > coalesce(k.forgotten_message_id, 0)")
        .where("o.author_kind = ? AND o.marked = 0 AND o.deleted_at IS NULL", AuthorKind.PERSON)
        .where(
            "NOT EXISTS (SELECT 1 FROM starts s WHERE s.subject_kind = m.subject_kind"
            " AND s.subject_id = m.subject_id AND s.status = ?)",
            StartStatus.STOPPED,
        )
        .order_by("m.subject_id, m.id")
    )
    messages = records.fetch_all(conn, records.Message, query)
    comments = _observed(conn, messages)
    waiting: defaultdict[str, list[records.Message]] = defaultdict(list)
    replied: dict[str, int] = {}
    for m in messages:
        comment = comments.get(m.comment_id or "")
        if comment is None or not _untrusted_on(conn, m.subject_id, comment, authors):
            continue
        if m.subject_id not in replied:
            replied[m.subject_id] = _last_reply(conn, m.subject_id)
        if m.id > replied[m.subject_id]:
            waiting[m.subject_id].append(m)
    return [
        Item(key, _detail(key, said, private=db.get_start(conn, conversation.TICKET, key) is not None))
        for key, said in sorted(waiting.items())
    ]


@dataclass(frozen=True)
class _Said:
    """A comment's message in its ticket's conversation, and the store's comment as the source last read it."""

    message: records.Message
    comment: records.ObservedArtifactComment


def _said(conn: sqlite3.Connection, key: str, after: int) -> list[_Said]:
    """Ticket `key`'s comments on artifacts newer than message `after`, each with its observation, deleted ones not.

    Returns:
        Each comment's message and observation, oldest first.
    """
    messages = records.fetch_all(
        conn,
        records.Message,
        sql.select("*")
        .from_("messages")
        .where("subject_kind = ? AND subject_id = ? AND id > ?", conversation.TICKET, key, after)
        .where("channel = ? AND comment_id IS NOT NULL", conversation.ARTIFACTS)
        .order_by("id"),
    )
    comments = _observed(conn, messages)
    return [
        _Said(m, comment)
        for m in messages
        if (comment := comments.get(m.comment_id or "")) is not None and comment.deleted_at is None
    ]


def _observed(
    conn: sqlite3.Connection,
    messages: Iterable[records.Message],
) -> dict[str, records.ObservedArtifactComment]:
    """The store's comments `messages` were recorded from, by the messages' comment ids.

    Returns:
        Each one found, by the id its message carries.
    """
    prefix = artifact_feed.COMMENT_ID_PREFIX
    ids = {m.comment_id.removeprefix(prefix) for m in messages if m.comment_id and m.comment_id.startswith(prefix)}
    if not ids:
        return {}
    found = records.fetch_all(
        conn,
        records.ObservedArtifactComment,
        sql.select("*").from_("observed_artifact_comments").where_in("id", sorted(ids)),
    )
    return {f"{prefix}{c.id}": c for c in found}


def _untrusted_on(
    conn: sqlite3.Connection,
    key: str,
    comment: records.ObservedArtifactComment,
    authors: AbstractSet[str],
) -> bool:
    """Whether a comment waits on the operator on ticket `key`: an untrusted one, or any person's on a private ticket.

    Returns:
        True if it raises the item.
    """
    match standing(comment, authors):
        case Standing.UNTRUSTED:
            return True
        case Standing.AUTHORIZED:
            return db.get_start(conn, conversation.TICKET, key) is not None
        case Standing.AGENT:
            return False
        case _ as unknown:
            assert_never(unknown)


def _last_reply(conn: sqlite3.Connection, key: str) -> int:
    """The id of the operator's latest reply on ticket `key`, a verb's instruction not counting, or 0.

    Returns:
        The message id.
    """
    after = db.forgotten_message_id(conn, key)
    replies = [
        m.id for m in conversation.operator_messages_after(conn, key, after) if conversation.answers_questions(m)
    ]
    return max(replies, default=0)


def _detail(key: str, said: Sequence[records.Message], *, private: bool) -> str:
    """An item's detail: how many comments wait, whose, why, the newest message, and how to send them on.

    Returns:
        The detail, naming no comment's text.
    """
    authors = list(dict.fromkeys(printable(m.author or "?") for m in said))
    named = ", ".join(authors[:MAX_NAMED])
    if len(authors) > MAX_NAMED:
        named += f" and {len(authors) - MAX_NAMED} more"
    count = f"{len(said)} comment{'' if len(said) == 1 else 's'}"
    # On a private ticket a listed author's comment waits too, since only the operator is authority there (§22).
    why = (
        "a private ticket, whose only authority is you"
        if private
        else "whom artifacts.authorized_authors does not list"
    )
    return (
        f"{count} on {key}'s artifacts by {named}, {why}, the newest message "
        f"{said[-1].id}: read them with `canopy show {key}`, and send on what a worker should act on with "
        f"`canopy reply {key}`"
    )
