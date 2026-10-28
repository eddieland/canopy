"""The reviews that wait on the operator (DESIGN §14, §21, §34), as the attention items the harness raises.

A review the operator asked for that landed with its draft unpublished is `review_waiting`, an item about its PR until
the operator publishes, stages, or discards a draft of the PR's newest reviewed commit, empties it of all it would post,
or the PR is seen merged or closed. A review of a later commit replaces it. A draft staged on GitHub, or whose post
ended without saying whether it submitted, is `review_unsettled` until a whole read of the PR settles it. A finding of
one of the loop's own PRs' reviews that canopy holds is `review_rebuttal` for a rebuttal of a worker's decline and
`review_late` for one on code unchanged since the PR's first reviewed commit, about its ticket, until the operator
sends it to a worker or dismisses it, or the PR is no longer the ticket's or is seen merged or closed. All four are the
operator's alone: the overseer never records them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, assert_never

from canopy.core import records, review_drafts, review_requests, sql
from canopy.core.vocab import HoldKind, PrState, ReviewDraftStatus, ReviewRunStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

#: A requested review that landed with its draft unpublished.
WAITING_REASON: Final = "review_waiting"
#: A review's draft staged on GitHub, or of unknown outcome, until a read settles it.
UNSETTLED_REASON: Final = "review_unsettled"
#: A finding canopy holds for the operator: a later review's rebuttal of a finding the worker declined.
REBUTTAL_REASON: Final = "review_rebuttal"
#: A finding canopy holds for the operator: a later review's, on code unchanged since the PR's first reviewed commit.
LATE_REASON: Final = "review_late"
#: All four, which the harness records and the overseer does not.
REASONS: Final = frozenset({WAITING_REASON, UNSETTLED_REASON, REBUTTAL_REASON, LATE_REASON})
#: The reason each kind of hold raises.
_HELD_REASONS: Final[Mapping[HoldKind, str]] = {HoldKind.REBUTTAL: REBUTTAL_REASON, HoldKind.LATE: LATE_REASON}
#: What the operator may do with a held finding of each kind, closing its item's detail.
_HELD_ASK: Final[Mapping[HoldKind, str]] = {
    HoldKind.REBUTTAL: (
        "canopy holds it for you, never for another resume: send it to a worker (`canopy send review:ID N`), or "
        "dismiss it if the worker was right (`canopy dismiss review:ID N --reason R`)"
    ),
    HoldKind.LATE: (
        "The PR's first review read that code, so canopy holds it for you rather than resume for it: send it to a "
        "worker (`canopy send review:ID N`), or dismiss it if it can wait (`canopy dismiss review:ID N --reason R`)"
    ),
}


@dataclass(frozen=True)
class Item:
    """One item about a PR: its URL, its reason, and its detail, which names the review runs by `review:N`."""

    pr: str
    reason: str
    detail: str
    #: The ticket whose PR it is, for an item about one of the loop's own PRs; None for another PR.
    ticket: str | None = None


def items(conn: sqlite3.Connection) -> list[Item]:
    """Return the items the reviews raise now: `review_waiting`, `review_unsettled`, `review_rebuttal`, `review_late`.

    Returns:
        At most one item of each reason per PR.
    """
    return [*_waiting(conn), *_unsettled(conn), *_held(conn)]


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


def _held(conn: sqlite3.Connection) -> list[Item]:
    """A `review_rebuttal` and a `review_late` item for each ticket whose open PR has findings canopy holds of the kind.

    Returns:
        The items, rebuttals first, each by ticket, each naming every finding held of its kind.
    """
    # CROSS JOIN keeps SQLite reading the few holds and each one's run, rather than every review run for the order.
    rows = sql.execute(
        conn,
        sql.select("h.review_run_id, h.finding, h.kind, h.rebuts_run_id, h.rebuts_finding, r.pr_url, r.ticket_key")
        .from_("review_holds h CROSS JOIN review_runs r ON r.id = h.review_run_id")
        .where("h.released_at IS NULL")
        .where("r.status = ? AND r.ticket_key IS NOT NULL", ReviewRunStatus.DONE)
        .where(
            "NOT EXISTS (SELECT 1 FROM review_dismissals d WHERE d.review_run_id = h.review_run_id "
            "AND d.finding = h.finding)",
        )
        .where("EXISTS (SELECT 1 FROM ticket_units u WHERE u.ticket_key = r.ticket_key AND u.pr_url = r.pr_url)")
        .where("NOT EXISTS (SELECT 1 FROM observed_prs p WHERE p.url = r.pr_url AND p.state != ?)", PrState.OPEN)
        .order_by("r.pr_url, h.review_run_id, h.finding"),
    ).fetchall()
    # One item a ticket and reason, as the attention list keys it, naming the PR of its first held finding: a joint
    # run's PRs share their ticket's.
    by_item: dict[tuple[str, HoldKind], list[str]] = defaultdict(list)
    prs: dict[tuple[str, HoldKind], str] = {}
    for r in rows:
        kind, held = HoldKind(r["kind"]), f"review:{r['review_run_id']} finding {r['finding']}"
        prs.setdefault((str(r["ticket_key"]), kind), str(r["pr_url"]))
        by_item[str(r["ticket_key"]), kind].append(_held_detail(held, kind, r["rebuts_run_id"], r["rebuts_finding"]))
    order = list(HoldKind)
    return [
        Item(prs[ticket, kind], _HELD_REASONS[kind], f"{'; '.join(held)}. {_HELD_ASK[kind]}", ticket=ticket)
        for (ticket, kind), held in sorted(by_item.items(), key=lambda i: (order.index(i[0][1]), i[0][0]))
    ]


def _held_detail(held: str, kind: HoldKind, rebuts_run_id: object, rebuts_finding: object) -> str:
    # What one held finding is, as its item names it.
    match kind:
        case HoldKind.REBUTTAL:
            return f"{held} rebuts the worker's decline of review:{rebuts_run_id} finding {rebuts_finding}"
        case HoldKind.LATE:
            return f"{held} is on code unchanged since the PR's first reviewed commit"
        case _:
            assert_never(kind)
