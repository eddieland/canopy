"""Reviews as the overseer sees them: the state block's `reviews` (DESIGN §21)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, NotRequired, TypedDict

from canopy.core import db
from canopy.core import review_result as result
from canopy.reviews import grants

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.config import Config

# PRs reviewed this recently are in the state block, newest first, at most this many.
RECENT = timedelta(days=14)
MAX_PRS = 50


class Limits(TypedDict):
    """The review limits in force, and how many reviews started in the last day."""

    max_reviews: int
    max_reviews_per_day: int
    max_reviews_per_pr: int
    started_last_24h: int


class RunningReview(TypedDict):
    """A review run still running."""

    run_id: int
    pr: str
    sha: str
    ticket: str | None
    started_at: str


class LatestReview(TypedDict):
    """A PR's latest review run. `findings` are the titles of those the operator did not dismiss."""

    run_id: int
    sha: str
    status: str
    verdict: str | None
    impact: str | None
    findings: list[str]
    dismissed_findings: int
    started_at: str
    ended_at: str | None
    reviewed_at: str | None


class ReviewedPR(TypedDict):
    """A PR reviewed recently. Only one the operator granted more reviews has `granted`."""

    url: str
    ticket: str | None
    review_runs: int
    granted: NotRequired[int]
    latest: LatestReview


class ReviewsSection(TypedDict):
    """The state block's `reviews` (DESIGN §21)."""

    agent_prs: bool
    query: str | None
    low_impact: bool
    limits: Limits
    running: list[RunningReview]
    prs: list[ReviewedPR]


def state_section(conn: sqlite3.Connection, config: Config, now: datetime) -> ReviewsSection | None:
    """Return the state block's `reviews`, or None when reviews are off: then the block has no such key."""
    if not config.reviews_on:
        return None
    runs = db.review_runs_since(conn, db.format_time(now - RECENT))
    by_pr: dict[str, list[sqlite3.Row]] = {}
    for run in runs:
        by_pr.setdefault(str(run["pr_url"]), []).append(run)
    prs = [_pr_summary(conn, url) for url in list(by_pr)[:MAX_PRS]]
    started_today = len(db.review_runs_since(conn, db.format_time(now - timedelta(hours=24))))
    return {
        "agent_prs": config.review.agent_prs,
        "query": config.review.query.strip() or None,
        "low_impact": bool(config.review.low_impact.strip()),
        "limits": {
            "max_reviews": config.capacity.max_reviews,
            "max_reviews_per_day": config.capacity.max_reviews_per_day,
            "max_reviews_per_pr": config.policy.max_reviews_per_pr,
            "started_last_24h": started_today,
        },
        "running": [
            {
                "run_id": r["id"],
                "pr": r["pr_url"],
                "sha": r["sha"],
                "ticket": r["ticket_key"],
                "started_at": r["started_at"],
            }
            for r in db.running_runs(conn, "review_runs")
        ],
        "prs": prs,
    }


def _pr_summary(conn: sqlite3.Connection, url: str) -> ReviewedPR:
    runs = db.review_runs_of(conn, url)
    latest = runs[0]
    stored = result.stored(latest["result_json"])
    granted = grants.granted(conn, url)
    # The operator's dismissals hold a finding back from workers and from the overseer alike (DESIGN §21).
    dismissed = db.review_dismissals(conn, int(latest["id"]))
    findings: list[result.Finding] = stored.findings if stored is not None else []
    return {
        "url": url,
        "ticket": next((r["ticket_key"] for r in runs if r["ticket_key"]), None),
        "review_runs": len(runs),
        # Only a PR the operator granted more reviews has the key: its limit is the policy's plus this.
        **({"granted": granted} if granted else {}),
        "latest": {
            "run_id": latest["id"],
            "sha": latest["sha"],
            "status": latest["status"],
            "verdict": stored.verdict if stored is not None else None,
            "impact": stored.impact if stored is not None else None,
            "findings": [f.title for i, f in enumerate(findings, 1) if i not in dismissed],
            "dismissed_findings": len(dismissed),
            "started_at": latest["started_at"],
            "ended_at": latest["ended_at"],
            # The review's time for the `review` cursor, which takes whole seconds only (DESIGN §7).
            "reviewed_at": _to_second(latest["ended_at"]),
        },
    }


def _to_second(stamp: str | None) -> str | None:
    """A time the journal wrote, `...T12:00:00.123Z`, as the `review` cursor's `...T12:00:00Z`.

    Returns:
        `stamp` cut to whole seconds, or None when there is no `stamp`.
    """
    return f"{stamp[:19]}Z" if stamp else None
