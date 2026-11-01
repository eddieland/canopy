"""How worker and task runs answered each repository's checklist, as the API sends it (DESIGN §42).

The counts by the backend's clock, as `canopy checklist` prints them, with the runs behind each item's `held` and
`fixed` answers, a held one's reason on one line, and the counts by week; and one run's answers, as `canopy show run:ID`
and `task:N` print them, a held item's reason among them: the worker's words, made printable and sent as text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from canopy.core import checklist_answers, conversation, db, health, spend
from canopy.core.vocab import ItemAnswer
from canopy.serve.schema import ChecklistAnswer
from canopy.serve.schema import ItemAnswer as AnswerWord
from canopy.serve.schema.checklist import (
    ChecklistCounts,
    ChecklistItemCounts,
    ChecklistPrevious,
    ChecklistRun,
    ChecklistWeek,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable

    from canopy.core.checklist_answers import AnsweredBy, RunTable
    from canopy.core.context import Context
    from canopy.serve.backend import Backend


def checklist_counts(backend: Backend, ctx: Context, days: int, *, repo: str | None = None) -> ChecklistCounts:
    """Count the answers of the worker and task runs that started in the last `days` local days, as `canopy checklist`.

    Returns:
        A count per repository and item a run of the window was given, with the runs behind its `held` and `fixed`
        answers, and its counts in each ISO week of the window; `repo`'s alone when it is named.
    """
    now = backend.clock()
    # One snapshot for both reads, so a run that ends between them cannot leave an item in one and out of the other.
    with db.read_snapshot(ctx.conn):
        found = checklist_answers.counts(ctx.conn, now, days, repo=repo)
        grouped = checklist_answers.details(ctx.conn, now, days, repo=repo)
        before = checklist_answers.between(ctx.conn, *spend.window_before(found.since, days), repo=repo)
    runs = {(r.repo, r.item): r for r in grouped.items}
    return ChecklistCounts(
        since=db.parse_time(found.since),
        until=db.parse_time(found.until),
        days=found.days,
        repo=found.repo,
        items=[
            ChecklistItemCounts(
                repo=c.repo,
                item=c.item,
                reminded=c.reminded,
                passed=c.passed,
                fixed=c.fixed,
                held=c.held,
                not_applicable=c.not_applicable,
                unanswered=c.unanswered,
                held_runs=_runs(runs[c.repo, c.item].held),
                fixed_runs=_runs(runs[c.repo, c.item].fixed),
            )
            for c in found.items
        ],
        weeks=[
            ChecklistWeek(
                repo=w.counts.repo,
                item=w.counts.item,
                week=w.week,
                reminded=w.counts.reminded,
                passed=w.counts.passed,
                fixed=w.counts.fixed,
                held=w.counts.held,
                not_applicable=w.counts.not_applicable,
                unanswered=w.counts.unanswered,
            )
            for w in grouped.weeks
        ],
        previous=ChecklistPrevious(
            since=db.parse_time(before.since),
            until=db.parse_time(before.until),
            reminded=before.reminded,
            held=before.held,
            unanswered=before.unanswered,
        ),
    )


def run_answers(conn: sqlite3.Connection, run_id: int, *, table: RunTable = "runs") -> list[ChecklistAnswer]:
    """What run `run_id` of `table` answered of its repositories' checklists, as `canopy show` prints it.

    Returns:
        A row per item it was given, by repository and in each list's order; none for a run given no list.
    """
    return [
        ChecklistAnswer(
            repo=a.repo,
            item=a.item,
            answer=_word(a.answer),
            reason=_text(a.reason) if a.reason is not None else None,
        )
        for a in checklist_answers.of_run(conn, run_id, table=table)
    ]


def _runs(found: Iterable[AnsweredBy]) -> list[ChecklistRun]:
    # The runs behind an item's answers, each held one's reason on a line.
    return [
        ChecklistRun(
            kind=r.kind,
            id=r.id,
            task_id=r.task_id,
            started_at=db.parse_time(r.started_at),
            reason=_line(r.reason) if r.reason is not None else None,
        )
        for r in found
    ]


def _word(answer: ItemAnswer) -> AnswerWord:
    # The API's word for an answer, the journal's own.
    match answer:
        case ItemAnswer.PASSED:
            return "pass"
        case ItemAnswer.FIXED:
            return "fixed"
        case ItemAnswer.HELD:
            return "held"
        case ItemAnswer.NOT_APPLICABLE:
            return "n/a"
        case ItemAnswer.UNANSWERED:
            return "unanswered"
        case _:
            assert_never(answer)


def _text(reason: str) -> str | None:
    # The worker's reason as a page lays it out: control characters dropped, line breaks kept, blank ends cut.
    return "\n".join(line.rstrip() for line in conversation.printable(reason).splitlines()).strip("\n") or None


def _line(reason: str) -> str | None:
    # The worker's reason on one line, printable, and cut as the health report cuts a note: a hover's worth.
    text = " ".join(conversation.printable(reason).split())
    if not text:
        return None
    return text if len(text) <= health.NOTE_LIMIT else text[: health.NOTE_LIMIT - 3] + "..."
