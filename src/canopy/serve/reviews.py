"""The reviews canopy keeps, as the web UI shows them (DESIGN §21): a shadow PR review, posted nowhere (D114).

Reads only; dismissing a finding goes through `canopy.core.conversation`, as `canopy dismiss review:ID` does.
Everything a review holds is untrusted: the reviewer read the PR, and the diff is the PR's own text. Text goes out with
control characters dropped, as every page's does, and the diff within `review_diff`'s bounds.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, assert_never

from canopy.core import contract, conversation, db, review_diff
from canopy.core import review_result as result
from canopy.core.vocab import ReviewRunStatus
from canopy.serve.schema import (
    DiffFile,
    DiffHunk,
    DiffLine,
    FindingSeverity,
    ReviewDetail,
    ReviewDiff,
    ReviewFinding,
    ReviewSummary,
    RunState,
)
from canopy.serve.views import lines, ticket_title

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

# How many review runs the reviews list carries, newest first.
RECENT_REVIEWS = 100
# Most severe first: a review's worst finding is the first of these it reported.
_SEVERITIES: tuple[FindingSeverity, ...] = ("blocking", "major", "minor")


def reviews(ctx: Context) -> list[ReviewSummary]:
    """The latest review runs, newest first.

    Returns:
        At most `RECENT_REVIEWS` runs, each as the reviews list shows it.
    """
    return [summary(r) for r in db.recent_review_runs(ctx.conn, RECENT_REVIEWS)]


def review(ctx: Context, run_id: int) -> ReviewDetail | None:
    """One review run in full, or None if there is no such run.

    Returns:
        The run with its ticket's title, summary, harness note, findings, the diff it reviewed if that was kept, and
        every review run of the same PR; or None.
    """
    row = db.get_review_run(ctx.conn, run_id)
    if row is None:
        return None
    stored = result.stored(row.result_json)
    dismissed = db.review_dismissals(ctx.conn, run_id)
    note = contract.stored_object(row.result_json).get("harness")
    found = review_diff.read(review_diff.path_for(row.log_path))
    diff = diff_view(found) if found is not None else None
    ticket = db.get_ticket(ctx.conn, row.ticket_key) if row.ticket_key else None
    return ReviewDetail(
        review=summary(row),
        ticket_title=ticket_title(ticket.title) if ticket is not None else None,
        summary=lines(stored.summary) or None if stored is not None else None,
        note=lines(note) or None if isinstance(note, str) else None,
        base_branch=row.base_branch or None,
        findings=[_finding(f, found, i in dismissed) for i, f in enumerate(stored.findings, 1)]
        if stored is not None
        else [],
        diff=diff,
        runs=[summary(r) for r in db.review_runs_of(ctx.conn, row.pr_url)],
        sendable=row.status is ReviewRunStatus.DONE and conversation.own_pr(ctx.conn, row),
    )


def summary(row: records.ReviewRun) -> ReviewSummary:
    """One review run's row, as the reviews list shows it.

    Returns:
        The run's summary. Its verdict and impact are None, and its findings 0, when it has no valid result.
    """
    stored = result.stored(row.result_json)
    worst = _worst(stored.findings) if stored is not None else None
    return ReviewSummary(
        id=row.id,
        pr_url=row.pr_url,
        sha=row.sha,
        ticket_key=row.ticket_key or None,
        repo=row.repo or None,
        status=row.status,
        state=_review_state(row.status),
        verdict=stored.verdict if stored is not None else None,
        impact=stored.impact if stored is not None else None,
        findings=len(stored.findings) if stored is not None else 0,
        worst=worst,
        worst_count=sum(f.severity == worst for f in stored.findings) if stored is not None else 0,
        started_at=db.parse_time(row.started_at),
        ended_at=db.parse_time(row.ended_at) if row.ended_at else None,
        cost_usd=row.cost_usd,
    )


def _review_state(status: ReviewRunStatus) -> RunState:
    """What the web UI colors a review run that has `status` as.

    Returns:
        The run's state: every ending but `done` is failed.
    """
    match status:
        case ReviewRunStatus.RUNNING:
            return "running"
        case ReviewRunStatus.DONE:
            return "done"
        case ReviewRunStatus.FAILED | ReviewRunStatus.UNKNOWN | ReviewRunStatus.TIMEOUT | ReviewRunStatus.CRASHED:
            return "failed"
        case _:
            assert_never(status)


def _worst(findings: Iterable[result.Finding]) -> FindingSeverity | None:
    found = {f.severity for f in findings}
    return next((s for s in _SEVERITIES if s in found), None)


def _finding(f: result.Finding, diff: review_diff.Diff | None, dismissed: bool) -> ReviewFinding:  # noqa: FBT001
    file, line = review_diff.anchor(diff, f.location) if diff is not None else (None, None)
    return ReviewFinding(
        severity=f.severity,
        title=lines(f.title),
        location=lines(f.location),
        detail=lines(f.detail),
        file=file,
        line=line,
        dismissed=dismissed,
    )


def diff_view(diff: review_diff.Diff) -> ReviewDiff:
    """Return a kept diff as the web UI reads it: a review's, or a run's at its pushed head (DESIGN §21, §29)."""
    return ReviewDiff(
        files=[
            DiffFile(
                path=f.path,
                old_path=f.old_path,
                binary=f.binary,
                hunks=[
                    DiffHunk(
                        header=h.header,
                        lines=[DiffLine(kind=ln.kind, old=ln.old, new=ln.new, text=ln.text) for ln in h.lines],
                    )
                    for h in f.hunks
                ],
            )
            for f in diff.files
        ],
        truncated=diff.truncated,
    )
