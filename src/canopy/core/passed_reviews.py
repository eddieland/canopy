"""Feedback a unit's `review` cursor passed with no worker sent to it, and why (DESIGN §7).

The overseer names each feedback item its `ticket-set` moves the cursor past, with a reason (`loop.claims` checks the
names against what the connectors observed); the harness names one on a resolved thread. Recorded here once the move is,
so "seen, and chosen not to act on" is in the journal beside the cursor, not only in a decision's rationale.

What `canopy show` and the attention list read (`left`) is each such item still left: not on a thread resolved since,
nor answered on it since by a worker or the operator through canopy. An item the reader no longer sees, deleted on
GitHub, is no longer left either, nor one on a PR none of the ticket's units has any more, as after a forget. The
operator overrules the call with `send`: a reply on the ticket naming the items, which the next tick reads as their
go-ahead, as `canopy send review:ID` is for a review run's findings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import conversation, db, item_numbers, records, sql
from canopy.core.vocab import Decider, PassReason, ReviewItem

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable, Mapping, Sequence

    from canopy.core.config import Trust


@dataclass(frozen=True)
class Passed:
    """A feedback item a `review` cursor passes with no worker sent to it: which, why, and on whose word."""

    item: records.ObservedReview
    reason: PassReason
    decider: Decider


@dataclass(frozen=True)
class Left(records.View):
    """Feedback passed with no worker that is still left, with what the reader last saw of it."""

    pr_url: str
    repo: str | None
    item: ReviewItem
    #: GitHub's id for it.
    id: int
    #: Its journal number.
    number: int
    reason: PassReason
    decider: Decider
    #: The tick whose cursor move passed it.
    tick_id: int
    author: str | None
    #: Where a review comment is: its file and line; None for a review, or a comment on no line.
    path: str | None
    line: int | None
    url: str | None


def left(
    conn: sqlite3.Connection,
    trust: Trust,
    sent: Mapping[str, Mapping[str, Collection[int]]],
    keys: Collection[str],
) -> dict[str, list[Left]]:
    """The feedback passed with no worker on each of `keys`' units that is still left.

    A worker's reply is known by `trust`'s marks, and one the operator sent through canopy by its id among `sent`, as
    `runs.drafts.sent_by_pr` reads them.

    Returns:
        Each ticket's, by key, oldest first; a ticket with none is not in it.
    """
    query = (
        sql.select(
            "p.ticket_key, p.pr_url, p.repo, p.item, p.id, p.number, p.reason, p.decider, p.tick_id, r.author, r.path, "
            "r.line, r.url, r.thread_id, r.resolved",
        )
        .from_("passed_reviews p")
        .join("observed_reviews r ON r.pr_url = p.pr_url AND r.item = p.item AND r.id = p.id")
        # Only a PR one of the ticket's units still has: a forget drops its PRs, and what was left on them with it.
        .join("ticket_units u ON u.ticket_key = p.ticket_key AND u.pr_url = p.pr_url")
        .where_in("p.ticket_key", sorted(keys))
        .order_by("p.number")
    )
    rows = records.fetch_all(conn, _Read, query)
    answered = _answered(conn, trust, sent, {r.pr_url for r in rows})
    found: dict[str, list[Left]] = {}
    for r in rows:
        replies = answered.get((r.pr_url, r.thread_id), []) if r.thread_id is not None else []
        if r.resolved or any(item_numbers.newer(n, r.number) for n in replies):
            continue
        found.setdefault(r.ticket_key, []).append(
            Left(
                pr_url=r.pr_url,
                repo=r.repo,
                item=r.item,
                id=r.id,
                number=r.number,
                reason=r.reason,
                decider=r.decider,
                tick_id=r.tick_id,
                author=r.author,
                path=r.path,
                line=r.line,
                url=r.url,
            ),
        )
    return found


def summary(items: Sequence[Left]) -> str:
    """Say how many feedback items are left with no worker, and why, as an attention item's detail ends.

    Returns:
        Such as `2 feedback items left with no worker (optional, would_reset_approval)`.
    """
    reasons = ", ".join(dict.fromkeys(i.reason.value for i in items))
    noun = "feedback item" if len(items) == 1 else "feedback items"
    return f"{len(items)} {noun} left with no worker ({reasons})"


def send(
    conn: sqlite3.Connection,
    trust: Trust,
    sent: Mapping[str, Mapping[str, Collection[int]]],
    key: str,
    numbers: Collection[int],
    *,
    channel: str,
) -> conversation.Sent:
    """Send feedback on ticket `key`'s PRs that is left with no worker to one: the operator's go-ahead, as a reply.

    The message names each item by GitHub's id, its PR, and where it is, never quoting it: the item is the reviewer's
    text, and the message the operator's. The next tick reads it as their go-ahead (DESIGN §7, D089), and a worker
    addresses the items it names, whoever wrote them. Each stays left until it is answered on its thread or resolved.

    Returns:
        The ticket, and the reply it recorded.

    Raises:
        conversation.Refused: `bad_reference` for no numbers, or one that is not of feedback left on `key`, which
            `left` reads with `trust` and `sent`; as `reply`, `unknown` for a ticket canopy has no record of.
    """
    wanted = sorted(set(numbers))
    if not wanted:
        raise conversation.Refused("bad_reference", "name one or more items by number, as `canopy show` lists them")
    found = {p.number: p for p in left(conn, trust, sent, [key]).get(key, [])}
    if missing := [n for n in wanted if n not in found]:
        raise conversation.Refused(
            "bad_reference",
            f"{key} has no feedback left with no worker numbered {', '.join(map(str, missing))}: `canopy show {key}` "
            "lists what is",
        )
    items = [found[n] for n in wanted]
    named = "; ".join(_named(p) for p in items)
    noun = "this review item" if len(items) == 1 else "these review items"
    body = f"Address {noun}, which the loop left with no worker: {named}."
    replied = conversation.reply(conn, conversation.Ref(conversation.TICKET, key), body, channel=channel)
    return conversation.Sent(ticket=key, replied=replied)


def record(conn: sqlite3.Connection, tick_id: int, key: str, repo: str | None, passed: Iterable[Passed]) -> None:
    """Record each of `passed`, of ticket `key`'s unit in `repo`, as passed in tick `tick_id`.

    One passed before, after a forget moved its cursor back, takes its newest reason. Call inside the transaction that
    moves the cursor.
    """
    now = db.now()
    for p in passed:
        number = p.item.number
        if number is None:
            # The journal numbers every item it observes; one without could not have been named, nor passed.
            continue
        records.insert(
            records.PassedReview,
            pr_url=p.item.pr_url,
            item=p.item.item,
            id=p.item.id,
            number=number,
            ticket_key=key,
            repo=repo,
            tick_id=tick_id,
            reason=p.reason,
            decider=p.decider,
            passed_at=now,
        ).or_replace().run(conn)


def _named(item: Left) -> str:
    """Name a left item for a worker, as `send` writes it: by id, PR, place, author, and why it was left.

    Returns:
        Such as `review comment 4443461025 by mgilson on https://github.com/o/r/pull/7 at s3_backfill.py:378 (left
        as optional)`.
    """
    what = "review comment" if item.item is ReviewItem.COMMENT else "review"
    where = f" at {item.path}:{item.line}" if item.path is not None and item.line is not None else ""
    return f"{what} {item.id} by {item.author or 'unknown'} on {item.pr_url}{where} (left as {item.reason.value})"


@dataclass(frozen=True)
class _Read(records.View):
    """A passed item as `left` reads it, with its thread and whether it is resolved."""

    ticket_key: str
    pr_url: str
    repo: str | None
    item: ReviewItem
    id: int
    number: int
    reason: PassReason
    decider: Decider
    tick_id: int
    author: str | None
    path: str | None
    line: int | None
    url: str | None
    thread_id: str | None
    resolved: bool | None


def _answered(
    conn: sqlite3.Connection,
    trust: Trust,
    sent: Mapping[str, Mapping[str, Collection[int]]],
    urls: Collection[str],
) -> Mapping[tuple[str, str], list[int]]:
    """The journal numbers of the replies a worker, or the operator through canopy, made on each thread of `urls`.

    Returns:
        Each thread's, by its PR's URL and its id.
    """
    if not urls:
        return {}
    query = (
        records.select(records.ObservedReview).where_in("pr_url", sorted(urls)).where("item = ?", ReviewItem.COMMENT)
    )
    found: dict[tuple[str, str], list[int]] = {}
    for r in query.all(conn):
        if r.thread_id is None or r.number is None:
            continue
        marked = conversation.worker_marked(r.body, trust.comment_prefix, trust.comment_suffix)
        if marked or r.id in sent.get(r.pr_url, {}).get("comments", ()):
            found.setdefault((r.pr_url, r.thread_id), []).append(r.number)
    return found
