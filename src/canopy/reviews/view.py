"""Reviews as the overseer sees them: the state block's `reviews` (DESIGN §21)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.reviews import result

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.config import Config

# PRs reviewed this recently are in the state block, newest first, at most this many.
RECENT = timedelta(days=14)
MAX_PRS = 50


def state_section(conn: sqlite3.Connection, config: Config, now: datetime) -> dict[str, object] | None:
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
            for r in db.running_review_runs(conn)
        ],
        "prs": prs,
    }


def _pr_summary(conn: sqlite3.Connection, url: str) -> dict[str, object]:
    runs = db.review_runs_of(conn, url)
    latest = runs[0]
    stored = result.stored(latest["result_json"])
    return {
        "url": url,
        "ticket": next((r["ticket_key"] for r in runs if r["ticket_key"]), None),
        "review_runs": len(runs),
        "latest": {
            "run_id": latest["id"],
            "sha": latest["sha"],
            "status": latest["status"],
            "verdict": stored.verdict if stored is not None else None,
            "impact": stored.impact if stored is not None else None,
            "comment": stored.comment if stored is not None else None,
            "findings": [f.title for f in stored.findings] if stored is not None else [],
            "started_at": latest["started_at"],
            "ended_at": latest["ended_at"],
        },
    }
