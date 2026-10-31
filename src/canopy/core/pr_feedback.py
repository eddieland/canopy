"""The feedback people left on PRs canopy observed (DESIGN §11, §29): what the reports count as review feedback.

Reads only. A comment, or a review that judged the PR, from someone other than the PR's author and not a bot. canopy
writes, replies, and reviews as the operator, who authors its PRs, so this is what other people said of the work. A PR
waits on a review from when one was first asked for once it was ready, or from when it was ready, on GitHub's clock as
the `vcs` source read it. The monthly report and the Reviews page both count feedback and its wait through here, so
they measure the same thing the same way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db, records, sql
from canopy.core.vocab import ReviewItem, ReviewState

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable
    from datetime import datetime

#: A review that judged the PR, as against one GitHub keeps while its author is still writing it, or one dismissed.
JUDGED = (ReviewState.APPROVED, ReviewState.CHANGES_REQUESTED, ReviewState.COMMENTED)


@dataclass(frozen=True)
class Feedback(records.View):
    """A comment or a review on a PR, from someone other than its author, not a bot's."""

    pr_url: str
    item: ReviewItem
    author: str | None
    #: A review's state, one of `JUDGED`; None for a comment.
    state: ReviewState | None
    #: When it was made, a journal time; None where the reader printed none.
    created_at: str | None

    @property
    def judged(self) -> bool:
        """Whether it is a review, rather than a comment."""
        return self.item is ReviewItem.REVIEW


def feedback(conn: sqlite3.Connection, urls: Collection[str]) -> dict[str, list[Feedback]]:
    """The feedback on each of `urls` from people other than its author, not bots'.

    Returns:
        Each PR's, by URL, in no order; a PR with none is not in it.
    """
    said = (
        sql.select("r.pr_url, r.item, r.author, r.state, r.created_at")
        .from_("observed_reviews r")
        .join("observed_prs p ON p.url = r.pr_url")
        .where("r.pr_url IN (SELECT value FROM json_each(?))", json.dumps(sorted(urls)))
        .where("r.bot = 0 AND (p.author IS NULL OR r.author IS NOT p.author)")
        .where("(r.item = ? OR r.state IN (SELECT value FROM json_each(?)))", ReviewItem.COMMENT, json.dumps(JUDGED))
    )
    found: dict[str, list[Feedback]] = {}
    for row in records.fetch_all(conn, Feedback, said):
        found.setdefault(row.pr_url, []).append(row)
    return found


def waiting_since(pr: records.ObservedPr) -> str | None:
    """When a PR began waiting on a review, as GitHub says: a review first asked for once it was ready, else ready.

    Returns:
        It, a journal time; None for a PR read before canopy kept GitHub's times, or a draft.
    """
    return pr.review_requested_at or pr.ready_at


def first_review(said: Iterable[Feedback], start: str) -> Feedback | None:
    """The first review in `said` made at or after `start`, a journal time.

    Returns:
        It; None with no such review.
    """
    begun = db.parse_time(start)
    found: tuple[datetime, Feedback] | None = None
    for review in said:
        if not review.judged or review.created_at is None:
            continue
        at = db.parse_time(review.created_at)
        if at >= begun and (found is None or at < found[0]):
            found = (at, review)
    return None if found is None else found[1]
