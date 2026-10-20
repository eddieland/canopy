"""The PRs the journal knows, as the web UI's pull requests pages show them (DESIGN §22).

A PR is the subject here: the loop's own, by their tickets' units, every one canopy reviewed, and every one the operator
asked canopy to review. Its page gathers what the journal holds about it from elsewhere: the operator's review request,
the runs that pushed to it, canopy's reviews of it, which open the reviews pages (reviews.py), and the decisions naming
it. Reads only; a rationale and a run's summary are untrusted text.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING

from canopy.core import contract, conversation, db, review_requests
from canopy.serve import threads
from canopy.serve.reviews import summaries
from canopy.serve.schema import CostTotal, PullRequest, PullRequestDetail, ReviewRequest
from canopy.serve.views import decision, limit, run

if TYPE_CHECKING:
    import sqlite3

    from canopy.core import records
    from canopy.core.context import Context
    from canopy.serve.backend import Backend

# The PRs list, by most recent activity, and how many runs and decisions a PR's page carries.
PULL_REQUESTS = 100
PR_RUNS = 20
PR_DECISIONS = 20


def pull_requests(ctx: Context) -> list[PullRequest]:
    """The PRs the journal knows, most recent activity first.

    Returns:
        At most `PULL_REQUESTS`: the loop's own, by their units, reviewed or not, and every one canopy reviewed.
    """
    rows = db.pull_requests(ctx.conn, PULL_REQUESTS)
    reviews = db.review_runs_of_prs(ctx.conn, [str(r["url"]) for r in rows])
    return [_pull_request(ctx.conn, r, reviews.get(str(r["url"]), [])) for r in rows]


def pull_request(backend: Backend, ctx: Context, url: str) -> PullRequestDetail | None:
    """One PR: the runs that pushed to it, its review runs and limit, and the decisions naming it.

    Returns:
        The PR's page, or None when no unit, review run, or decision names it. One that only decisions name, such as
        a `review.query` match no review has run on yet, has a page with its decisions alone.
    """
    rows = db.pull_requests(ctx.conn, 1, url=url)
    decisions = db.decisions_about_pr(ctx.conn, url, PR_DECISIONS)
    reviews = db.review_runs_of(ctx.conn, url)
    if rows:
        found = _pull_request(ctx.conn, rows[0], reviews)
    elif decisions:
        found = PullRequest(url=url, active_at=db.parse_time(decisions[0].created_at))
    else:
        return None
    runs: list[sqlite3.Row] = _runs(ctx.conn, found.ticket_key, url) if found.ticket_key is not None else []
    reviewed = backend.review_limit(ctx, url)
    return PullRequestDetail(
        pull_request=found,
        review_limit=limit(reviewed, repo=found.repo) if reviewed is not None else None,
        runs=[run(r, ctx.workspace.root) for r in runs[:PR_RUNS]],
        reviews=summaries(ctx.conn, reviews),
        decisions=[decision(d) for d in decisions],
        cost=_cost(runs, reviews),
        threads=threads.known(ctx.conn, url),
    )


def review_request(row: records.ReviewRequest) -> ReviewRequest:
    """A review request as the API shows it.

    Returns:
        The request: when and where it was made, its notes, and when and why it ended, if it has.
    """
    return ReviewRequest.model_validate(
        {
            "created_at": db.parse_time(row.created_at),
            "channel": row.channel,
            "ended_at": db.parse_time(row.ended_at) if row.ended_at else None,
            "end_reason": row.end_reason,
            "notes": row.notes,
        }
    )


def _pull_request(conn: sqlite3.Connection, row: sqlite3.Row, reviews: Sequence[records.ReviewRun]) -> PullRequest:
    # A PR no unit records takes its ticket and repository from its reviews: an agent PR's ticket may be forgotten.
    request = review_requests.latest_request(conn, str(row["url"]))
    key = row["ticket_key"] or next((r.ticket_key for r in reviews if r.ticket_key), None)
    repo = row["repo"] or next((r.repo for r in reviews if r.repo), None)
    running = db.running_run_of(conn, str(key)) if key else None
    return PullRequest(
        url=str(row["url"]),
        ticket_key=str(key) if key else None,
        ticket_title=_one_line(row["title"]),
        title=_one_line(row["pr_title"]),
        repo=str(repo) if repo else None,
        branch=str(row["branch"]) if row["branch"] else None,
        phase=str(row["phase"]) if row["phase"] else None,
        active_at=db.parse_time(str(row["active_at"])),
        running_run=running.id if running is not None else None,
        reviews=len(reviews),
        latest_review=summaries(conn, reviews[:1])[0] if reviews else None,
        review_request=review_request(request) if request is not None else None,
    )


def _one_line(text: object) -> str | None:
    found = " ".join(conversation.printable(str(text)).split()) if text else ""
    return found or None


def _runs(conn: sqlite3.Connection, key: str, url: str) -> list[sqlite3.Row]:
    # A run names the PRs it pushed to in its result; one still running has no result yet, so it is kept as well.
    # Every run of the ticket is read, not only the page's 20, so the PR's cost counts them all.
    return [
        r
        for r in db.runs_of(conn, key, None)
        if r["status"] == "running" or url in contract.stored_prs(contract.stored_object(r["result_json"]))
    ]


def _cost(runs: Collection[sqlite3.Row], reviews: Collection[records.ReviewRun]) -> CostTotal:
    # A run that pushed to two PRs, one per repository, counts on each one's page, and once on its ticket's.
    costs = [float(r["cost_usd"]) for r in runs if r["cost_usd"] is not None]
    costs += [r.cost_usd for r in reviews if r.cost_usd is not None]
    return CostTotal(
        runs=len(runs), reviews=len(reviews), priced=len(costs), cost_usd=math.fsum(costs) if costs else None
    )
