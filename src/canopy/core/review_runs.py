"""Review runs (DESIGN §21): each review of a PR, its slot, and the findings the operator dismissed or canopy holds.

A review run's lifecycle, from its claim to its close, is the one every run table shares (`db.claim_run`,
`db.finish_run`); what is here is the review's own: its start, its slot, and its runs as a PR's reviews read them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, records, sql
from canopy.core.vocab import DismissalReason, HoldKind

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from canopy.core.vocab import PoolKind


#: A PR's reviews: its review runs but the revisions of their drafts (DESIGN §34), which review nothing, report no
#: verdict, and count toward their draft's limit rather than the PR's.
_REVIEWS = sql.select("*").from_("review_runs").where("revises IS NULL")


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
) -> int:
    """Insert a `running` review run with no slot or pid yet, logging to `<logs_dir>/<id>.log`, and return its id.

    `purpose` is why it runs (DESIGN §21): `own` for one of the loop's own PRs, `request` for a PR the operator
    asked for, `query` for a `review.query` match. `persona` and `persona_digest` are the name and text digest of the
    persona its prompt carries (DESIGN §31), and `persona_text` that text, kept once per digest
    (`db.record_persona_text`). `revises` makes it a revision (§34): the draft it revises, by its id, and the version of
    it the revision reads.

    Returns:
        The new review run's id.
    """
    with db.transaction(conn):
        run = sql.insert(
            "review_runs",
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
        )
        run_id = db.rowid(sql.execute(conn, run))
        db.record_persona_text(conn, persona_digest, persona_text)
        log_path = str(logs_dir / f"{run_id}.log")
        sql.execute(conn, sql.update("review_runs").set(log_path=log_path).where("id = ?", run_id))
    return run_id


def delete_review_run(conn: sqlite3.Connection, run_id: int) -> None:
    """Forget a review run that never started: no slot, or no prompt. It counts toward no limit."""
    sql.execute(conn, sql.delete("review_runs").where("id = ? AND pid IS NULL", run_id))


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
    sql.execute(
        conn,
        sql.insert(
            "review_dismissals",
            review_run_id=run_id,
            finding=finding,
            dismissed_at=db.now(),
            channel=channel,
            reason=reason,
        ).on_conflict(
            "(review_run_id, finding) DO UPDATE SET dismissed_at = excluded.dismissed_at, channel = excluded.channel, "
            "reason = excluded.reason",
        ),
    )


def held(conn: sqlite3.Connection, run_id: int) -> dict[int, records.ReviewHold]:
    """Return review run `run_id`'s findings the harness holds for the operator (DESIGN §21), by their numbers from 1.

    A held finding reaches no worker and starts no `resume` until the operator sends it, which releases it.

    Returns:
        Each finding still held, with its hold; one the operator released is not among them.
    """
    query = sql.select("*").from_("review_holds").where("review_run_id = ? AND released_at IS NULL", run_id)
    return {h.finding: h for h in records.fetch_all(conn, records.ReviewHold, query)}


def withheld(conn: sqlite3.Connection, run_id: int) -> frozenset[int]:
    """Return review run `run_id`'s findings no worker or tick acts on: dismissed, or held for the operator (§21).

    Returns:
        Their numbers, from 1.
    """
    return frozenset(review_dismissals(conn, run_id)) | frozenset(held(conn, run_id))


def hold(conn: sqlite3.Connection, run_id: int, finding: int, *, rebuts: tuple[int, int]) -> None:
    """Hold review run `run_id`'s finding number `finding` for the operator: a rebuttal of `rebuts`'s finding.

    `rebuts` is the earlier review run, and its finding, that the worker declined.
    """
    sql.execute(
        conn,
        sql.insert(
            "review_holds",
            review_run_id=run_id,
            finding=finding,
            kind=HoldKind.REBUTTAL,
            rebuts_run_id=rebuts[0],
            rebuts_finding=rebuts[1],
            held_at=db.now(),
        ).on_conflict("(review_run_id, finding) DO NOTHING"),
    )


def release_holds(conn: sqlite3.Connection, run_id: int, findings: Iterable[int], *, channel: str) -> None:
    """Release the operator's hold on review run `run_id`'s `findings`: they reach a worker as any other finding."""
    sql.execute_many(
        conn,
        sql.update("review_holds")
        .set(released_at=db.now(), released_channel=channel)
        .where("review_run_id = ? AND finding = ? AND released_at IS NULL", run_id, sql.ROW),
        [(f,) for f in findings],
    )


def delete_review_dismissal(conn: sqlite3.Connection, run_id: int, finding: int) -> bool:
    """Take back the operator's dismissal of review run `run_id`'s finding number `finding`.

    Returns:
        Whether there was one to take back.
    """
    taken = sql.delete("review_dismissals").where("review_run_id = ? AND finding = ?", run_id, finding)
    return sql.execute(conn, taken).rowcount > 0


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
    lease = sql.update("review_runs").set(
        slot_path=str(slot),
        lease_id=lease_id,
        lease_holder=lease_holder,
        base_branch=base_branch,
        pool=pool,
    )
    sql.execute(conn, lease.where("id = ?", run_id))


def get_review_run(conn: sqlite3.Connection, run_id: int) -> records.ReviewRun | None:
    """Return the review run with `run_id`, or None."""
    return records.fetch_one(conn, records.ReviewRun, sql.select("*").from_("review_runs").where("id = ?", run_id))


def review_runs_of(conn: sqlite3.Connection, pr_url: str) -> list[records.ReviewRun]:
    """Return a PR's review runs, newest first, revisions left out."""
    return records.fetch_all(conn, records.ReviewRun, _REVIEWS.where("pr_url = ?", pr_url).order_by("id DESC"))


def recent_review_runs(conn: sqlite3.Connection, limit: int) -> list[records.ReviewRun]:
    """Return the latest `limit` review runs, newest first, revisions left out."""
    return records.fetch_all(conn, records.ReviewRun, _REVIEWS.order_by("id DESC").limit(limit))


def review_runs_since(conn: sqlite3.Connection, since: str, *, revisions: bool = False) -> list[records.ReviewRun]:
    """Return the review runs started at or after `since`, newest first, with `revisions` the revisions too."""
    every = sql.select("*").from_("review_runs") if revisions else _REVIEWS
    return records.fetch_all(conn, records.ReviewRun, every.where("started_at >= ?", since).order_by("id DESC"))


def revision_runs_of(conn: sqlite3.Connection, draft_id: int) -> list[records.ReviewRun]:
    """Return the revisions of review draft `draft_id` (DESIGN §34), newest first."""
    query = sql.select("*").from_("review_runs").where("revises = ?", draft_id).order_by("id DESC")
    return records.fetch_all(conn, records.ReviewRun, query)


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
    for run in records.fetch_all(conn, records.ReviewRun, query):
        found.setdefault(run.pr_url, []).append(run)
    return found
