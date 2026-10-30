"""How worker runs answered each repository's checklist, as the API sends it (DESIGN §42), by the backend's clock."""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import checklist_answers, db
from canopy.serve.schema.checklist import ChecklistCounts, ChecklistItemCounts

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.serve.backend import Backend


def checklist_counts(backend: Backend, ctx: Context, days: int, *, repo: str | None = None) -> ChecklistCounts:
    """Count the answers of the worker runs that started in the last `days` local days, as `canopy checklist` does.

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
