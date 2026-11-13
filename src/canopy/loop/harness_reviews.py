"""The harness answers the operator's review requests (DESIGN §21, §37, ROADMAP M38): the row `review_request`.

Each tick derives what to do with each open request (`loop.requested_reviews`). For a request it takes, the harness
does it in code. Before the overseer runs it records its `wait`, on a review running, a draft, or a PR the `vcs`
source left stale or never read, and ends a request whose PR merged or closed first, is in no repository of the
workspace, or was reviewed at its head already. After the overseer's run, whatever it ended as, the tick starts the
review of each one at an unreviewed head, first in §7's order, in each persona still owed one, under every guard an
overseer's review passes (`reviews.start`), with no context: none is model-written (TRUST_MODEL T1). Each is recorded
as the harness's own, about the PR. A dry run records the same, ends nothing, and checks the guards and starts none
(D036).

The overseer is not shown a request the harness takes, and what it records about one, a review, a wait, or an end,
is refused `decided` (`refuse_decided`). Each review it starts holds a worker and a review run ahead of the overseer's
dispatches and its other reviews, which are refused `reserved` should they take them (`holds`).

The row is enabled on MEASUREMENTS "2026-11-10: M38, the derivation against the overseer over two weeks": five
situations, no disagreement. A request on one of the loop's own PRs is refused as it is made (`review_requests`).
Chosen conservatively, for the operator to change: one whose PR a ticket's unit has opened since stays the
overseer's, which names its ticket and weighs its review beside the ticket's rows.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, assert_never

from canopy.core import db, records, sql
from canopy.core.items import ACTION_PREFIX
from canopy.core.vocab import Decider, RequestAction
from canopy.loop import attention
from canopy.reviews import grants, review_requests
from canopy.reviews import start as review_start

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

    from canopy.core.context import Context
    from canopy.infra import logs


def takes(conn: sqlite3.Connection, pr_url: str) -> bool:
    """Whether the request on `pr_url` is the harness's: its PR is not one a ticket's unit opened.

    Returns:
        False for one of the loop's own PRs, whose request stays the overseer's.
    """
    query = sql.select("1").from_("ticket_units").where("pr_url = ?", pr_url)
    return sql.execute(conn, query).fetchone() is None


def taken(conn: sqlite3.Connection, tick_id: int) -> frozenset[str]:
    """The PRs whose requests the harness answers in tick `tick_id`, which the overseer is not shown.

    Returns:
        The URL of each request the tick derived that the harness takes.
    """
    return frozenset(r.pr_url for r in _derived(conn, tick_id))


def decide(ctx: Context, tick_id: int, *, dry_run: bool, log: logs.TickAdapter) -> None:
    """Record the harness's `wait` on each request it takes that waits, and end each that ends, before the overseer.

    A dry run records each and ends none.
    """
    for row in _derived(ctx.conn, tick_id):
        match row.action:
            case RequestAction.START:
                # Started after the overseer, with every other run the tick starts (`loop.spawns`).
                continue
            case RequestAction.WAIT:
                why = f"stale: {row.stale}; it waits for the vcs source to read it" if row.stale else str(row.reason)
                _record(ctx, tick_id, row.pr_url, "wait", why)
            case RequestAction.END:
                _end(ctx, tick_id, row.pr_url, str(row.reason), dry_run=dry_run)
            case _:
                assert_never(row.action)
        log.info("harness answered a review request", extra={"pr": row.pr_url, "action": row.action})


def starts(conn: sqlite3.Connection, tick_id: int) -> list[records.RequestDerivation]:
    """The requests whose reviews the harness starts after the overseer in tick `tick_id`, oldest first.

    Returns:
        Each request the tick derived a start for that the harness takes, with the head it starts at.
    """
    return [r for r in _derived(conn, tick_id) if r.action is RequestAction.START and r.head_sha is not None]


def holds(ctx: Context, tick_id: int) -> int:
    """The reviews the harness starts after the overseer in tick `tick_id`: one in each persona still owed one.

    Each holds a review run and a worker, first in §7's order, which the overseer's dispatches and reviews ranked below
    it leave free (`harness_dispatches.reserved`). A request a guard would refuse before any persona holds none.

    Returns:
        How many.
    """
    held = 0
    for row in starts(ctx.conn, tick_id):
        asked = review_start.Request(pr=row.pr_url, sha=str(row.head_sha), ticket=None, repo=None)
        with contextlib.suppress(review_start.Refusal):
            held += len(review_start.due(ctx, asked))
    return held


def make_review(
    ctx: Context,
    tick_id: int,
    row: records.RequestDerivation,
    *,
    dry_run: bool,
    log: logs.TickAdapter,
) -> None:
    """Start the review `row` derived, in each persona still owed one, or in a dry run check its guards.

    Each review and each refusal is recorded as the harness's. A guard that refuses one after the first leaves it and
    the rest to a later tick, as for the overseer's (`review_tools.review_run`).
    """
    pr = row.pr_url
    repo = review_requests.repo_of(ctx.workspace, pr)
    asked = review_start.Request(pr=pr, sha=str(row.head_sha), ticket=None, repo=repo.name if repo else None)
    try:
        due = review_start.due(ctx, asked)
    except review_start.Refusal as r:
        _refused(ctx, tick_id, pr, r, dry_run=dry_run, log=log)
        return
    for one in due:
        in_persona = f" in {one.persona}" if one.persona is not None else ""
        try:
            if dry_run:
                review_start.check(ctx, tick_id=tick_id, request=one)
                rationale = f"dry run: not dispatched; would review {one.sha}{in_persona}"
            else:
                started = review_start.start(ctx, tick_id=tick_id, request=one, context=None)
                rationale = f"review run {started.run_id}: {one.sha} in {started.slot}{in_persona}"
        except review_start.Refusal as r:
            _refused(ctx, tick_id, pr, r, dry_run=dry_run, log=log)
            return
        _record(ctx, tick_id, pr, review_start.DISPATCH_ACTION, rationale)
        log.info("harness started a review", extra={"pr": pr, "persona": one.persona, "dry_run": dry_run})


def reviews_to_come(rows: Sequence[records.RequestDerivation]) -> list[str]:
    """The state block's `dispatches_to_come.reviews`: the PR of each review the harness starts after the overseer.

    Returns:
        Their URLs, in the order it starts them.
    """
    return [r.pr_url for r in rows]


def refuse_decided(ctx: Context, tick_id: int, pr_url: str, verb: str) -> str | None:
    """Record the refusal of the overseer's `verb` about `pr_url` if the harness answers its request this tick.

    A request it ended before the overseer ran is open no longer, so what it recorded about the PR counts too.

    Returns:
        The refusal's reason, or None when the PR is the overseer's to decide.
    """
    if pr_url not in taken(ctx.conn, tick_id) and not _answered(ctx.conn, tick_id, pr_url):
        return None
    reason = f"the harness answers the review request on {pr_url} this tick; record nothing about it"
    db.record_decision(ctx.conn, tick_id, None, attention.REFUSED_DECIDED, f"{verb}: {reason}", pr=pr_url)
    return reason


def _derived(conn: sqlite3.Connection, tick_id: int) -> list[records.RequestDerivation]:
    """What tick `tick_id` derived for each request the harness takes, oldest request first.

    Returns:
        The rows, less those of a request since ended or on one of the loop's own PRs.
    """
    rows = records.select(records.RequestDerivation).where("tick_id = ?", tick_id).order_by("request_id").all(conn)
    opened = {r.id for r in review_requests.open_requests(conn)}
    return [r for r in rows if r.request_id in opened and takes(conn, r.pr_url)]


def _answered(conn: sqlite3.Connection, tick_id: int, pr_url: str) -> bool:
    """Whether the harness recorded an answer to the request on `pr_url` in tick `tick_id`: a wait, an end, a review.

    Returns:
        False when all it recorded about the PR, if anything, is an attention item.
    """
    made = (
        records.select(records.Decision)
        .where("tick_id = ? AND pr = ? AND decider = ? AND ticket_key IS NULL", tick_id, pr_url, Decider.HARNESS)
        .where("action NOT LIKE ?", f"{ACTION_PREFIX}%")
        .all(conn)
    )
    return bool(made)


def _end(ctx: Context, tick_id: int, pr: str, reason: str, *, dry_run: bool) -> None:
    """End the request on `pr` for `reason`, as the overseer's `review-end` or a refusal `reviewed` would."""
    if not dry_run:
        if reason == review_requests.REVIEWED:
            review_requests.answered(ctx.conn, pr)
        else:
            review_requests.end(ctx.conn, pr, reason)
    _record(ctx, tick_id, pr, review_requests.END_ACTION, f"dry run: not ended; {reason}" if dry_run else reason)


def _refused(
    ctx: Context,
    tick_id: int,
    pr: str,
    r: review_start.Refusal,
    *,
    dry_run: bool,
    log: logs.TickAdapter,
) -> None:
    """Record a guard's refusal of the harness's review, and what it leaves the operator, as the overseer's does."""
    _record(ctx, tick_id, pr, f"refused:{r.guard}", r.reason)
    if r.guard == review_requests.REVIEWED and not dry_run:
        # The head already has its `done` review: that answers the request, which no new review would end.
        review_requests.answered(ctx.conn, pr)
    if r.guard == "review_limit":
        _record(ctx, tick_id, pr, f"{ACTION_PREFIX}review_limit", f"{r.reason}; {grants.hint(pr)}")
    if r.attention is not None:
        _record(ctx, tick_id, pr, f"{ACTION_PREFIX}{r.attention}", r.reason)
    log.info("harness review refused", extra={"pr": pr, "guard": r.guard, "reason": r.reason})


def _record(ctx: Context, tick_id: int, pr: str, action: str, rationale: str) -> None:
    db.record_decision(ctx.conn, tick_id, None, action, rationale, pr=pr, decider=Decider.HARNESS)
