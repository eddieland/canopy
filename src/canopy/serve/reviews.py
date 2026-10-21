"""The reviews canopy keeps, as the web UI shows them (DESIGN §21): a shadow PR review, posted nowhere (D114).

Reads only; dismissing a finding goes through `canopy.core.conversation`, as `canopy dismiss review:ID` does, and so
does marking one seen, as its page does (`api/seen.py`).
Everything a review holds is untrusted: the reviewer read the PR, the diff is the PR's own text, and its transcript and
log are the reviewer's output. Text goes out with
control characters dropped, as every page's does, and the diff within `review_diff`'s bounds.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from canopy.core import contract, conversation, db, review_diff, review_requests
from canopy.core import review_result as result
from canopy.core.vocab import ReviewRunStatus, SeenKind
from canopy.serve.schema import (
    DiffFile,
    DiffHunk,
    DiffLine,
    FindingSeverity,
    RawOutput,
    RequestedReview,
    ReviewDetail,
    ReviewDiff,
    ReviewFinding,
    ReviewSummary,
    RunState,
    Transcript,
)
from canopy.serve.views import (
    lines,
    models_served,
    new_tokens,
    raw_output,
    session_transcript,
    shown_path,
    ticket_title,
)

if TYPE_CHECKING:
    import sqlite3

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
    return summaries(ctx.conn, db.recent_review_runs(ctx.conn, RECENT_REVIEWS))


def requested(ctx: Context) -> list[RequestedReview]:
    """The PRs the operator asked canopy to review that wait on a tick to start the review, newest first.

    Returns:
        Each open request no review of its PR is running for: one that started shows in `reviews` instead.
    """
    return [
        RequestedReview(pr_url=r.pr_url, created_at=db.parse_time(r.created_at), channel=r.channel)
        for r in review_requests.waiting_requests(ctx.conn)
    ]


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
        review=summaries(ctx.conn, [row])[0],
        ticket_title=ticket_title(ticket.title) if ticket is not None else None,
        summary=lines(stored.summary) or None if stored is not None else None,
        note=lines(note) or None if isinstance(note, str) else None,
        base_branch=row.base_branch or None,
        findings=[_finding(f, found, i in dismissed) for i, f in enumerate(stored.findings, 1)]
        if stored is not None
        else [],
        diff=diff,
        runs=summaries(ctx.conn, db.review_runs_of(ctx.conn, row.pr_url)),
        sendable=row.status is ReviewRunStatus.DONE and conversation.own_pr(ctx.conn, row),
        new_tokens=new_tokens(row),
        peak_context=row.tokens_peak_context,
        log_path=shown_path(row.log_path, ctx.workspace.root),
        persona=row.persona,
        persona_digest=row.persona_digest,
        models=models_served(
            ctx.conn,
            "review_runs",
            run_id,
            ended=row.ended_at is not None,
            session_id=row.session_id or None,
        ),
    )


def review_transcript(ctx: Context, run_id: int) -> Transcript | None:
    """A review run's session in its log, or None if there is no such run.

    The reviewer's output reaches the log when it ends, so a running review's transcript has no session yet.

    Returns:
        The transcript, its status saying whether the run recorded a session and whether its log could be read.
    """
    row = db.get_review_run(ctx.conn, run_id)
    if row is None:
        return None
    return session_transcript(Path(row.log_path), row.session_id)


def review_raw_output(ctx: Context, run_id: int) -> RawOutput | None:
    """The end of a review run's log as written, the reviewer's stderr and exit included.

    Returns:
        The tail, without control characters, or a `no_output` status when the log is missing or not a regular file;
        None if there is no such run.
    """
    row = db.get_review_run(ctx.conn, run_id)
    if row is None:
        return None
    return raw_output(Path(row.log_path))


def summaries(conn: sqlite3.Connection, rows: Sequence[records.ReviewRun]) -> list[ReviewSummary]:
    """Review runs' rows, as the reviews list shows them, each saying whether the operator has seen it.

    Returns:
        A summary of each, in their order.
    """
    seen = db.seen_among(conn, SeenKind.REVIEW, [str(row.id) for row in rows])
    # A PR's title as its pages give it: its own, else its ticket's.
    own = db.pr_titles(conn, {row.pr_url for row in rows})
    tickets = db.ticket_titles(conn, {row.ticket_key for row in rows if row.ticket_key})
    return [
        summary(
            row,
            seen=str(row.id) in seen,
            title=ticket_title(own.get(row.pr_url)) or ticket_title(tickets.get(row.ticket_key or "")),
        )
        for row in rows
    ]


def summary(row: records.ReviewRun, *, seen: bool, title: str | None) -> ReviewSummary:
    """One review run's row, as the reviews list shows it, `seen` when the operator has seen it, its PR's `title`.

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
        title=title,
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
        news=review_requests.has_news(row, stored),
        seen=seen,
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
