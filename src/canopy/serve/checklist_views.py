"""How worker and task runs answered each repository's checklist, as the API sends it (DESIGN §42).

The counts by the backend's clock, as `canopy checklist` prints them, and one run's answers, as `canopy show run:ID`
and `task:N` print them, a held item's reason among them: the worker's words, made printable and sent as text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from canopy.core import checklist_answers, conversation, db
from canopy.core.vocab import ItemAnswer
from canopy.serve.schema import ChecklistAnswer
from canopy.serve.schema import ItemAnswer as AnswerWord
from canopy.serve.schema.checklist import ChecklistCounts, ChecklistItemCounts

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.checklist_answers import RunTable
    from canopy.core.context import Context
    from canopy.serve.backend import Backend


def checklist_counts(backend: Backend, ctx: Context, days: int, *, repo: str | None = None) -> ChecklistCounts:
    """Count the answers of the worker and task runs that started in the last `days` local days, as `canopy checklist`.

    Returns:
        A count per repository and item a run of the window was given; `repo`'s alone when it is named.
    """
    found = checklist_answers.counts(ctx.conn, backend.clock(), days, repo=repo)
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
            )
            for c in found.items
        ],
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
