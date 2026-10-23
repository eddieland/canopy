"""The reviews canopy keeps, as the web UI shows them (DESIGN §21): a shadow PR review, posted nowhere (D114).

Reads only; dismissing a finding goes through `canopy.core.conversation`, as `canopy dismiss review:ID` does, and so
does marking one seen, as its page does (`api/seen.py`). A review of a PR the loop does not own carries its draft
(`review_draft_views`, DESIGN §34), which posts only what the operator publishes.
Everything a review holds is untrusted: the reviewer read the PR, the diff is the PR's own text, and its transcript and
log are the reviewer's output. Text goes out with
control characters dropped, as every page's does, and the diff within `review_diff`'s bounds.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from canopy.core import (
    contract,
    conversation,
    db,
    review_diff,
    review_drafts,
    review_requests,
    review_runs,
)
from canopy.core import review_result as result
from canopy.core.vocab import DismissalReason, ReviewRunStatus, SeenKind
from canopy.serve import review_draft_views
from canopy.serve.schema.review import (
    DiffFile,
    DiffHunk,
    DiffLine,
    DismissalReasonName,
    FindingSeverity,
    RequestedReview,
    ReviewDetail,
    ReviewDiff,
    ReviewDraftStatusName,
    ReviewFinding,
    ReviewSummary,
)
from canopy.serve.transcript_views import raw_output, removed_after, session_transcript
from canopy.serve.views import lines, models_served, new_tokens, review_state, shown_path, ticket_title

if TYPE_CHECKING:
    import sqlite3

    from canopy.core import records
    from canopy.core.context import Context
    from canopy.serve.schema.transcript import RawOutput, Transcript

# How many review runs the reviews list carries, newest first.
RECENT_REVIEWS = 100
# Most severe first: a review's worst finding is the first of these it reported.
_SEVERITIES: tuple[FindingSeverity, ...] = ("blocking", "major", "minor")


def reviews(ctx: Context) -> list[ReviewSummary]:
    """The latest review runs, newest first.

    Returns:
        At most `RECENT_REVIEWS` runs, each as the reviews list shows it.
    """
    return summaries(ctx.conn, review_runs.recent_review_runs(ctx.conn, RECENT_REVIEWS))


def requested(ctx: Context) -> list[RequestedReview]:
    """The PRs the operator asked canopy to review that wait on a tick to start the review, newest first.

    Returns:
        Each open request no review of its PR is running for: one that started shows in `reviews` instead.
    """
    waiting = review_requests.waiting_requests(ctx.conn)
    prs = review_draft_views.observed_prs(ctx.conn, {r.pr_url for r in waiting})
    return [
        RequestedReview(
            pr_url=r.pr_url,
            created_at=db.parse_time(r.created_at),
            channel=r.channel,
            author=prs[r.pr_url].author if r.pr_url in prs else None,
        )
        for r in waiting
    ]


def review(ctx: Context, run_id: int) -> ReviewDetail | None:
    """One review run in full, or None if there is no such run.

    Returns:
        The run with its ticket's title, summary, harness note, findings, the diff it reviewed if that was kept, and
        every review run of the same PR; or None.
    """
    row = review_runs.get_review_run(ctx.conn, run_id)
    if row is None:
        return None
    stored = result.stored(row.result_json)
    dismissed = review_runs.review_dismissals(ctx.conn, run_id)
    note = contract.stored_object(row.result_json).get("harness")
    kept = review_diff.path_for(row.log_path)
    found = review_diff.read(kept)
    diff = diff_view(found) if found is not None else None
    ticket = db.get_ticket(ctx.conn, row.ticket_key) if row.ticket_key else None
    return ReviewDetail(
        review=summaries(ctx.conn, [row])[0],
        ticket_title=ticket_title(ticket.title) if ticket is not None else None,
        summary=lines(stored.summary) or None if stored is not None else None,
        note=lines(note) or None if isinstance(note, str) else None,
        base_branch=row.base_branch or None,
        findings=[_finding(f, found, i, dismissed) for i, f in enumerate(stored.findings, 1)]
        if stored is not None
        else [],
        diff=diff,
        diff_removed_after_days=removed_after(ctx.conn, kept, row.ended_at, "run_files_days"),
        runs=summaries(ctx.conn, review_runs.review_runs_of(ctx.conn, row.pr_url)),
        sendable=row.status is ReviewRunStatus.DONE and conversation.own_pr(ctx.conn, row),
        draft=review_draft_views.of_review(ctx.conn, ctx.config, row, found),
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

    The reviewer's events reach the log as it prints them, so a running review's transcript is what it did so far.

    Returns:
        The transcript, its status saying whether the run recorded a session and whether its log could be read.
    """
    row = review_runs.get_review_run(ctx.conn, run_id)
    if row is None:
        return None
    log = Path(row.log_path)
    return session_transcript(log, row.session_id, removed_after(ctx.conn, log, row.ended_at, "run_files_days"))


def review_raw_output(ctx: Context, run_id: int) -> RawOutput | None:
    """The end of a review run's log as written, the reviewer's stderr and exit included.

    Returns:
        The tail, without control characters, or a `no_output` status when the log is missing or not a regular file;
        None if there is no such run.
    """
    row = review_runs.get_review_run(ctx.conn, run_id)
    if row is None:
        return None
    log = Path(row.log_path)
    return raw_output(log, removed_after(ctx.conn, log, row.ended_at, "run_files_days"))


def summaries(conn: sqlite3.Connection, rows: Sequence[records.ReviewRun]) -> list[ReviewSummary]:
    """Review runs' rows, as the reviews list shows them, each with whether it is seen, its draft, and its request.

    Returns:
        A summary of each, in their order.
    """
    seen = db.seen_among(conn, SeenKind.REVIEW, [str(row.id) for row in rows])
    # A PR's title as its pages give it: its own, as a worker or a review reported it, else as canopy's reader last
    # read it, which is all a coworker's PR may have, else its ticket's.
    own = db.pr_titles(conn, {row.pr_url for row in rows})
    read = {url: pr.title for url, pr in review_draft_views.observed_prs(conn, {row.pr_url for row in rows}).items()}
    tickets = db.ticket_titles(conn, {row.ticket_key for row in rows if row.ticket_key})
    drafts = review_drafts.of_reviews(conn, [row.id for row in rows])
    asked = review_requests.answered_by(conn, rows)
    return [
        summary(
            row,
            seen=str(row.id) in seen,
            title=ticket_title(own.get(row.pr_url))
            or ticket_title(read.get(row.pr_url))
            or ticket_title(tickets.get(row.ticket_key or "")),
            draft=drafts.get(row.id),
            request=asked.get(row.id),
        )
        for row in rows
    ]


def summary(
    row: records.ReviewRun,
    *,
    seen: bool,
    title: str | None,
    draft: records.ReviewDraft | None,
    request: int | None,
) -> ReviewSummary:
    """One review run's row, as the reviews list shows it, `seen` when the operator has seen it, its PR's `title`.

    `request` is the id of the operator's request it answers, which groups it with its reviews in other personas.

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
        state=review_state(row.status),
        verdict=stored.verdict if stored is not None else None,
        impact=stored.impact if stored is not None else None,
        findings=len(stored.findings) if stored is not None else 0,
        worst=worst,
        worst_count=sum(f.severity == worst for f in stored.findings) if stored is not None else 0,
        started_at=db.parse_time(row.started_at),
        ended_at=db.parse_time(row.ended_at) if row.ended_at else None,
        cost_usd=row.cost_usd,
        persona=row.persona,
        request_id=request,
        news=review_requests.has_news(row, stored),
        seen=seen,
        draft=cast("ReviewDraftStatusName", draft.status.value) if draft is not None else None,
    )


def _worst(findings: Iterable[result.Finding]) -> FindingSeverity | None:
    found = {f.severity for f in findings}
    return next((s for s in _SEVERITIES if s in found), None)


def _finding(
    f: result.Finding,
    diff: review_diff.Diff | None,
    number: int,
    dismissed: Mapping[int, DismissalReason | None],
) -> ReviewFinding:
    file, line = review_diff.anchor(diff, f.location) if diff is not None else (None, None)
    reason = dismissed.get(number)
    return ReviewFinding(
        severity=f.severity,
        title=lines(f.title),
        location=lines(f.location),
        detail=lines(f.detail),
        file=file,
        line=line,
        dismissed=number in dismissed,
        dismissed_reason=cast("DismissalReasonName", reason.value) if reason is not None else None,
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
