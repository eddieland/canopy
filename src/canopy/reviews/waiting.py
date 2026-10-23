"""The reviews' drafts that wait on the operator (DESIGN §14, §34), as the attention items the harness raises.

A review the operator asked for that landed with its draft unpublished is `review_waiting`, an item about its PR until
the operator publishes, stages, or discards a draft of the PR's newest reviewed commit, empties it of all it would post,
or the PR is seen merged or closed. A review of a later commit replaces it. A draft staged on GitHub, or whose post
ended without saying whether it submitted, is `review_unsettled` until a whole read of the PR settles it. Both are the
operator's alone: the overseer never records them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import records, review_drafts, review_requests, sql
from canopy.core.vocab import PrState, ReviewDraftStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

#: A requested review that landed with its draft unpublished.
WAITING_REASON = "review_waiting"
#: A review's draft staged on GitHub, or of unknown outcome, until a read settles it.
UNSETTLED_REASON = "review_unsettled"
#: Both, which the harness records and the overseer does not.
REASONS = frozenset({WAITING_REASON, UNSETTLED_REASON})


@dataclass(frozen=True)
class Item:
    """One item about a PR: its URL, its reason, and its detail, which names the review runs by `review:N`."""

    pr: str
    reason: str
    detail: str


def items(conn: sqlite3.Connection) -> list[Item]:
    """Return the items the reviews' drafts raise now: `review_waiting`, then `review_unsettled`, each by PR.

    Returns:
        At most one item of each reason per PR.
    """
    return [*_waiting(conn), *_unsettled(conn)]


def unread_prs(conn: sqlite3.Connection) -> list[str]:
    """Return the PRs a requested review's draft waits on that no read has seen merged or closed.

    Each tick's `vcs` read takes them, so a PR merged or closed since its review clears its `review_waiting` item, one
    whose request ended before the PR was ever read among them.

    Returns:
        The PRs' URLs, in order.
    """
    rows = sql.execute(
        conn,
        sql.select("d.pr_url")
        .unique()
        .from_("review_drafts d")
        .join("review_runs r ON r.id = d.review_run_id")
        .where("d.status = ?", ReviewDraftStatus.WAITING)
        .where("r.purpose = ?", review_requests.PURPOSE)
        .where("NOT EXISTS (SELECT 1 FROM observed_prs p WHERE p.url = d.pr_url AND p.state != ?)", PrState.OPEN)
        .order_by("d.pr_url"),
    )
    return [str(r["pr_url"]) for r in rows]


def _waiting(conn: sqlite3.Connection) -> list[Item]:
    """A `review_waiting` item for each open PR whose newest reviewed commit has a requested review's draft to publish.

    The drafts of that commit are taken together, a review in each persona among them: one published, staged,
    discarded, being posted, or of unknown outcome answers them all.

    Returns:
        The items, by PR.
    """
    drafts = records.fetch_all(
        conn,
        records.ReviewDraft,
        sql.select("*")
        .from_("review_drafts")
        # Each condition a lookup by index, so the list's read does not grow with the PRs the loop ever opened.
        .where("pr_url IN (SELECT pr_url FROM review_drafts WHERE status = ?)", ReviewDraftStatus.WAITING)
        .where("NOT EXISTS (SELECT 1 FROM ticket_units u WHERE u.pr_url = review_drafts.pr_url)")
        .where(
            "NOT EXISTS (SELECT 1 FROM observed_prs p WHERE p.url = review_drafts.pr_url AND p.state != ?)",
            PrState.OPEN,
        )
        .order_by("id"),
    )
    by_pr: dict[str, list[records.ReviewDraft]] = defaultdict(list)
    for draft in drafts:
        by_pr[draft.pr_url].append(draft)
    requested = _requested(conn, [d.review_run_id for d in drafts])
    found: list[Item] = []
    for pr in sorted(by_pr):
        newest = by_pr[pr][-1].sha
        of_head = [d for d in by_pr[pr] if d.sha == newest]
        if any(d.status is not ReviewDraftStatus.WAITING for d in of_head):
            continue
        runs = [d.review_run_id for d in of_head if d.review_run_id in requested and _posts(conn, d)]
        if runs:
            found.append(Item(pr, WAITING_REASON, _waiting_detail(pr, runs)))
    return found


def _requested(conn: sqlite3.Connection, run_ids: Sequence[int]) -> set[int]:
    """Which of review runs `run_ids` the operator asked for.

    Returns:
        Their ids.
    """
    if not run_ids:
        return set()
    rows = sql.execute(
        conn,
        sql.select("id").from_("review_runs").where("purpose = ?", review_requests.PURPOSE).where_in("id", run_ids),
    )
    return {int(r["id"]) for r in rows}


def _posts(conn: sqlite3.Connection, draft: records.ReviewDraft) -> bool:
    """Whether the draft's newest version would post anything: one the operator emptied waits on nobody.

    Returns:
        True when it holds a body or a comment.
    """
    version = review_drafts.newest(conn, draft.id)
    return bool(version.body or version.comments)


def _waiting_detail(pr: str, runs: Sequence[int]) -> str:
    named = " and ".join(f"review:{r}" for r in runs)
    if len(runs) == 1:
        return (
            f"{named}, which you asked for, is done: its draft of {pr} waits on you to publish or stage it "
            f"(`canopy review draft {runs[0]}`), or discard it (`canopy review discard {runs[0]}`)"
        )
    return (
        f"{named}, which you asked for, are done: their drafts of {pr} wait on you to publish or stage one, or "
        "discard one (`canopy review discard RUN_ID`)"
    )


def _unsettled(conn: sqlite3.Connection) -> list[Item]:
    """A `review_unsettled` item for each PR with a review's draft staged or of unknown outcome.

    Returns:
        The items, by PR.
    """
    drafts = records.fetch_all(
        conn,
        records.ReviewDraft,
        sql.select("*")
        .from_("review_drafts")
        .where_in("status", (ReviewDraftStatus.STAGED, ReviewDraftStatus.UNCONFIRMED))
        .order_by("pr_url, id"),
    )
    by_pr: dict[str, list[str]] = defaultdict(list)
    for draft in drafts:
        by_pr[draft.pr_url].append(_unsettled_detail(draft))
    return [Item(pr, UNSETTLED_REASON, "; ".join(details)) for pr, details in by_pr.items()]


def _unsettled_detail(draft: records.ReviewDraft) -> str:
    ref = f"review:{draft.review_run_id}"
    if draft.status is ReviewDraftStatus.STAGED:
        return (
            f"{ref}'s draft is in the review you staged on {draft.pr_url}: submit or delete it on GitHub, and the "
            "next read of the PR settles it"
        )
    return (
        f"{ref}'s draft may have been posted on {draft.pr_url}: the next whole read of the PR says whether, and "
        "nothing posts for it until then"
    )
