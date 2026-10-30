"""Late findings (DESIGN §21): a later review's findings on code unchanged since its PR's first review, held."""

from pathlib import Path

import pytest

from canopy.core import db, review_runs
from canopy.core.vocab import HoldKind, ResumeReason, RunKind
from canopy.reviews import waiting
from tests.canopy.helpers import Called, present, waits
from tests.canopy.review_helpers import CLEAN, FINDINGS, PR, THEIRS, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes, reviews
from tests.conftest import CanopyEnv, GitPool, git

#: The file at the PR's first reviewed commit, and at its second, which changes line 2 and adds line 5.
FIRST, SECOND = "a = 1\nb = 2\nc = 3\nd = 4\n", "a = 1\nb = 20\nc = 3\nd = 4\ne = 5\n"


def finding(severity: str, title: str, location: str) -> dict[str, str]:
    """A finding of the second review's report."""
    return {"severity": severity, "title": title, "location": location, "detail": "It is wrong."}


#: The second review's report: findings 1, 8, and 9 are on lines the second commit leaves as they were, and are late.
LATER = {
    **FINDINGS,
    "findings": [
        finding("minor", "c is unused", "src/retry.py:3"),
        finding("minor", "b is too big", "src/retry.py:2"),
        finding("blocking", "d breaks the build", "src/retry.py:4"),
        finding("major", "e is new", "src/retry.py:5"),
        finding("minor", "past the end", "src/retry.py:9"),
        finding("minor", "the whole file", "src/retry.py"),
        finding("major", "a and b clash", "./src/retry.py:1-2"),
        finding("minor", "c and d clash", "`./src/retry.py:L3-L4`"),
        finding("minor", "a shadows a builtin", "src/retry.py:1:5"),
        finding("minor", "not in this repository", "web/src/app.ts:1"),
    ],
}
#: The second review's findings that are not late.
NOT_LATE = [
    "b is too big",
    "d breaks the build",
    "e is new",
    "past the end",
    "the whole file",
    "a and b clash",
    "not in this repository",
]


def two_commits(git_pool: GitPool, tmp_path: Path) -> tuple[str, str]:
    """Push `FIRST`, then `SECOND`, as `src/retry.py` on a branch `late` off origin's `main`; return the commits."""
    seed = tmp_path / "seed"
    git("checkout", "--quiet", "-b", "late", cwd=seed)
    (seed / "src").mkdir()
    shas: list[str] = []
    for text in (FIRST, SECOND):
        (seed / "src" / "retry.py").write_text(text)
        git("add", "src/retry.py", cwd=seed)
        git("commit", "--quiet", "-m", "retry", cwd=seed)
        git("push", "--quiet", str(git_pool.origin), "late", cwd=seed)
        shas.append(present(git_pool.remote_head("late")))
    return shas[0], shas[1]


def resume(review_run: int) -> Called:
    """The overseer dispatches a `resume` of PROJ-1 for review run `review_run`'s findings."""
    return dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW], review_run=review_run)


def test_a_later_reviews_finding_on_code_the_first_review_read_waits_on_the_operator(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    """A finding on a line unchanged since the PR's first reviewed commit starts no resume; the operator sends it."""
    # canopy's reviewer is trusted, so its findings go to a worker on its own word, but a late one's never does.
    scenario.configures("private", trust={"trusted_reviewers": ["canopy:review"]})
    conn = scenario.conn
    first, second = two_commits(git_pool, tmp_path)
    scenario.review(reviews(first, ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))
    scenario.run(worker=pushes())
    db.set_unit(conn, "PROJ-1", str(reviewing.root), "repo", pr_url=PR)
    later = scenario.review(reviews(second, ticket="PROJ-1"), reviewer=reviewer_reports(LATER)).id

    # Not a blocking finding, nor one off the file, past its end, or reaching a line the second commit wrote.
    held = review_runs.held(conn, later)
    assert {n: h.kind for n, h in held.items()} == dict.fromkeys([1, 8, 9], HoldKind.LATE)
    assert (held[1].rebuts_run_id, held[1].rebuts_finding) == (None, None)
    shown = scenario.operator("review", "show", str(later)).out
    assert (
        "1. **minor** `src/retry.py:3`: c is unused (held for the operator: it is on code unchanged since the" in shown
    )

    # Neither the overseer nor a worker acts on a held one; the operator hears of them.
    [item] = waiting.items(conn)
    assert (item.ticket, item.reason) == ("PROJ-1", waiting.LATE_REASON)
    unchanged = "is on code unchanged since the PR's first reviewed commit"
    assert item.detail.startswith(f"review:{later} finding 1 {unchanged}; review:{later} finding 8 {unchanged}; ")
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    latest = scenario.state()["reviews"]["prs"][0]["latest"]
    assert (latest["findings"], latest["held_findings"]) == (NOT_LATE, 3)
    prompt = scenario.run(resume(later), worker=pushes()).prompt
    assert "b is too big" in prompt
    assert "c is unused" not in prompt
    assert "a shadows a builtin" not in prompt

    # Sent, a resume hands it on; dismissed, it waits on nobody.
    db.set_unit(conn, "PROJ-1", str(reviewing.root), "repo", pr_url=PR)
    scenario.operator("send", f"review:{later}", "1")
    assert set(review_runs.held(conn, later)) == {8, 9}
    for number in ("8", "9"):
        scenario.operator("dismiss", f"review:{later}", number, "--reason", "not_worth_it")
    assert waiting.items(conn) == []
    assert "c is unused" in scenario.run(resume(later), worker=pushes()).prompt


@pytest.mark.usefixtures("reviewing")
def test_only_a_review_of_the_loops_own_pr_holds_a_late_finding(
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    """A coworker's PR's findings start no resume to hold one back from, at any commit."""
    first, second = two_commits(git_pool, tmp_path)
    scenario.review(reviews(first, THEIRS), reviewer=reviewer_reports(CLEAN))
    theirs = scenario.review(reviews(second, THEIRS), reviewer=reviewer_reports(LATER)).id
    assert review_runs.held(scenario.conn, theirs) == {}
