"""The outline of the PR's code in a reviewer's prompt (DESIGN §46, ROADMAP M70 stage 1).

At `index.outline = "tree"` a review's prompt holds the tree of the commit it reviews, read from git's objects at its
start and opened where the PR's diff changed files; at `off`, the default, it holds none.
"""

from pathlib import Path

import pytest

from canopy.core.vocab import ReviewRunStatus
from tests.canopy.helpers import OUTLINE_HEADING, outline_of, present, tracked
from tests.canopy.review_helpers import CLEAN, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, reviews
from tests.conftest import GitPool, git

#: A repository's files, as its base branch holds them: by size alone, `docs/` is the directory an outline opens.
FILES = (
    "README.md",
    *(f"docs/page_{n:02}.md" for n in range(22)),
    *(f"src/module_{n:02}.py" for n in range(20)),
)


def pr_commit(git_pool: GitPool, tmp_path: Path, *, fetched: bool) -> str:
    """Push a PR's branch that adds `src/ledger.py` off origin's `main`; return its commit.

    With `fetched`, each slot fetches it, as a pool's lease does; without, only origin holds it, as a fork's PR's is.
    """
    work = tmp_path / "tracked-origin"
    git("checkout", "--quiet", "-b", "feature", cwd=work)
    (work / "src" / "ledger.py").write_text("ledger\n")
    git("add", ".", cwd=work)
    git("commit", "--quiet", "-m", "a ledger", cwd=work)
    git("push", "--quiet", "origin", "feature", cwd=work)
    if fetched:
        for slot in git_pool.slots:
            git("fetch", "--quiet", "origin", cwd=slot)
    return present(git_pool.remote_head("feature"))


@pytest.mark.usefixtures("reviewing")
def test_a_reviews_prompt_holds_the_prs_tree_opened_where_its_diff_changed(
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path, FILES)
    sha = pr_commit(git_pool, tmp_path, fetched=True)
    scenario.configures(index={"outline": "tree", "outline_chars": 500})

    review = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))

    assert review.status == ReviewRunStatus.DONE
    assert f"`repo`, as of `{sha[:12]}`:" in review.prompt
    # The directory the PR changed is open, its new file among its own, and the larger one is a name and a count.
    assert outline_of(review.prompt)[:3] == ["docs/ (22 files)", "src/", "  ledger.py"]
    assert "44 files in all, 22 not listed by name." in review.prompt


@pytest.mark.usefixtures("reviewing")
def test_a_review_of_a_commit_its_slot_does_not_hold_yet_gets_no_outline_and_goes_on(
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path, FILES)
    sha = pr_commit(git_pool, tmp_path, fetched=False)
    scenario.configures(index={"outline": "tree"})

    review = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))

    assert review.status == ReviewRunStatus.DONE
    assert OUTLINE_HEADING not in review.prompt


@pytest.mark.usefixtures("reviewing")
def test_with_the_outline_off_a_reviews_prompt_has_none(scenario: Scenario, git_pool: GitPool, tmp_path: Path) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path, FILES)
    sha = pr_commit(git_pool, tmp_path, fetched=True)

    review = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))

    assert review.status == ReviewRunStatus.DONE
    assert OUTLINE_HEADING not in review.prompt
    assert "module_00" not in review.prompt
