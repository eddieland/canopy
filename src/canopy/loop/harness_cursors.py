"""The harness moves cursors past what needs no handling, and past what its own decisions handle (DESIGN §37, M38).

A worker's comment, one carrying the workers' marks (D069), and a reply the operator sent through canopy (DESIGN §29)
are never feedback, a reply, or a reason to dispatch, so nobody handles them. Each live tick, after the connectors and
before the derivation, the harness moves a ticket's `comment` cursor and each unit's `review` cursor across the run of
such items directly after it, in journal-number order (§35), and stops at the first item that is anything else: a
person's comment, a review or review comment, a canopy review run. So a cursor never passes an item that needs
handling, never moves back, and stops lagging behind items nobody reads, which the block shows no more.

Only a cursor over items the state block shows fresh moves: a fresh candidate's comments, and the reviews of a unit
whose PR is observed fresh, on any ticket but a fresh non-candidate, which the block shows by key alone. A stale or
unobserved subject keeps its cursors for the overseer, and a private ticket's move as a public one's, since what an
item is does not hang on what authorizes the ticket's runs. A reply the operator sent is one on a PR
(`drafts.sent_by_pr`); a ticket's draft the operator sent is a tracker comment in their name, left to the overseer. An
empty review that only holds comments that need no handling, as GitHub wraps a reply on a thread, needs none either.

A `resume` the harness makes handles the items its reasons' cursors pass, as the overseer's does: once its worker
starts, it moves them to its default cursors (`claims.default_cursors`), which stop short of the first item the
dispatch may not cover, through `handled` (`loop.harness_dispatches`). The harness's other decisions handle no item: a
`wait` leaves what came meanwhile new for the next run.

Each move is the harness's decision, `harness.CURSOR_ACTION`, marked as its own, so `canopy decisions` shows who moved
it, from where to where, and past what or for which run. It decides nothing about the ticket: one past what needs no
handling leaves the ticket the overseer's. A dry run moves nothing (D036).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple

from canopy.core import conversation, db, item_numbers, records, sql
from canopy.core.vocab import Decider, ReviewItem, ReviewState
from canopy.loop import harness, observations
from canopy.runs import drafts

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Set as AbstractSet
    from datetime import datetime

    from canopy.core.config import Trust
    from canopy.core.context import Context

#: How many items a move's rationale names before it counts the rest.
NAMED = 5
#: What a move past items that need no handling says of them.
NEEDS_NO_HANDLING = "past what needs no handling"
#: A cursor the harness moves: the ticket's `comment` or `message` cursor, or a unit's `review` or `ci` cursor.
type Cursor = Literal["comment", "message", "review", "ci"]


@dataclass(frozen=True)
class Move:
    """A cursor the harness moves past what needs no handling: whose, from where, to where, and past what."""

    key: str
    #: The unit's repository for its `review` cursor; None for the ticket's `comment` cursor.
    repo: str | None
    #: Which cursor.
    name: Cursor
    #: Where it was: a journal number, or None when it was unset.
    before: int | None
    #: Where it goes: the number of the last item it passes.
    after: int
    #: What it passes, each named, oldest first; empty when a run of the harness's handles it, named in `why`.
    passed: Sequence[str]
    #: Why it moves: past what needs no handling, or the harness's run that handles what it passes.
    why: str = NEEDS_NO_HANDLING

    def rationale(self) -> str:
        """Say what the move did, for the decision recording it.

        Returns:
            The cursor, from and to, why, and what it passed.
        """
        whose = "" if self.repo is None else f" in {self.repo}"
        before = "unset" if self.before is None else self.before
        said = f"{self.name} cursor{whose} from {before} to {self.after}, {self.why}"
        if not self.passed:
            return said
        named = ", ".join(self.passed[:NAMED])
        more = len(self.passed) - NAMED
        if more > 0:
            named += f" and {more} more"
        return f"{said}: {named}"


def moves(ctx: Context, now: datetime) -> list[Move]:
    """The cursors to move past what needs no handling, as the observations stand at `now`.

    Returns:
        A move per cursor with such items directly after it, by ticket and then unit; none for one without.
    """
    conn = ctx.conn
    stopped = set(conversation.stopped(conn))
    tickets = [t for t in db.open_tickets(conn) if t.key not in stopped]
    reader = observations.Reader.read(ctx, (), now, tickets)
    sent = drafts.sent_by_pr(conn)
    found: list[Move] = []
    for ticket in tickets:
        seen = reader.ticket(ticket.key)
        if seen["observed"] == "fresh" and seen.get("candidate"):
            items = [_Item(c.number, _worker_comment(c)) for c in reader.comments.get(ticket.key, [])]
            found.extend(_move(ticket.key, None, "comment", ticket.comment_cursor, items))
        units = {u.repo: u for u in reader.units_of.get(ticket.key, []) if u.repo is not None}
        for shown in seen.get("units", []):
            unit = units.get(shown["repo"])
            pr = shown.get("pr")
            if unit is None or pr is None or shown["observed"] != "fresh":
                continue
            items = _review_items(conn, ctx.config.trust, pr["url"], reader.reviews.get(pr["url"], []), sent)
            found.extend(_move(ticket.key, shown["repo"], "review", unit.review_cursor, items))
    return found


def record(conn: sqlite3.Connection, tick_id: int, found: Iterable[Move]) -> list[Move]:
    """Move each cursor of `found` in tick `tick_id`, recording each as the harness's decision, in one transaction.

    A cursor already at or past where a move takes it stays where it is, so none moves back.

    Returns:
        The moves made, in order.
    """
    made: list[Move] = []
    with db.transaction(conn):
        for move in found:
            if _moved(move).run(conn).rowcount:
                db.record_decision(
                    conn,
                    tick_id,
                    move.key,
                    harness.CURSOR_ACTION,
                    move.rationale(),
                    repo=move.repo,
                    decider=Decider.HARNESS,
                )
                made.append(move)
    return made


def handled(conn: sqlite3.Connection, key: str, repo: str, cursors: Mapping[str, str], why: str) -> list[Move]:
    """The moves of ticket `key`'s cursors, and its unit's in `repo`, to `cursors`: what a run of the harness's handles.

    `cursors` are by name, each a journal number or message id, as `claims.default_cursors` gives them; `why` names the
    run. A cursor already at or past where a move takes it is left to `record`, which moves none back.

    Returns:
        A move per cursor, ticket's then unit's, as `cursors` orders them.

    Raises:
        ValueError: A name in `cursors` is no cursor.
    """
    ticket = db.get_ticket(conn, key)
    unit = next((u for u in db.units(conn, key) if u.repo == repo), None)
    found: list[Move] = []
    for name, value in cursors.items():
        cursor, before = _now_at(name, ticket, unit)
        found.append(Move(key, repo if name in db.UNIT_CURSORS else None, cursor, before, int(value), (), why))
    return found


class _Item(NamedTuple):
    """An item a cursor may pass: its journal number, and what it is when it needs no handling, else None."""

    number: int | None
    passes: str | None


def _move(
    key: str,
    repo: str | None,
    name: Cursor,
    cursor: int | None,
    items: Iterable[_Item],
) -> list[Move]:
    """The move of a cursor at `cursor` across the items after it that need no handling, up to the first that does.

    An item with no number is new past any cursor (`item_numbers.newer`), so no move passes it, nor stops at it.

    Returns:
        One move, or none when the first item after the cursor needs handling or none comes after it.
    """
    numbered = sorted((i for i in items if i.number is not None), key=lambda i: i.number or 0)
    after: int | None = None
    passed: list[str] = []
    for item in numbered:
        if not item_numbers.newer(item.number, cursor):
            continue
        if item.passes is None:
            break
        after = item.number
        passed.append(item.passes)
    if after is None:
        return []
    return [Move(key, repo, name, cursor, after, tuple(passed))]


def _worker_comment(comment: records.ObservedComment) -> str | None:
    """Name a tracker comment that carries the workers' marks, as its source recorded it (D069).

    Returns:
        What it is, or None for anyone else's.
    """
    return f"worker comment {comment.id}" if comment.source == "worker" else None


def _review_items(
    conn: sqlite3.Connection,
    trust: Trust,
    url: str,
    reviews: Sequence[records.ObservedReview],
    sent: Mapping[str, Mapping[str, Sequence[int]]],
) -> list[_Item]:
    """Every numbered item the `review` cursor of the PR at `url` passes: its reviews, review comments, and review runs.

    A review run of canopy's, each of its revisions included, always needs handling here.

    Returns:
        The items, in no order.
    """
    mine = sent.get(url, {})
    comments, reviewed = frozenset(mine.get("comments", ())), frozenset(mine.get("reviews", ()))
    named = {(r.item, r.id): _needs_none(r, trust, comments, reviewed) for r in reviews}
    found = [_Item(r.number, named[r.item, r.id] or _wrapper(r, reviews, named)) for r in reviews]
    runs = sql.select("number").from_("review_runs").where("pr_url = ? AND number IS NOT NULL", url)
    found.extend(_Item(int(row[0]), None) for row in sql.execute(conn, runs))
    return found


def _needs_none(
    review: records.ObservedReview,
    trust: Trust,
    comments: AbstractSet[int],
    reviewed: AbstractSet[int],
) -> str | None:
    """Name a review item that needs no handling: one the operator sent through canopy, or a worker's.

    Returns:
        What it is, or None when it is anything else.
    """
    what = "review comment" if review.item is ReviewItem.COMMENT else "review"
    sent = comments if review.item is ReviewItem.COMMENT else reviewed
    if review.id in sent:
        return f"{what} {review.id} the operator sent"
    if conversation.worker_marked(review.body, trust.comment_prefix, trust.comment_suffix):
        return f"worker {what} {review.id}"
    return None


def _wrapper(
    review: records.ObservedReview,
    reviews: Iterable[records.ObservedReview],
    named: Mapping[tuple[ReviewItem, int], str | None],
) -> str | None:
    """Name an empty review that holds only comments that need no handling, as GitHub wraps a reply on a thread.

    Returns:
        What it is, or None for any other review or review comment.
    """
    if review.item is not ReviewItem.REVIEW or review.state is not ReviewState.COMMENTED or review.body.strip():
        return None
    held = [named[r.item, r.id] for r in reviews if r.item is ReviewItem.COMMENT and r.review_id == review.id]
    if not held or any(h is None for h in held):
        return None
    return f"review {review.id}, holding only those"


def _now_at(
    name: str,
    ticket: records.Ticket | None,
    unit: records.TicketUnit | None,
) -> tuple[Cursor, int | None]:
    """The cursor `name`, and where it is now: on `ticket` for a ticket's, on `unit` for a unit's.

    Returns:
        The cursor, and its value, None when unset or its ticket or unit has no row yet.

    Raises:
        ValueError: `name` is no cursor.
    """
    match name:
        case "comment":
            return "comment", None if ticket is None else ticket.comment_cursor
        case "message":
            return "message", None if ticket is None else ticket.last_message_id
        case "review":
            return "review", None if unit is None else unit.review_cursor
        case "ci":
            return "ci", None if unit is None else unit.ci_cursor
        case _:
            raise ValueError(f"no cursor {name!r}")


def _moved(move: Move) -> records.Update[records.Ticket] | records.Update[records.TicketUnit]:
    """The update that moves `move`'s cursor.

    Returns:
        It, which moves the cursor only forward.
    """
    if move.repo is None:
        column = sql.name(db.TICKET_CURSORS[move.name])
        return (
            records.update(records.Ticket)
            .set_to("{} = ?", column, move.after)
            .where("key = ? AND ({} IS NULL OR {} < ?)", move.key, column, column, move.after)
        )
    column = sql.name(db.UNIT_CURSORS[move.name])
    return (
        records.update(records.TicketUnit)
        .set_to("{} = ?", column, move.after)
        .where(
            "ticket_key = ? AND repo = ? AND ({} IS NULL OR {} < ?)",
            move.key,
            move.repo,
            column,
            column,
            move.after,
        )
    )
