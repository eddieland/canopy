"""The reports (DESIGN §11): what each local calendar month cost and got done, and how the last days' runs ended.

Reads only.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from canopy.core import spend
from canopy.serve import monthly, report_views
from canopy.serve.api.deps import BackendDep
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


@router.get("/reports/health", operation_id="getHealthReport", summary="Get how the last days' runs ended")
def health_report(
    backend: BackendDep,
    days: Annotated[
        int,
        Query(
            ge=1,
            le=spend.MAX_DAYS,
            description=f"How many local days to read, today's so far included: 1 to {spend.MAX_DAYS}.",
        ),
    ] = spend.DEFAULT_DAYS,
) -> HealthReport:
    """Each kind's runs by how they ended, the newest failures, what the guards refused, and each day's failures."""
    with backend.open() as ctx:
        return report_views.health_report(backend, ctx, days)
