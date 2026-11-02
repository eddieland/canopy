"""The web UI's Plans report (DESIGN §11, §25): how the window's plans were approved, by level, and what followed.

Reads only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from canopy.core import plan_report, spend
from canopy.core.vocab import PlannerApproval
from canopy.serve.schema.plan_report import PlanLevel, PlanOutcome, PlansGroup
from tests.canopy.web_helpers import client

if TYPE_CHECKING:
    from canopy.serve.backend import Backend


def test_the_plans_report_reads_the_mocks_week_and_months(backend: Backend) -> None:
    """The week holds ABC-105's two plans; 30 days September's, at `strict` and `off`; 90 one from before levels."""
    c = client(None, backend)
    week = c.get("/api/reports/plans").json()
    assert (week["days"], week["since"], week["until"], week["level"]) == (
        7,
        "2026-10-02T00:00:00Z",
        "2026-10-09T00:00:00Z",
        "off",
    )
    assert [(p["ticket_key"], p["level"], p["outcome"]) for p in week["plans"]] == [
        ("ABC-105", "strict", "waiting"),
        ("ABC-105", "strict", "replaced"),
    ]
    assert (week["groups"], week["lengths"]) == ([], [])

    month = c.get("/api/reports/plans", params={"days": 30}).json()
    assert month["outcomes"] == {
        "planner": 2,
        "as_written": 1,
        "revised": 2,
        "replaced": 2,
        "dropped": 0,
        "waiting": 1,
    }
    rows = [(g["level"], g["outcome"], g["plans"], g["implemented"], g["with_resume"]) for g in month["groups"]]
    assert rows == [
        ("off", "revised", 1, 1, 0),
        ("strict", "planner", 2, 2, 1),
        ("strict", "as_written", 1, 1, 0),
        ("strict", "revised", 1, 1, 1),
    ]
    # ABC-091's second plan replaced one sent back with a comment; approved four hours after it was written.
    # Each plan measured from its original; the operator's approvals by length, cut at whole pages.
    assert all(p["metrics"]["lines"] > 0 for p in month["plans"])
    assert month["page_lines"] == plan_report.PAGE_LINES
    # ABC-079's and ABC-085's two to four pages; ABC-091's second, four to six.
    assert [(n["low"], n["high"], n["plans"]) for n in month["lengths"]] == [(100, 200, 2), (200, 300, 1)]
    second = next(p for p in month["plans"] if p["ticket_key"] == "ABC-091" and p["outcome"] == "revised")
    assert (second["earlier"], second["hours_to_approve"], second["resumes"], second["done"]) == (1, 4.0, 1, True)

    # ABC-076's run kept no level; its PR's `fix-ci` counts as a resume for CI.
    quarter = c.get("/api/reports/plans", params={"days": 90}).json()
    [old] = [p for p in quarter["plans"] if p["ticket_key"] == "ABC-076"]
    assert (old["level"], old["outcome"], old["resumes"], old["reasons"]) == (None, "as_written", 1, {"ci": 1})
    assert quarter["groups"][-1]["level"] is None
    assert c.get("/api/reports/plans", params={"days": 0}).status_code == 422
    assert c.get("/api/reports/plans", params={"days": spend.MAX_DAYS + 1}).status_code == 422


def test_the_schemas_literals_are_the_vocabularies_values() -> None:
    """A level or an outcome added to the core reaches the API's types, which name each by its value."""
    assert set(get_args(get_args(PlanLevel.__value__)[0])) == {str(level) for level in PlannerApproval}
    assert set(get_args(get_args(PlanOutcome.__value__)[0])) == {str(outcome) for outcome in plan_report.Outcome}
    assert set(get_args(PlansGroup.model_fields["outcome"].annotation)) == {str(o) for o in plan_report.APPROVED}
