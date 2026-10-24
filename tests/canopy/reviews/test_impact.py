"""A review's impact as the harness holds it: `high` for a change to a path `review.high_impact_paths` covers (§21)."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from canopy.core import review_result as result
from canopy.reviews import impact
from tests.canopy.helpers import present
from tests.canopy.review_helpers import CLEAN, FINDINGS, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, reviews
from tests.conftest import CanopyEnv, GitPool, git

#: The note on a review the harness raised for a change to CI's workflow.
RAISED = (
    "reported {impact} impact, but the change touches .github/workflows/ci.yml, which review.high_impact_paths covers "
    "as .github/workflows/; recorded as high"
)


@pytest.mark.parametrize(
    ("entries", "changed", "found"),
    [
        ((".github/workflows/",), [".github/workflows/ci.yml"], (".github/workflows/ci.yml", ".github/workflows/")),
        ((".agents",), ["src/a.py", ".agents/prompts/overseer.md"], (".agents/prompts/overseer.md", ".agents")),
        (("docs/TRUST_MODEL.md",), ["docs/TRUST_MODEL.md"], ("docs/TRUST_MODEL.md", "docs/TRUST_MODEL.md")),
        # By whole components, never as text: a sibling with a longer name is not under the entry.
        ((".agents/", "docs/TRUST_MODEL.md"), [".agentsrc", "docs/TRUST_MODEL.md.bak", "x/.agents/a.md"], None),
        # No globs: an entry is a path.
        (("*.yml",), ["ci.yml"], None),
        ((".github/workflows/",), [], None),
    ],
)
def test_an_entry_covers_the_path_it_names_and_everything_under_it(
    entries: tuple[str, ...],
    changed: list[str],
    found: tuple[str, str] | None,
) -> None:
    match = impact.matched(entries, changed)
    assert (None if match is None else (match.path, match.entry)) == found


def changes(git_pool: GitPool, tmp_path: Path, files: Mapping[str, str]) -> str:
    """Push a commit writing `files` on a branch `feature` off origin's `main`, and return it."""
    seed = tmp_path / "seed"
    git("checkout", "--quiet", "-b", "feature", cwd=seed)
    for name, text in files.items():
        path = seed / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        git("add", name, cwd=seed)
    git("commit", "--quiet", "-m", "change", cwd=seed)
    git("push", "--quiet", str(git_pool.origin), "feature", cwd=seed)
    return present(git_pool.remote_head("feature"))


def stored(scenario: Scenario, sha: str, report: Mapping[str, object]) -> tuple[result.ReviewResult, str]:
    """Review `PR` at `sha`, the reviewer reporting `report`, and return the result recorded and the harness's note."""
    row = scenario.review(reviews(sha), reviewer=reviewer_reports(report)).row
    assert row.status == "done", row.result_json
    return present(result.stored(row.result_json)), json.loads(str(row.result_json)).get("harness", "")


@pytest.mark.parametrize("reported", ["normal", "low"])
def test_a_change_to_ci_is_high_impact_whatever_the_reviewer_says(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
    reported: str,
) -> None:
    """A PR's text cannot talk the reviewer down on a change to a default path, not even with `review.low_impact`."""
    scenario.configures(review={"low_impact": "A change to CI or docs only."})
    sha = changes(git_pool, tmp_path, {".github/workflows/ci.yml": "on: push\n", "retry.py": "call()\n"})
    found, note = stored(scenario, sha, {**FINDINGS, "impact": reported})
    assert found.impact == "high"
    assert note == RAISED.format(impact=reported)
    shown = scenario.operator("review", "show", "1").out
    assert f"harness: {RAISED.format(impact=reported)}\nverdict findings, impact high\n" in shown


def test_the_reviewers_own_high_on_such_a_change_stands_without_a_note(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    sha = changes(git_pool, tmp_path, {".agents/prompts/overseer.md": "Be careful.\n"})
    found, note = stored(scenario, sha, {**FINDINGS, "impact": "high"})
    assert (found.impact, note) == ("high", "")


def test_a_change_elsewhere_keeps_the_reviewers_impact(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    """The harness only raises: `low`, as `review.low_impact` allows it, stands on a change no entry covers."""
    scenario.configures(review={"low_impact": "A change to docs only."})
    sha = changes(git_pool, tmp_path, {"docs/guide.md": "Hello.\n"})
    found, note = stored(scenario, sha, CLEAN)
    assert (found.impact, note) == ("low", "")


def test_the_workspace_file_adds_paths_and_the_operator_chooses_the_rest(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    """A shared file only adds: the operator may drop the defaults, and the workspace's entry still holds."""
    scenario.configures(review={"high_impact_paths": ["deploy/"]})
    scenario.configures("workspace", review={"high_impact_paths": ["infra/"]})
    sha = changes(git_pool, tmp_path, {".github/workflows/ci.yml": "on: push\n", "infra/main.tf": "x = 1\n"})
    found, note = stored(scenario, sha, FINDINGS)
    assert found.impact == "high"
    assert note.startswith("reported normal impact, but the change touches infra/main.tf, which review.high_impact")


def test_a_review_whose_paths_git_could_not_name_says_they_went_unchecked(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    """Without its base, the review runs as it did, keeping the reviewer's impact, and the operator is told."""
    sha = changes(git_pool, tmp_path, {".github/workflows/ci.yml": "on: push\n"})
    git("update-ref", "-d", "refs/heads/main", cwd=git_pool.origin)
    found, note = stored(scenario, sha, FINDINGS)
    assert found.impact == "normal"
    assert note == "the change's paths could not be read, so review.high_impact_paths went unchecked"
