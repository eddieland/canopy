"""Review runs (DESIGN §21): each review of a PR, its slot, and the findings the operator dismissed or canopy holds.

A review run's lifecycle, from its claim to its close, is the one every run table shares (`db.claim_run`,
`db.finish_run`); what is here is the review's own: its start, its slot, and its runs as a PR's reviews read them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, records, sql
from canopy.core.vocab import DismissalReason, HoldKind, ReviewRunStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from canopy.core.vocab import PoolKind


#: A PR's reviews: its review runs but the revisions of their drafts (DESIGN §34), which review nothing, report no
#: verdict, and count toward their draft's limit rather than the PR's.
_REVIEWS = records.select(records.ReviewRun).where("revises IS NULL")


def insert_review_run(
    conn: sqlite3.Connection,
    *,
    tick_id: int,
    pr_url: str,
    sha: str,
    ticket: str | None,
    repo: str | None,
    purpose: str,
    logs_dir: Path,
    persona: str | None = None,
    persona_digest: str | None = None,
    persona_text: str | None = None,
    revises: tuple[int, int] | None = None,
    model: str | None = None,
) -> int:
    """Insert a `running` review run with no slot or pid yet, logging to `<logs_dir>/<id>.log`, and return its id.

    `purpose` is why it runs (DESIGN §21): `own` for one of the loop's own PRs, `request` for a PR the operator
    asked for, `query` for a `review.query` match. `persona` and `persona_digest` are the name and text digest of the
    persona its prompt carries (DESIGN §31), and `persona_text` that text, kept once per digest
    (`db.record_persona_text`). `revises` makes it a revision (§34): the draft it revises, by its id, and the version of
    it the revision reads. `model` is the one its reviewer asks for (DESIGN §13), None for the runtime's default.

    Returns:
        The new review run's id.
    """
    with db.transaction(conn):
        run = records.insert(
            records.ReviewRun,
            tick_id=tick_id,
            pr_url=pr_url,
            sha=sha,
            ticket_key=ticket,
            repo=repo,
            purpose=purpose,
            started_at=db.now(),
            log_path="",
            persona=persona,
            persona_digest=persona_digest,
            revises=revises[0] if revises is not None else None,
            revises_version=revises[1] if revises is not None else None,
            model=model,
        )
        run_id = db.rowid(run.run(conn))
        db.record_persona_text(conn, persona_digest, persona_text)
        log_path = str(logs_dir / f"{run_id}.log")
        records.update(records.ReviewRun).set(log_path=log_path).where("id = ?", run_id).run(conn)
    return run_id


def delete_review_run(conn: sqlite3.Connection, run_id: int) -> None:
    """Forget a review run that never started: no slot, or no prompt. It counts toward no limit."""
    records.delete(records.ReviewRun).where("id = ? AND pid IS NULL", run_id).run(conn)


def review_dismissals(conn: sqlite3.Connection, run_id: int) -> dict[int, DismissalReason | None]:
    """Return review run `run_id`'s findings the operator dismissed (DESIGN §21), by their numbers from 1.

    Returns:
        Each dismissed finding's number, with why it was dismissed: None for a dismissal from before canopy asked.
    """
    query = sql.select("finding, reason").from_("review_dismissals").where("review_run_id = ?", run_id)
    return {int(r[0]): DismissalReason(r[1]) if r[1] is not None else None for r in sql.execute(conn, query)}


def set_review_dismissal(
    conn: sqlite3.Connection,
    run_id: int,
    finding: int,
    *,
    reason: DismissalReason,
    channel: str,
) -> None:
    """Record that the operator dismissed review run `run_id`'s finding number `finding` now, for `reason`."""
    records.insert(
        records.ReviewDismissal,
        review_run_id=run_id,
        finding=finding,
        dismissed_at=db.now(),
        channel=channel,
        reason=reason,
    ).on_conflict(
        "(review_run_id, finding) DO UPDATE SET dismissed_at = excluded.dismissed_at, channel = excluded.channel, "
        "reason = excluded.reason",
    ).run(conn)


def held(conn: sqlite3.Connection, run_id: int, *, released: bool = False) -> dict[int, records.ReviewHold]:
    """Return review run `run_id`'s findings the harness holds for the operator (DESIGN §21), by their numbers from 1.

    A held finding reaches no worker and starts no `resume` until the operator sends it, which releases it.

    Args:
        conn: The journal.
        run_id: The review run.
        released: Also return the findings the operator has released, which were held once.

    Returns:
        Each finding still held, with its hold; one the operator released only with `released`.
    """
    query = records.select(records.ReviewHold).where("review_run_id = ?", run_id)
    if not released:
        query = query.where("released_at IS NULL")
    return {h.finding: h for h in query.all(conn)}


def withheld(conn: sqlite3.Connection, run_id: int) -> frozenset[int]:
    """Return review run `run_id`'s findings no worker or tick acts on: dismissed, or held for the operator (§21).

    Returns:
        Their numbers, from 1.
    """
    return frozenset(review_dismissals(conn, run_id)) | frozenset(held(conn, run_id))


def hold(conn: sqlite3.Connection, run_id: int, finding: int, *, rebuts: tuple[int, int] | None) -> None:
    """Hold review run `run_id`'s finding number `finding` for the operator: a rebuttal of `rebuts`'s finding, or late.

    `rebuts` is the earlier review run, and its finding, that the worker declined; None holds the finding as `late`, on
    code unchanged since the PR's first reviewed commit. A finding already held keeps its first hold.
    """
    records.insert(
        records.ReviewHold,
        review_run_id=run_id,
        finding=finding,
        kind=HoldKind.LATE if rebuts is None else HoldKind.REBUTTAL,
        rebuts_run_id=rebuts[0] if rebuts is not None else None,
        rebuts_finding=rebuts[1] if rebuts is not None else None,
        held_at=db.now(),
    ).on_conflict("(review_run_id, finding) DO NOTHING").run(conn)


def release_holds(conn: sqlite3.Connection, run_id: int, findings: Iterable[int], *, channel: str) -> None:
    """Release the operator's hold on review run `run_id`'s `findings`: they reach a worker as any other finding."""
    sql.execute_many(
        conn,
        records.update(records.ReviewHold)
        .set(released_at=db.now(), released_channel=channel)
        .where("review_run_id = ? AND finding = ? AND released_at IS NULL", run_id, sql.ROW),
        [(f,) for f in findings],
    )


def delete_review_dismissal(conn: sqlite3.Connection, run_id: int, finding: int) -> bool:
    """Take back the operator's dismissal of review run `run_id`'s finding number `finding`.

    Returns:
        Whether there was one to take back.
    """
    taken = records.delete(records.ReviewDismissal).where("review_run_id = ? AND finding = ?", run_id, finding)
    return taken.run(conn).rowcount > 0


def set_review_slot(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    slot: Path,
    lease_id: str,
    lease_holder: str,
    base_branch: str,
    pool: PoolKind,
) -> None:
    """Record the slot a review run leased, the base branch it was leased on, and the pool that made the lease."""
    lease = records.update(records.ReviewRun).set(
        slot_path=str(slot),
        lease_id=lease_id,
        lease_holder=lease_holder,
        base_branch=base_branch,
        pool=pool,
    )
    lease.where("id = ?", run_id).run(conn)


def get_review_run(conn: sqlite3.Connection, run_id: int) -> records.ReviewRun | None:
    """Return the review run with `run_id`, or None."""
    return records.select(records.ReviewRun).where("id = ?", run_id).one(conn)


def review_runs_of(conn: sqlite3.Connection, pr_url: str) -> list[records.ReviewRun]:
    """Return a PR's review runs, newest first, revisions left out."""
    return _REVIEWS.where("pr_url = ?", pr_url).order_by("id DESC").all(conn)


def recent_review_runs(conn: sqlite3.Connection, limit: int) -> list[records.ReviewRun]:
    """Return the latest `limit` review runs, newest first, revisions left out."""
    return _REVIEWS.order_by("id DESC").limit(limit).all(conn)


def review_runs_since(conn: sqlite3.Connection, since: str, *, revisions: bool = False) -> list[records.ReviewRun]:
    """Return the review runs started at or after `since`, newest first, with `revisions` the revisions too."""
    every = records.select(records.ReviewRun) if revisions else _REVIEWS
    return every.where("started_at >= ?", since).order_by("id DESC").all(conn)


def revision_runs_of(conn: sqlite3.Connection, draft_id: int) -> list[records.ReviewRun]:
    """Return the revisions of review draft `draft_id` (DESIGN §34), newest first."""
    query = records.select(records.ReviewRun).where("revises = ?", draft_id).order_by("id DESC")
    return query.all(conn)


def is_unit_pr(conn: sqlite3.Connection, key: str, pr_url: str, *, repo: str | None = None) -> bool:
    """Return whether `pr_url` is the PR of one of ticket `key`'s units, or its unit in `repo`: one the loop opened."""
    query = sql.select("1").from_("ticket_units").where("ticket_key = ? AND pr_url = ?", key, pr_url)
    if repo is not None:
        query = query.where("repo = ?", repo)
    return sql.execute(conn, query).fetchone() is not None


def review_runs_of_prs(conn: sqlite3.Connection, pr_urls: Sequence[str]) -> dict[str, list[records.ReviewRun]]:
    """Return the review runs of each of `pr_urls` that has any, by URL, each list newest first."""
    found: dict[str, list[records.ReviewRun]] = {}
    # SQLite takes an empty list, `IN ()`, as matching nothing.
    query = _REVIEWS.where_in("pr_url", pr_urls).order_by("id DESC")
    for run in query.all(conn):
        found.setdefault(run.pr_url, []).append(run)
    return found


def see_review_head(conn: sqlite3.Connection, pr_url: str, sha: str, at: str) -> str:
    """Record that `sha` was the PR's head at `at`, unless it already was the head canopy last saw (DESIGN §21).

    A different commit replaces the PR's row, so its wait starts at `at`: a push, or a force push back to an earlier
    commit, starts over.

    Returns:
        Since when `sha` has been the head: `at`, or the time it was first seen if it still was the head.
    """
    seen = records.insert(records.ReviewHead, pr_url=pr_url, sha=sha, seen_at=at).on_conflict(
        "(pr_url) DO UPDATE SET sha = excluded.sha, seen_at = excluded.seen_at WHERE review_heads.sha != excluded.sha",
    )
    seen.run(conn)
    return review_head_seen_at(conn, pr_url, sha) or at


def review_head_seen_at(conn: sqlite3.Connection, pr_url: str, sha: str) -> str | None:
    """Return since when `sha` has been the PR's head canopy last saw, or None if that head is another commit."""
    query = records.select(records.ReviewHead).where("pr_url = ? AND sha = ?", pr_url, sha)
    head = query.one(conn)
    return None if head is None else head.seen_at


def review_heads_seen_after(conn: sqlite3.Connection, since: str) -> list[records.ReviewHead]:
    """Return the PR heads seen after `since` with no `done` review of them, newest first."""
    reviewed = (
        sql.select("1")
        .from_("review_runs r")
        .where("r.pr_url = h.pr_url AND r.sha = h.sha AND r.revises IS NULL AND r.status = ?", ReviewRunStatus.DONE)
    )
    query = (
        records.select(records.ReviewHead, "h")
        .where("h.seen_at > ?", since)
        .where("NOT EXISTS ({})", reviewed)
        .order_by("h.seen_at DESC, h.pr_url")
    )
    return query.all(conn)
