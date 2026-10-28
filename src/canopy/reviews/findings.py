"""A review's findings as a resumed worker, a later review, and a reviser read them (DESIGN §21, §34).

They come from the journal, since nothing is posted but what the operator publishes (D114).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from canopy.core import contract, db, review_answers, review_requests, review_runs
from canopy.core import review_result as result
from canopy.core.vocab import HoldKind, ReviewRunStatus, SeenKind
from canopy.infra.text import printable, quoted

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Mapping, Sequence

    from canopy.core import records
    from canopy.core.vocab import DismissalReason


class Unusable(Exception):  # noqa: N818  (the dispatch records it as a refusal)
    """The review run is missing, or cannot go to this worker: not this ticket's, not `done`, or without findings."""


def for_worker(conn: sqlite3.Connection, run_id: int, key: str, repos: Sequence[str]) -> str:
    """Return `{{REVIEW_FINDINGS}}` for a `resume` of `key` in `repos`: review run `run_id`'s findings, as data.

    A finding the operator dismissed, or one canopy holds for them, is left out; the rest keep their numbers. Each other
    persona's latest `done` review of the same commit adds its own (DESIGN §31), so a resume addresses every review of
    the commit at once.

    Raises:
        Unusable: the run is missing, of another ticket or repository, not `done`, or found nothing it has not had
            dismissed or held.
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
    dismissed, withheld = review_runs.review_dismissals(conn, run_id), review_runs.withheld(conn, run_id)
    if len(dismissed) >= len(stored.findings):
        raise Unusable(f"the operator dismissed every finding of review run {run_id}: none is left to address")
    if len(withheld) >= len(stored.findings):
        raise Unusable(
            f"every finding of review run {run_id} the operator did not dismiss is held for them, a rebuttal of a "
            "worker's decline or a late one: none is left to address until they send one",
        )
    beside = [(r, result.stored(r.result_json), review_runs.withheld(conn, r.id)) for r in _beside(conn, run)]
    kept = [(r, found, left) for r, found, left in beside if found is not None and len(left) < len(found.findings)]
    lines = _found_by(run, stored, withheld, named=bool(kept))
    for other, found, left in kept:
        lines.extend(["", *_found_by(other, found, left, named=True)])
    return "\n".join(lines)


def for_reviewer(conn: sqlite3.Connection, pr_url: str, *, before: int) -> str | None:
    """Return `{{PREVIOUS_REVIEW}}` for a review of `pr_url`: its latest `done` review before run `before`, as data.

    A finding the operator dismissed is left out, as it is for a worker; the rest keep their numbers. Under each, the
    answer the latest worker handed it gave, `fixed` or `declined` with its reason, quoted as the worker's (DESIGN
    §21); one canopy holds for the operator is marked so, for them to settle rather than the next review.

    Returns:
        That review's verdict, summary, and findings; None when the PR has no `done` review before this one.
    """
    found = review_answers.previous(conn, pr_url, before=before)
    if found is None:
        return None
    run, stored = found
    return _review_block(conn, run, stored, answers=review_answers.latest(conn, run.id))


def for_reviser(conn: sqlite3.Connection, run: records.ReviewRun) -> str:
    """Return `{{REVIEW}}` for a revision of review run `run`'s draft (DESIGN §34): the review, as data.

    A finding the operator dismissed is left out, as it is for a later review; the rest keep their numbers.

    Returns:
        The review's verdict, summary, and findings; a line saying it kept no result, if it has none.
    """
    stored = result.stored(run.result_json)
    if stored is None:
        return f"canopy's review run {run.id} of this PR, at commit `{run.sha}`, kept no result."
    return _review_block(conn, run, stored)


def _review_block(
    conn: sqlite3.Connection,
    run: records.ReviewRun,
    stored: result.ReviewResult,
    *,
    answers: Mapping[int, records.ReviewAnswer] | None = None,
) -> str:
    # A `done` review for another agent to read: its verdict, its summary, and the findings the operator kept, quoted,
    # each with the worker's answer to it among `answers`, and marked when canopy holds it for the operator.
    lines = [
        (
            f"canopy's review run {run.id} of this PR, at commit `{run.sha}`, ended with verdict {stored.verdict}, "
            f"impact {stored.impact}."
        ),
    ]
    if stored.summary:
        lines += ["", "Its summary:", quoted(stored.summary)]
    kept = _findings(
        stored,
        review_runs.review_dismissals(conn, run.id),
        keep_dismissed=False,
        held=review_runs.held(conn, run.id),
        answers=answers,
    )
    if kept:
        lines += ["", "Its findings:", *kept]
    elif stored.findings:
        lines += ["", "Its findings: none the operator kept."]
    return "\n".join(lines)


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
            dismissed, held = review_runs.review_dismissals(conn, run_id), review_runs.held(conn, run_id)
            answers = review_answers.latest(conn, run_id)
            lines += ["", *_findings(stored, dismissed, keep_dismissed=True, held=held, answers=answers)]
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
    withheld: Collection[int],
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
        *_findings(stored, dict.fromkeys(withheld), keep_dismissed=False),
    ]


def _findings(
    stored: result.ReviewResult,
    dismissed: Mapping[int, DismissalReason | None],
    *,
    keep_dismissed: bool,
    held: Mapping[int, records.ReviewHold] | None = None,
    answers: Mapping[int, records.ReviewAnswer] | None = None,
) -> list[str]:
    # Every string here is the reviewer's or a worker's, which read hostile text: printable, so it cannot move a
    # terminal's cursor, and a worker's reason quoted, so no line of it passes for the prompt's own.
    lines: list[str] = []
    held, answers = held or {}, answers or {}
    for i, f in enumerate(stored.findings, 1):
        if i in dismissed and not keep_dismissed:
            continue
        where = f" `{printable(f.location)}`" if f.location else ""
        reason = dismissed.get(i)
        mark = f" (dismissed: {reason})" if reason is not None else " (dismissed)" if i in dismissed else ""
        if (hold := held.get(i)) is not None:
            mark += f" (held for the operator: {_held_for(hold)})"
        lines.append(f"{i}. **{f.severity}**{where}: {printable(f.title)}{mark}")
        lines.extend(f"   > {line}" for line in printable(f.detail).splitlines())
        if (answer := answers.get(i)) is not None:
            lines.append(f"   The author's answer: {answer.answer}{':' if answer.reason else '.'}")
            lines.extend(f"   > {line}" for line in printable(answer.reason or "").splitlines())
    return lines


def _held_for(hold: records.ReviewHold) -> str:
    # Why canopy holds a finding, as its mark says it.
    match hold.kind:
        case HoldKind.REBUTTAL:
            rebuts = f"finding {hold.rebuts_finding} of review run {hold.rebuts_run_id}"
            return f"it rebuts the author's decline of {rebuts}"
        case HoldKind.LATE:
            return "it is on code unchanged since the PR's first reviewed commit"
        case _:
            assert_never(hold.kind)
