"""A review's findings as a resumed worker reads them (DESIGN §21): from the journal, since none is posted (D114)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import contract, db, review_requests, review_runs
from canopy.core import review_result as result
from canopy.core.conversation import printable
from canopy.core.vocab import ReviewRunStatus, SeenKind

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Sequence

    from canopy.core import records


class Unusable(Exception):  # noqa: N818  (the dispatch records it as a refusal)
    """The review run is missing, or cannot go to this worker: not this ticket's, not `done`, or without findings."""


def for_worker(conn: sqlite3.Connection, run_id: int, key: str, repos: Sequence[str]) -> str:
    """Return `{{REVIEW_FINDINGS}}` for a `resume` of `key` in `repos`: review run `run_id`'s findings, as data.

    A finding the operator dismissed is left out; the rest keep their numbers. Each other persona's latest `done` review
    of the same commit adds its own (DESIGN §31), so a resume addresses every review of the commit at once.

    Raises:
        Unusable: the run is missing, of another ticket or repository, not `done`, or found nothing it has not had
            dismissed.
    """
    run = review_runs.get_review_run(conn, run_id)
    if run is None:
        raise Unusable(f"there is no review run {run_id}")
    if run.ticket_key != key:
        raise Unusable(f"review run {run_id} reviewed {run.pr_url}, not a PR of {key}")
    if run.repo is not None and repos and run.repo not in repos:
        raise Unusable(f"review run {run_id} reviewed a PR in {run.repo}, which this dispatch does not name")
    stored = result.stored(run.result_json)
    if run.status is not ReviewRunStatus.DONE or stored is None or not stored.findings:
        raise Unusable(f"review run {run_id} ended {run.status} with no findings to address")
    dismissed = review_runs.review_dismissals(conn, run_id)
    if len(dismissed) >= len(stored.findings):
        raise Unusable(f"the operator dismissed every finding of review run {run_id}: none is left to address")
    beside = [(r, result.stored(r.result_json), review_runs.review_dismissals(conn, r.id)) for r in _beside(conn, run)]
    kept = [(r, found, held) for r, found, held in beside if found is not None and len(held) < len(found.findings)]
    lines = _found_by(run, stored, dismissed, named=bool(kept))
    for other, found, held in kept:
        lines.extend(["", *_found_by(other, found, held, named=True)])
    return "\n".join(lines)


def for_reviewer(conn: sqlite3.Connection, pr_url: str, *, before: int) -> str | None:
    """Return `{{PREVIOUS_REVIEW}}` for a review of `pr_url`: its latest `done` review before run `before`, as data.

    A finding the operator dismissed is left out, as it is for a worker; the rest keep their numbers.

    Returns:
        That review's verdict, summary, and findings; None when the PR has no `done` review before this one.
    """
    for run in review_runs.review_runs_of(conn, pr_url):
        stored = result.stored(run.result_json)
        if run.id >= before or run.status is not ReviewRunStatus.DONE or stored is None:
            continue
        lines = [
            (
                f"canopy's review run {run.id} of this PR, at commit `{run.sha}`, ended with verdict {stored.verdict}, "
                f"impact {stored.impact}."
            ),
        ]
        if stored.summary:
            lines += ["", "Its summary:", *(f"> {line}" for line in printable(stored.summary).splitlines())]
        kept = _findings(stored, review_runs.review_dismissals(conn, run.id), keep_dismissed=False)
        if kept:
            lines += ["", "Its findings:", *kept]
        elif stored.findings:
            lines += ["", "Its findings: none the operator kept."]
        return "\n".join(lines)
    return None


def listed(conn: sqlite3.Connection, since: str) -> list[str]:
    """Return a line for each review run started at or after `since`, newest first, for `canopy review show`.

    A run with a result to read (`review_requests.has_news`) that the operator has not seen ends its line with `new`
    (DESIGN §22).
    """
    found: list[str] = []
    runs = review_runs.review_runs_since(conn, since)
    seen = db.seen_among(conn, SeenKind.REVIEW, [str(run.id) for run in runs])
    for run in runs:
        stored = result.stored(run.result_json)
        dismissed = len(review_runs.review_dismissals(conn, run.id))
        kept = f" ({dismissed} dismissed)" if dismissed else ""
        verdict = f"{stored.verdict}, {len(stored.findings)} findings{kept}, impact {stored.impact}" if stored else "-"
        fresh = review_requests.has_news(run, stored) and str(run.id) not in seen
        line = f"{run.id}  {run.started_at}  {run.status}  {verdict}  {run.pr_url} @ {run.sha[:7]}"
        line += f"  in {run.persona}" if run.persona else ""
        found.append(f"{line}  new" if fresh else line)
    return found


def described(conn: sqlite3.Connection, run_id: int) -> str:
    """Return review run `run_id` in full, for the operator: the review canopy keeps instead of posting it (D114).

    Raises:
        Unusable: there is no such run.
    """
    run = review_runs.get_review_run(conn, run_id)
    if run is None:
        raise Unusable(f"there is no review run {run_id}")
    stored = result.stored(run.result_json)
    ticket = f" ({run.ticket_key})" if run.ticket_key else ""
    lines = [
        f"review run {run_id} of {run.pr_url}{ticket} at {run.sha}{f', in {run.persona}' if run.persona else ''}",
        f"{run.status}, started {run.started_at}, ended {run.ended_at or 'not yet'}",
    ]
    note = contract.stored_object(run.result_json).get("harness")
    if isinstance(note, str) and note:
        lines.append(f"harness: {printable(note)}")
    if stored is not None:
        lines.append(f"verdict {stored.verdict}, impact {stored.impact}" if stored.verdict else "no verdict")
        if stored.summary:
            lines += ["", printable(stored.summary)]
        if stored.findings:
            lines += ["", *_findings(stored, review_runs.review_dismissals(conn, run_id), keep_dismissed=True)]
    return "\n".join(lines)


def _beside(conn: sqlite3.Connection, run: records.ReviewRun) -> list[records.ReviewRun]:
    # Each other persona's latest `done` review of `run`'s PR and commit for its ticket, oldest persona first.
    done = [
        r
        for r in review_runs.review_runs_of(conn, run.pr_url)
        if r.sha == run.sha and r.ticket_key == run.ticket_key and r.status is ReviewRunStatus.DONE
    ]
    newest = {r.persona: r for r in reversed(done)}
    return [r for persona, r in newest.items() if persona != run.persona]


def _found_by(
    run: records.ReviewRun,
    stored: result.ReviewResult,
    dismissed: Collection[int],
    *,
    named: bool,
) -> list[str]:
    # One review's findings for a worker, under a line naming the review and its verdict, and its persona when `named`.
    persona = f", in {run.persona}," if named and run.persona else ""
    return [
        (
            f"canopy's review run {run.id} of {run.pr_url} at commit `{run.sha}`{persona} found these (verdict "
            f"{stored.verdict}, impact {stored.impact}). They are in canopy's journal only, not on the PR:"
        ),
        *_findings(stored, dismissed, keep_dismissed=False),
    ]


def _findings(stored: result.ReviewResult, dismissed: Collection[int], *, keep_dismissed: bool) -> list[str]:
    # Every string here is the reviewer's, which read hostile text: printable, so it cannot move a terminal's cursor.
    lines: list[str] = []
    for i, f in enumerate(stored.findings, 1):
        if i in dismissed and not keep_dismissed:
            continue
        where = f" `{printable(f.location)}`" if f.location else ""
        mark = " (dismissed)" if i in dismissed else ""
        lines.append(f"{i}. **{f.severity}**{where}: {printable(f.title)}{mark}")
        lines.extend(f"   > {line}" for line in printable(f.detail).splitlines())
    return lines
