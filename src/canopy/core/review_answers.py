"""What a resumed worker answered of the review findings it was handed (DESIGN §21, Answers and rebuttals).

A `resume` handed canopy's review findings answers each in its result line's `review_answers` field: `fixed`, or
`declined` with its reason, naming the finding by its review run and number. `_run` checks each entry alone and records
those that pass with the run: a finding of one of its own ticket's `done` reviews, at most one answer each. The next
review of the PR reads them beside the findings as data, so it need not report a declined one again unless it can
rebut the reason, and a rebuttal is held for the operator (`review_runs.hold`). The reason is the worker's text, which
read the PR: it is shown as data, made printable, and authorizes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from canopy.core import contract, records, review_runs
from canopy.core import review_result as result
from canopy.core.vocab import FindingAnswer, ReviewRunStatus

if TYPE_CHECKING:
    import sqlite3

#: The placeholder of the result field's contract, which a resume handed review findings carries.
REVIEW_ANSWERS = "REVIEW_ANSWERS"
#: How many answers a run's result may carry: every finding of a review in each of a few personas.
MAX_ANSWERS = 4 * result.MAX_FINDINGS
#: How long a reason may be.
MAX_REASON = 1000
#: How many refused entries a note names; the rest are counted.
MAX_NAMED = 10


class _Reported(BaseModel):
    """The result line's `review_answers` field, read apart from the rest of the result, as follow-ups are.

    Untrusted, so each entry is checked in `check`: a value of any shape is read here, and one that is not a list of
    answers is refused there, never taken as the whole result being invalid.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    review_answers: object = None


@dataclass(frozen=True)
class Answer:
    """One answer to record: the finding, by its review run and number, and what the worker said of it."""

    review_run_id: int
    finding: int
    answer: FindingAnswer
    #: Why it declined, or what it says of a fix; None for a fix it said nothing of.
    reason: str | None


@dataclass(frozen=True)
class Checked:
    """A run's `review_answers`, checked: the answers to record, and why each other entry was refused."""

    answers: Sequence[Answer] = ()
    refused: Sequence[str] = ()

    def note(self) -> str:
        """The run's harness note about what was refused, or "" when nothing was.

        Returns:
            A sentence naming each refused entry with why, at most `MAX_NAMED` of them, and counting the rest.
        """
        if not self.refused:
            return ""
        parts = list(self.refused[:MAX_NAMED])
        rest = len(self.refused) - len(parts)
        if rest:
            parts.append(f"{rest} more, not named")
        return f"review answers not recorded: {'; '.join(parts)}"


def parse(text: str) -> object:
    """Return the `review_answers` field of `text`'s result line, as the worker wrote it.

    Returns:
        The field's value, of any shape; None when there is no result line or it has no such field.
    """
    found = contract.last_line(_Reported, text)
    return found.review_answers if found is not None else None


def check(conn: sqlite3.Connection, reported: object, *, key: str) -> Checked:
    """Check what a run of ticket `key` reported in `review_answers`, each entry alone.

    An entry is kept when it names, by `review` and `finding`, a finding of a `done` review of `key`'s, with an
    `answer` of `fixed` or `declined`, and a `reason` for a decline. A finding answered twice keeps its first answer.

    Returns:
        The answers to record, and why each other entry was refused.
    """
    if reported is None:
        return Checked()
    if not isinstance(reported, list):
        return Checked(refused=("review_answers is not a list",))
    answers: list[Answer] = []
    refused: list[str] = []
    found: dict[int, int] = {}
    for number, entry in enumerate(reported, 1):
        if number > MAX_ANSWERS:
            refused.append(f"entry {number}: over {MAX_ANSWERS} answers a run")
            continue
        try:
            answer = _answer(conn, entry, key=key, found=found)
        except ValueError as e:
            refused.append(f"entry {number}: {e}")
            continue
        if any((a.review_run_id, a.finding) == (answer.review_run_id, answer.finding) for a in answers):
            refused.append(f"entry {number}: finding {answer.finding} of review run {answer.review_run_id} again")
            continue
        answers.append(answer)
    return Checked(answers=tuple(answers), refused=tuple(refused))


def record(conn: sqlite3.Connection, run_id: int, checked: Checked | None) -> None:
    """Record the answers run `run_id` gave, in the transaction that closes it."""
    if checked is None or not checked.answers:
        return
    records.insert_rows(records.ReviewAnswer, ["run_id", "review_run_id", "finding", "answer", "reason"]).many(
        conn,
        [(run_id, a.review_run_id, a.finding, a.answer, a.reason) for a in checked.answers],
    )


def latest(conn: sqlite3.Connection, review_run_id: int) -> dict[int, records.ReviewAnswer]:
    """Return what the latest run to answer each of review run `review_run_id`'s findings said of it.

    Each finding by its own latest answer: two resumes may answer different findings of one review, as when the
    operator sends one finding after a worker declined another, and the later run must not hide the earlier's decline.

    Returns:
        Each answered finding's answer, by its number; empty when no run answered any.
    """
    query = records.select(records.ReviewAnswer).where("review_run_id = ?", review_run_id).order_by("run_id")
    # Read oldest first, so each finding keeps its newest answer.
    return {a.finding: a for a in query.all(conn)}


def previous(
    conn: sqlite3.Connection,
    pr_url: str,
    *,
    before: int,
) -> tuple[records.ReviewRun, result.ReviewResult] | None:
    """Return the review a review of `pr_url` reads as its previous one: the latest `done` one before run `before`.

    Returns:
        The run and its result; None when the PR has no `done` review before this one.
    """
    for run in review_runs.review_runs_of(conn, pr_url):
        stored = result.stored(run.result_json)
        if run.id < before and run.status is ReviewRunStatus.DONE and stored is not None:
            return run, stored
    return None


def hold_rebuttals(conn: sqlite3.Connection, run: records.ReviewRun, stored: result.ReviewResult) -> list[int]:
    """Hold for the operator each of review run `run`'s findings that rebuts a finding the worker declined (§21).

    A finding's `rebuts` is the reviewer's claim: it is held only when it names a finding of the review the run read as
    its previous one that the latest worker to answer it declined. Any other finding, one that names a fixed or
    unanswered finding among them, is an ordinary one. Call in the transaction that closes the run.

    Returns:
        The numbers, from 1, of the findings held.
    """
    claimed = [(i, f.rebuts) for i, f in enumerate(stored.findings, 1) if f.rebuts is not None]
    found = previous(conn, run.pr_url, before=run.id) if claimed else None
    if found is None:
        return []
    earlier = found[0]
    answers = latest(conn, earlier.id)
    held: list[int] = []
    for number, rebuts in claimed:
        answer = answers.get(rebuts)
        if answer is not None and answer.answer is FindingAnswer.DECLINED:
            review_runs.hold(conn, run.id, number, rebuts=(earlier.id, rebuts))
            held.append(number)
    return held


def contract_text() -> str:
    """Return `{{REVIEW_ANSWERS}}`: the result field a resume handed canopy's review findings answers them in.

    Returns:
        The contract, starting with the blank line before it.
    """
    entry = '{"review":<review run id>,"finding":<its number>,"answer":"fixed|declined","reason":"<why>"}'
    return "\n".join(
        [
            "",
            "",
            (
                f'That JSON object also carries `"review_answers":[{entry}]`: one entry for each finding under '
                "canopy's review above, naming it by the review run and number it is listed under. `fixed` when this "
                "run's pushes fix it, `declined` when you left it as it is, with a `reason` that says why in a few "
                f"sentences, at most {MAX_REASON} characters, in your own words: what in the code or the ticket makes "
                "the finding wrong, or not this change's to fix. canopy's next review of the PR reads each answer, so "
                "a declined finding is not reported again unless the reviewer can show the reason is wrong, and then "
                "it goes to the operator, not back to you. Answer only the findings listed; leave out one you neither "
                "fixed nor declined."
            ),
        ],
    )


def _answer(conn: sqlite3.Connection, entry: object, *, key: str, found: dict[int, int]) -> Answer:
    """One entry as an answer to record. `found` caches each review run's number of findings, or -1 for none of key's.

    Returns:
        The answer.

    Raises:
        ValueError: the entry is not an answer to a finding of one of `key`'s `done` reviews, with why.
    """
    if not isinstance(entry, Mapping):
        raise ValueError("not an object")  # noqa: TRY004  (a refusal, said in the note, not a type error)
    review, finding, answer, reason = (entry.get(k) for k in ("review", "finding", "answer", "reason"))
    if not isinstance(review, int) or isinstance(review, bool) or review < 1:
        raise ValueError("`review` is not a review run's id")
    if not isinstance(finding, int) or isinstance(finding, bool) or finding < 1:
        raise ValueError("`finding` is not a finding's number")
    # The `str` test first: `in` on an enum raises for an unhashable value, such as a list, before Python 3.13.
    if not isinstance(answer, str) or answer not in FindingAnswer:
        raise ValueError(f"`answer` is not {' or '.join(FindingAnswer)}")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("`reason` is not text")
    said = reason.strip()[:MAX_REASON] if reason is not None else ""
    if answer == FindingAnswer.DECLINED and not said:
        raise ValueError("a decline gives no reason")
    if review not in found:
        found[review] = _findings_of(conn, review, key=key)
    if found[review] < 0:
        raise ValueError(f"review run {review} is not a done review of {key}")
    if finding > found[review]:
        raise ValueError(f"review run {review} has no finding {finding}")
    return Answer(review, finding, FindingAnswer(answer), said or None)


def _findings_of(conn: sqlite3.Connection, review_run_id: int, *, key: str) -> int:
    # How many findings a `done` review of `key`'s reported; -1 for a run that is not one.
    run = review_runs.get_review_run(conn, review_run_id)
    if run is None or run.ticket_key != key or run.status is not ReviewRunStatus.DONE:
        return -1
    stored = result.stored(run.result_json)
    return len(stored.findings) if stored is not None else -1
