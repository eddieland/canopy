"""The PRs the journal knows, as the web UI's pull requests pages show them (DESIGN §22).

A PR is the subject here: the loop's own, by their tickets' units, and every one canopy reviewed. Its page gathers what
the journal holds about it from elsewhere: the runs that pushed to it, canopy's reviews of it, which open the reviews
pages (reviews.py), and the decisions naming it. Reads only; a rationale and a run's summary are untrusted text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import contract, conversation, db
from canopy.serve.reviews import summary
from canopy.serve.schema import PullRequest, PullRequestDetail
from canopy.serve.views import decision, run

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context

# The PRs list, by most recent activity, and how many runs and decisions a PR's page carries.
PULL_REQUESTS = 100
PR_RUNS = 20
PR_DECISIONS = 20
# A ticket's runs read to find those that reported a PR: a ticket rarely has more, and the page shows at most 20.
_TICKET_RUNS = 100


def pull_requests(ctx: Context) -> list[PullRequest]:
    """The PRs the journal knows, most recent activity first.

    Returns:
        At most `PULL_REQUESTS`: the loop's own, by their units, reviewed or not, and every one canopy reviewed.
    """
    rows = db.pull_requests(ctx.conn, PULL_REQUESTS)
    reviews = db.review_runs_of_prs(ctx.conn, [str(r["url"]) for r in rows])
    return [_pull_request(ctx.conn, r, reviews.get(str(r["url"]), [])) for r in rows]


def pull_request(ctx: Context, url: str) -> PullRequestDetail | None:
    """One PR: the runs that pushed to it, its review runs, and the decisions naming it.

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
        found = PullRequest(url=url, active_at=db.parse_time(str(decisions[0]["created_at"])))
    else:
        return None
    runs: list[sqlite3.Row] = _runs(ctx.conn, found.ticket_key, url) if found.ticket_key is not None else []
    return PullRequestDetail(
        pull_request=found,
        runs=[run(r, ctx.workspace.root) for r in runs],
        reviews=[summary(r) for r in reviews],
        decisions=[decision(d) for d in decisions],
    )


def _pull_request(conn: sqlite3.Connection, row: sqlite3.Row, reviews: list[sqlite3.Row]) -> PullRequest:
    # A PR no unit records takes its ticket and repository from its reviews: an agent PR's ticket may be forgotten.
    key = row["ticket_key"] or next((r["ticket_key"] for r in reviews if r["ticket_key"]), None)
    repo = row["repo"] or next((r["repo"] for r in reviews if r["repo"]), None)
    title = " ".join(conversation.printable(str(row["title"])).split()) if row["title"] else ""
    running = db.running_run_of(conn, str(key)) if key else None
    return PullRequest(
        url=str(row["url"]),
        ticket_key=str(key) if key else None,
        ticket_title=title or None,
        repo=str(repo) if repo else None,
        branch=str(row["branch"]) if row["branch"] else None,
        phase=str(row["phase"]) if row["phase"] else None,
        active_at=db.parse_time(str(row["active_at"])),
        running_run=int(running["id"]) if running is not None else None,
        reviews=len(reviews),
        latest_review=summary(reviews[0]) if reviews else None,
    )


def _runs(conn: sqlite3.Connection, key: str, url: str) -> list[sqlite3.Row]:
    # A run names the PRs it pushed to in its result; one still running has no result yet, so it is kept as well.
    found = [
        r
        for r in db.runs_of(conn, key, _TICKET_RUNS)
        if r["status"] == "running" or url in contract.stored_prs(contract.stored_object(r["result_json"]))
    ]
    return found[:PR_RUNS]
