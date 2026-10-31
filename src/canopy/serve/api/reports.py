"""The reports (DESIGN §11, §42): what each local calendar month cost, in dollars and tokens, and what it got done.

And how worker runs answered each repository's checklist over the last days, how the last days' runs ended, as
`canopy health` reads them, and what CI did on the PRs canopy observed. Reads only.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from canopy.core import config
from canopy.core import spend as spending
from canopy.serve import checklist_views, monthly, report_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.schema.checklist import ChecklistCounts
from canopy.serve.schema.ci import CiReport
from canopy.serve.schema.health import HealthReport
from canopy.serve.schema.reports import MonthlyReport

TAG = "reports"
router = APIRouter(tags=[TAG])


@router.get("/reports/monthly", operation_id="getMonthlyReport", summary="Get the report by month")
def monthly_report(
    backend: BackendDep,
    months: Annotated[
        int,
        Query(
            ge=1,
            le=monthly.MAX_MONTHS,
            description=(
                f"How many local calendar months to read, the current one so far included: 1 to {monthly.MAX_MONTHS}."
            ),
        ),
    ] = monthly.DEFAULT_MONTHS,
) -> MonthlyReport:
    """What each month cost by kind and by model, its tokens, and the tickets it landed with what each took."""
    with backend.open() as ctx:
        return report_views.monthly_report(backend, ctx, months)


@router.get("/reports/checklist", operation_id="getChecklistCounts", summary="Get the checklist's counts")
def checklist_counts(
    backend: BackendDep,
    days: Annotated[
        int,
        Query(
            ge=1,
            le=spending.MAX_DAYS,
            description=f"How many local days to read, today's so far included: 1 to {spending.MAX_DAYS}.",
        ),
    ] = spending.DEFAULT_DAYS,
    repo: Annotated[
        str | None,
        Query(
            max_length=64,
            pattern=f"^{config.REPO_NAME_RE.pattern}$",
            description="A repository's name: count only its list.",
        ),
    ] = None,
) -> ChecklistCounts:
    """How the worker runs that started in the window answered each item of their repositories' lists.

    As `canopy checklist` counts them: per repository and item, the runs reminded, then each answer. A held item's
    reason is the worker's text, and stays on its run.
    """
    with backend.open() as ctx:
        return checklist_views.checklist_counts(backend, ctx, days, repo=repo)


@router.get("/reports/health", operation_id="getHealthReport", summary="Get how the last days' runs ended")
def health_report(
    backend: BackendDep,
    days: Annotated[
        int,
        Query(
            ge=1,
            le=spending.MAX_DAYS,
            description=f"How many local days to read, today's so far included: 1 to {spending.MAX_DAYS}.",
        ),
    ] = spending.DEFAULT_DAYS,
) -> HealthReport:
    """Each kind's runs by how they ended, the newest failures, what the guards refused, and each day's failures."""
    with backend.open() as ctx:
        return report_views.health_report(backend, ctx, days)


@router.get("/reports/ci", operation_id="getCiReport", summary="Get what CI did over the last days")
def ci_report(
    backend: BackendDep,
    days: Annotated[
        int,
        Query(
            ge=1,
            le=spending.MAX_DAYS,
            description=f"How many local days to read, today's so far included: 1 to {spending.MAX_DAYS}.",
        ),
    ] = spending.DEFAULT_DAYS,
) -> CiReport:
    """Each check's red runs and how often a new head fixed it, each day's, the fixes and kicks, and the cooldown."""
    with backend.open() as ctx:
        return report_views.ci_report(backend, ctx, days)
