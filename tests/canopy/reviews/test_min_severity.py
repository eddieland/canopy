"""`review.min_severity` (DESIGN §21): a finding less severe than it is held for the operator, and asks nothing."""

from pathlib import Path
from typing import Final

import pytest

from canopy.core import db, review_runs
from canopy.core.vocab import HoldKind, ResumeReason, RunKind
from canopy.reviews import waiting
from tests.canopy.helpers import waits
from tests.canopy.review_helpers import PR, REPORT, THEIRS, feature_commit, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes, reviews
from tests.conftest import CanopyEnv, GitPool

#: A report with a finding of each severity, gravest first.
EACH: Final = {
    **REPORT,
    "findings": [
        {"severity": "blocking", "title": "loops forever", "location": "retry.py:1", "detail": "Nothing ends it."},
        {"severity": "major", "title": "no tests", "location": "retry.py:2", "detail": "Add one."},
        {"severity": "minor", "title": "a vague name", "location": "retry.py:2", "detail": "Name it."},
    ],
}


@pytest.mark.parametrize(
    ("least", "held"),
    [("minor", []), ("major", [3]), ("blocking", [2, 3])],
)
def test_a_finding_less_severe_than_the_setting_is_held_and_asks_nothing(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
    least: str,
    held: list[int],
) -> None:
    """The findings at or above `review.min_severity` go to a worker; the rest wait, with no attention item."""
    scenario.configures("private", trust={"trusted_reviewers": ["canopy:review"]}, review={"min_severity": least})
    conn = scenario.conn
    scenario.run(worker=pushes())
    db.set_unit(conn, "PROJ-1", str(reviewing.root), "repo", pr_url=PR)
    run = scenario.review(reviews(feature_commit(git_pool, tmp_path), ticket="PROJ-1"), reviewer=reviewer_reports(EACH))

    assert {n: h.kind for n, h in review_runs.held(conn, run.id).items()} == dict.fromkeys(held, HoldKind.SEVERITY)
    assert waiting.items(conn) == []
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    latest = scenario.state()["reviews"]["prs"][0]["latest"]
    titles = [f["title"] for n, f in enumerate(EACH["findings"], 1) if n not in held]
    assert (latest["findings"], latest["held_findings"]) == (titles, len(held))
    resume = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW], review_run=run.id)
    prompt = scenario.run(resume, worker=pushes()).prompt
    assert "loops forever" in prompt
    assert ("a vague name" in prompt) == (3 not in held)


@pytest.mark.usefixtures("reviewing")
def test_the_operator_sends_a_finding_held_for_its_severity(
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    """A held finding says why where the operator reads the review, and reaches a worker once they send it."""
    scenario.configures("private", review={"min_severity": "major"})
    conn = scenario.conn
    run = scenario.review(reviews(feature_commit(git_pool, tmp_path), ticket="PROJ-1"), reviewer=reviewer_reports(EACH))
    shown = scenario.operator("review", "show", str(run.id)).out
    assert "a vague name (held for the operator: it is less severe than `review.min_severity`)" in shown

    scenario.operator("send", f"review:{run.id}", "3")
    assert review_runs.held(conn, run.id) == {}


@pytest.mark.usefixtures("reviewing")
def test_only_a_review_of_the_loops_own_pr_holds_a_finding_for_its_severity(
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    """A coworker's PR's findings make a draft, which the setting leaves whole."""
    scenario.configures("private", review={"min_severity": "blocking"})
    theirs = scenario.review(reviews(feature_commit(git_pool, tmp_path), THEIRS), reviewer=reviewer_reports(EACH))
    assert review_runs.held(scenario.conn, theirs.id) == {}
