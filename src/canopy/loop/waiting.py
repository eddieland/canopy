"""What waits on the operator, and what happened since a time: the report a briefing reads (DESIGN §19, §20).

`canopy waiting` prints it, and an agent reads it through the tool of the same name, `canopy_reports_waiting`, which
`canopy _mcp --reports` serves beside the reports in `core.reports`. It is what a briefing chore words for the
operator: the attention list as the sinks hear of it, each open ticket's open PRs with the reviews on them and the
feedback no plan has handled yet, by who wrote it, and the digest's counts of what happened since `since`. It writes
nothing, and judges nothing: which of it matters is the briefing's to say.

What reviewers, the tracker, and agents wrote, a PR's title, a review's body, an item's detail, is data to whoever
reads it, cut and with its control characters dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import AfterValidator, Field, StrictStr

from canopy.core import db, outbox, records, reports
from canopy.core.items import age
from canopy.core.vocab import PrState, ReviewItem, ReviewState
from canopy.infra.text import printable
from canopy.loop import attention
from canopy.notify import message
from canopy.runs import feedback_items

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from canopy.core.context import Context
    from canopy.core.items import Item

#: How far back the report looks when the request names no time: a day.
DEFAULT_SINCE = timedelta(days=1)
#: How far back a request may look: as far as a report of days may (`spend.MAX_DAYS`).
MAX_SINCE = timedelta(days=366)
#: How many characters of a review's body the report carries: enough to say what was asked.
EXCERPT = 300
#: The most feedback items a PR lists, the newest; the rest it counts.
MAX_FEEDBACK = 20


def _moment(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"invalid time {value!r}: must be ISO 8601, such as 2026-11-13T09:00:00Z") from None
    if moment.tzinfo is None:
        raise ValueError(f"invalid time {value!r}: must name its time zone, such as Z for UTC")
    if datetime.now(UTC) - moment > MAX_SINCE:
        raise ValueError(f"invalid time {value!r}: must be within {MAX_SINCE.days} days")
    return db.format_time(moment)


class Waiting(reports.Request):
    """`waiting`: what waits on the operator, and what happened since a time."""

    #: What counts as new: the report marks what began at or after it, and counts what happened since.
    since: Annotated[
        Annotated[StrictStr, AfterValidator(_moment)] | None,
        Field(
            max_length=40,
            description=(
                "What counts as new, an ISO 8601 time with its zone, such as the previous run's ended_at; a day "
                "back when left out."
            ),
        ),
    ] = None


def read_waiting(ctx: Context, request: Waiting) -> str:
    """Report what waits on the operator, and what happened since `request.since`, as `canopy waiting` prints it.

    Returns:
        The report's JSON: `since`, the time it counts from; `attention`, the open list as the sinks hear of it, each
        item marked `new` when it began at or after `since`; `prs`, each open ticket's open PRs, with the latest review
        of each reviewer and the feedback no plan has handled; and `happened`, the digest's counts since `since`.
    """
    now = datetime.now(UTC)
    since = request.since or db.format_time(now - DEFAULT_SINCE)
    with db.read_snapshot(ctx.conn):
        items = attention.listed(ctx)
        titles = message.titles(ctx.conn)
        found = message.digest(ctx.conn, items, since=since, now=now, state_dir=ctx.state_dir).as_json()
        prs = _prs(ctx, titles, since)
    # Its time and its lines say again what the clock and its counts say, which the caller reads apart.
    happened = {k: v for k, v in found.items() if k not in {"until", "lines"}}
    return reports.report_json(
        {
            "since": since,
            "attention": [_item_json(i, titles, since, now) for i in items],
            "prs": prs,
            "happened": happened,
        },
    )


def _item_json(item: Item, titles: Mapping[str, str], since: str, now: datetime) -> dict[str, object]:
    return {
        "subject": item.subject,
        "ticket": item.ticket_key,
        "title": titles.get(item.ticket_key) if item.ticket_key else None,
        "repo": item.repo,
        "reason": item.reason,
        "finding": item.finding,
        "detail": printable(item.detail),
        "since": item.since,
        "waiting": age(item.since, now),
        "new": _at_or_after(item.since, since),
    }


def _prs(ctx: Context, titles: Mapping[str, str], since: str) -> list[dict[str, Any]]:
    """Each open ticket's open PRs, by ticket key, then repository.

    Returns:
        One object per PR the reader last saw open.
    """
    found: list[dict[str, Any]] = []
    for ticket in db.open_tickets(ctx.conn):
        urls = [u.pr_url for u in db.units(ctx.conn, ticket.key) if u.pr_url]
        observed = [pr for pr in (_observed(ctx, url) for url in urls) if pr is not None and pr.state is PrState.OPEN]
        if not observed:
            continue
        offered = feedback_items.offered(ctx.conn, ctx.config.trust, ticket.key, [pr.url for pr in observed])
        for pr in observed:
            mine = [o for o in offered if o.pr_url == pr.url]
            found.append(
                {
                    "ticket": ticket.key,
                    "title": titles.get(ticket.key),
                    "pr": pr.url,
                    "repository": pr.repository,
                    "number": pr.number,
                    "pr_title": printable(pr.title) if pr.title else None,
                    "author": pr.author,
                    "draft": pr.draft,
                    "mergeable_state": None if pr.mergeable_state is None else str(pr.mergeable_state),
                    "ready_at": pr.ready_at,
                    "review_requested_at": pr.review_requested_at,
                    "reviews": _latest_reviews(ctx, pr),
                    "feedback": [_feedback_json(o, since) for o in mine[-MAX_FEEDBACK:]],
                    "more_feedback": max(0, len(mine) - MAX_FEEDBACK),
                },
            )
    return found


def _observed(ctx: Context, url: str) -> records.ObservedPr | None:
    return records.select(records.ObservedPr).where("url = ?", url).one(ctx.conn)


def _latest_reviews(ctx: Context, pr: records.ObservedPr) -> list[dict[str, object]]:
    """Each reviewer's latest review of `pr` that says where they stand, oldest first: not the PR's author, nor a bot.

    Returns:
        Each one's author, state, and time.
    """
    rows = (
        records.select(records.ObservedReview)
        .where("pr_url = ?", pr.url)
        .where("item = ?", ReviewItem.REVIEW)
        .where("bot = 0")
        .where("state IS NOT NULL")
        .order_by("created_at, id")
        .all(ctx.conn)
    )
    latest: dict[str, records.ObservedReview] = {}
    for row in rows:
        if row.author is None or row.author == pr.author or row.state in (None, ReviewState.PENDING):
            continue
        # A review that only comments leaves the reviewer where their last approval or request for changes put them.
        if row.state is ReviewState.COMMENTED and row.author in latest:
            continue
        latest[row.author] = row
    return [
        {"author": r.author, "state": None if r.state is None else str(r.state), "at": r.created_at}
        for r in sorted(latest.values(), key=lambda r: (r.created_at or "", r.id))
    ]


def _feedback_json(item: feedback_items.Offered, since: str) -> dict[str, object]:
    return {
        "author": item.author,
        "pr_author": item.pr_author,
        "trusted": item.trusted,
        "bot": item.bot,
        "item": str(item.item),
        "state": None if item.state is None else str(item.state),
        "created_at": item.created_at,
        "new": item.created_at is not None and _at_or_after(item.created_at, since),
        "url": item.url,
        "path": item.path,
        "excerpt": outbox.cut(printable(item.body), EXCERPT),
        "replies": _replies(item.replies),
    }


def _replies(replies: Iterable[feedback_items.Offered]) -> list[dict[str, object]]:
    return [
        {
            "author": r.author,
            "pr_author": r.pr_author,
            "created_at": r.created_at,
            "excerpt": outbox.cut(printable(r.body), EXCERPT),
        }
        for r in replies
    ]


def _at_or_after(stamp: str, since: str) -> bool:
    return db.parse_time(stamp) >= db.parse_time(since)
