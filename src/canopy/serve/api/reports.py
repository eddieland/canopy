"""The reports (DESIGN §11): what each local calendar month cost, in dollars and tokens, and what it got done.

Reads only.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from canopy.core import monthly
from canopy.serve import report_views
from canopy.serve.api.deps import BackendDep
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
