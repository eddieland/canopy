"""The reports (DESIGN §11, §42): what each local calendar month cost, in dollars and tokens, and what it got done.

And how worker runs answered each repository's checklist over the last days, how the last days' runs ended, as
`canopy health` reads them, what CI did on the PRs canopy observed, where their review feedback came from, and how
plans were approved. Reads only.
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
from canopy.serve.schema.plan_report import PlansReport
from canopy.serve.schema.reports import MonthlyReport
from canopy.serve.schema.review_report import ReviewsReport

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

    As `canopy checklist` counts them: per repository and item, the runs reminded, then each answer, with the newest
    runs behind its `held` and `fixed` answers, each held one's reason the worker's text on a line. Then the same
    counts per item and local ISO week of the window.
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


@router.get("/reports/reviews", operation_id="getReviewsReport", summary="Get who reviewed over the last days")
def reviews_report(
    backend: BackendDep,
    days: Annotated[
        int,
        Query(
            ge=1,
            le=spending.MAX_DAYS,
            description=f"How many local days to read, today's so far included: 1 to {spending.MAX_DAYS}.",
        ),
    ] = spending.DEFAULT_DAYS,
) -> ReviewsReport:
    """Who reviewed the PRs canopy tracked, how soon first reviews came, the feedback rounds, and canopy's reviewer."""
    with backend.open() as ctx:
        return report_views.reviews_report(backend, ctx, days)


@router.get("/reports/plans", operation_id="getPlansReport", summary="Get how the last days' plans were approved")
def plans_report(
    backend: BackendDep,
    days: Annotated[
        int,
        Query(
            ge=1,
            le=spending.MAX_DAYS,
            description=f"How many local days to read, today's so far included: 1 to {spending.MAX_DAYS}.",
        ),
    ] = spending.DEFAULT_DAYS,
) -> PlansReport:
    """Each plan written in the window, how it was approved and how long that took, and the resumes its ticket needed.

    Split by the level of `policy.planner_may_approve` each plan's run was offered, and by who approved it.
    """
    with backend.open() as ctx:
        return report_views.plans_report(backend, ctx, days)
