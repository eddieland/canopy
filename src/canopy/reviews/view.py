"""Reviews as the overseer sees them: the state block's `reviews` (DESIGN §21), and the revisions asked for (§34)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, NotRequired, TypedDict

from canopy.core import db, personas, review_requests, review_revisions, review_runs
from canopy.core import review_result as result
from canopy.core.vocab import ReviewRunStatus
from canopy.reviews import grants
from canopy.reviews import start as review_start

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

    from canopy.core import records
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
    """A PR's latest review run. `findings` are the titles of those the operator did not dismiss.

    Of one of the loop's own PRs reviewed in each persona of `[personas] reviewers` (DESIGN §31), a `done` one stands
    for every persona's latest `done` review of its commit together: their kept findings, the gravest impact, and the
    time the last of them ended.
    """

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
    #: Only one of the loop's own PRs under `[personas] reviewers` has it: the personas with no `done` review of
    #: `latest`'s commit yet, which the commit waits on.
    owed: NotRequired[list[str]]


class RequestedPR(TypedDict):
    """A PR with the operator's open review request: reviewed once at its head, then the request ends."""

    url: str
    requested_at: str
    review_runs: int
    granted: NotRequired[int]
    latest: LatestReview | None


class LatestRevision(TypedDict):
    """A draft's latest revision: how it ended, or that it runs."""

    run_id: int
    status: str
    started_at: str
    ended_at: str | None


class WantedRevision(TypedDict):
    """A review's draft the operator's note asks a revision of (DESIGN §34): never the note's or the draft's text."""

    #: The review whose draft it is, which `canopy review revise --run` names.
    review_run: int
    pr: str
    #: The commit the review read, which the revision reads too.
    sha: str
    repo: str | None
    #: When the newest note was written.
    noted_at: str
    #: The draft's revisions so far, however they ended, and how many it may have.
    revisions: int
    limit: int
    latest: LatestRevision | None


class ReviewsSection(TypedDict):
    """The state block's `reviews` (DESIGN §21)."""

    agent_prs: bool
    query: str | None
    low_impact: bool
    limits: Limits
    running: list[RunningReview]
    prs: list[ReviewedPR]
    requests: list[RequestedPR]
    #: Only when a note asks for one: the drafts to revise.
    revisions: NotRequired[list[WantedRevision]]


def state_section(conn: sqlite3.Connection, config: Config, now: datetime) -> ReviewsSection | None:
    """Return the state block's `reviews`, or None when reviews are off: then the block has no such key.

    A revision the operator's note asks for keeps the key, with reviews otherwise off (DESIGN §34).
    """
    if not review_requests.reviews_on(conn, config) and not review_revisions.on(conn, config):
        return None
    runs = review_runs.review_runs_since(conn, db.format_time(now - RECENT))
    by_pr: dict[str, list[records.ReviewRun]] = {}
    for run in runs:
        by_pr.setdefault(run.pr_url, []).append(run)
    prs = [_pr_summary(conn, config, url) for url in list(by_pr)[:MAX_PRS]]
    # The daily limit counts revisions too: each is a review run.
    started_today = len(review_runs.review_runs_since(conn, db.format_time(now - timedelta(hours=24)), revisions=True))
    revisions = [_wanted(w) for w in review_revisions.wanted(conn, config)]
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
        "requests": [_requested(conn, r) for r in review_requests.open_requests(conn)],
        **({"revisions": revisions} if revisions else {}),
    }


def _wanted(wanted: review_revisions.Wanted) -> WantedRevision:
    latest = wanted.revisions[0] if wanted.revisions else None
    return {
        "review_run": wanted.review.id,
        "pr": wanted.review.pr_url,
        "sha": wanted.review.sha,
        "repo": wanted.review.repo,
        "noted_at": wanted.notes[-1].created_at if wanted.notes else wanted.draft.created_at,
        "revisions": len(wanted.revisions),
        "limit": wanted.limit,
        "latest": (
            {
                "run_id": latest.id,
                "status": latest.status,
                "started_at": latest.started_at,
                "ended_at": latest.ended_at,
            }
            if latest is not None
            else None
        ),
    }


def _requested(conn: sqlite3.Connection, request: records.ReviewRequest) -> RequestedPR:
    url = request.pr_url
    runs = review_runs.review_runs_of(conn, url)
    granted = grants.granted(conn, url)
    return {
        "url": url,
        "requested_at": request.created_at,
        "review_runs": len(runs),
        **({"granted": granted} if granted else {}),
        "latest": _latest(conn, runs[0]) if runs else None,
    }


def _pr_summary(conn: sqlite3.Connection, config: Config, url: str) -> ReviewedPR:
    runs = review_runs.review_runs_of(conn, url)
    granted = grants.granted(conn, url)
    ticket = next((r.ticket_key for r in runs if r.ticket_key), None)
    latest = runs[0]
    chosen: list[str] = personas.reviewers_of(conn, config, ticket) if ticket is not None else []
    # Each persona's latest `done` review of the latest's commit, which a `done` latest stands for together (§31).
    newest = {r.persona: r for r in reversed(runs) if r.sha == latest.sha and r.status is ReviewRunStatus.DONE}
    together = [newest[p] for p in dict.fromkeys([latest.persona, *chosen]) if p in newest] if chosen else []
    return {
        "url": url,
        "ticket": ticket,
        "review_runs": len(runs),
        # Only a PR the operator granted more reviews has the key: its limit is the policy's plus this.
        **({"granted": granted} if granted else {}),
        "latest": _latest(conn, latest, together),
        **({"owed": review_start.owed_by(runs, latest.sha, chosen)} if chosen else {}),
    }


#: How grave each impact is, for the gravest of reviews read together.
_IMPACTS = ("low", "normal", "high")


def _latest(
    conn: sqlite3.Connection,
    latest: records.ReviewRun,
    together: Sequence[records.ReviewRun] = (),
) -> LatestReview:
    reviews = together if latest.status is ReviewRunStatus.DONE and together else [latest]
    kept: list[str] = []
    dismissed_count = 0
    verdicts: list[str] = []
    impacts: list[str] = []
    for run in reviews:
        stored = result.stored(run.result_json)
        # The operator's dismissals hold a finding back from workers and from the overseer alike (DESIGN §21).
        dismissed = review_runs.review_dismissals(conn, run.id)
        findings: list[result.Finding] = stored.findings if stored is not None else []
        kept.extend(f.title for i, f in enumerate(findings, 1) if i not in dismissed)
        dismissed_count += len(dismissed)
        if stored is not None and stored.verdict is not None:
            verdicts.append(stored.verdict)
        if stored is not None and stored.impact is not None:
            impacts.append(stored.impact)
    ended = max((r.ended_at for r in reviews if r.ended_at is not None), default=None)
    return {
        "run_id": latest.id,
        "sha": latest.sha,
        "status": latest.status,
        "verdict": ("findings" if "findings" in verdicts else verdicts[0]) if verdicts else None,
        "impact": max(impacts, key=_IMPACTS.index) if impacts else None,
        "findings": kept,
        "dismissed_findings": dismissed_count,
        "started_at": latest.started_at,
        "ended_at": ended,
        # The review's time for the `review` cursor, which takes whole seconds only (DESIGN §7).
        "reviewed_at": _to_second(ended),
    }


def _to_second(stamp: str | None) -> str | None:
    """A time the journal wrote, `...T12:00:00.123Z`, as the `review` cursor's `...T12:00:00Z`.

    Returns:
        `stamp` cut to whole seconds, or None when there is no `stamp`.
    """
    return f"{stamp[:19]}Z" if stamp else None
