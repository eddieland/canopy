"""If a worker does this in git, canopy concludes that: the push check's verdicts, one story a line (DESIGN §8).

After the worker, `checkpoint.ensure_pushed` decides whether its work is on origin: `done` when it is, whether the
worker pushed it or canopy pushed what it left, and `unpushed` when a commit the worker made is on no branch of
origin's and no commit there holds its change. Each line of STORIES is one thing a worker does and what canopy makes
of it, in the language `tests/canopy/push_check_helpers.py` defines: its docstring says what each word means. A line
that reads wrong is a bug in the check.
"""

from typing import Final

import pytest

from tests.canopy.push_check_helpers import (
    AUTOSQUASH,
    BRANCH_BEHIND_MAIN,
    CHECKOUT_BRANCH,
    CHECKOUT_MAIN,
    DONE,
    DROP_LAST,
    FORCE_PUSH,
    PUSH,
    PUSH_REFUSED,
    REBASE,
    REBASE_TRUSTED,
    REVERT,
    REWORD,
    SQUASH,
    Story,
    amend,
    commit,
    edit,
    fixup,
    given,
    left_behind,
    new_branch,
    play,
    squash_without,
    worker,
)
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import GitPool

STORIES: Final = [
    # Plain work: what the worker did not push, canopy does.
    worker(commit("a"), PUSH).then(DONE),
    worker(commit("a")).canopy_pushes().then(DONE),
    worker(commit("a"), PUSH, commit("b")).canopy_pushes().then(DONE),
    worker(new_branch("mine"), commit("a")).canopy_pushes().then(DONE),
    worker(commit("a"), PUSH, REVERT, PUSH).then(DONE),
    # HEAD moved off the work: only what was pushed first is safe.
    worker(commit("a"), PUSH, CHECKOUT_MAIN).then(DONE),
    worker(commit("a"), CHECKOUT_MAIN).then(left_behind(1)),
    worker(commit("a"), commit("b"), DROP_LAST).canopy_pushes().then(left_behind(1)),
    # Amends: the old commit is left behind, and pushed only if the new one holds its change.
    given(REBASE_TRUSTED).worker(commit("a"), PUSH, REWORD, FORCE_PUSH).then(DONE),
    worker(commit("a"), PUSH, REWORD).then(PUSH_REFUSED),
    # A false alarm the check still raises: the amended commit's change is replaced, not held, by the one pushed, and
    # nothing tells a revision from a loss.
    given(REBASE_TRUSTED).worker(commit("a"), PUSH, amend("a"), FORCE_PUSH).then(left_behind(1)),
    # Rebases onto a base that moved: canopy pushes one the worker left, but only where it may replace the branch.
    given(BRANCH_BEHIND_MAIN).worker(REBASE).then(PUSH_REFUSED),
    given(BRANCH_BEHIND_MAIN, REBASE_TRUSTED).worker(REBASE).canopy_pushes().then(DONE),
    given(BRANCH_BEHIND_MAIN, REBASE_TRUSTED).worker(commit("fix"), REBASE, FORCE_PUSH).then(DONE),
    # A rebase the worker drops, to push on the branch as origin has it, loses only a commit made on the rebase.
    given(BRANCH_BEHIND_MAIN).worker(REBASE, CHECKOUT_BRANCH, commit("fix"), PUSH).then(DONE),
    given(BRANCH_BEHIND_MAIN).worker(REBASE, commit("lost"), CHECKOUT_BRANCH, commit("fix"), PUSH).then(left_behind(1)),
    # Squashes and autosquashes (#2447): the commit pushed holds the commits folded into it, though a later commit
    # changes a line of theirs again.
    given(REBASE_TRUSTED).worker(commit("a"), commit("b"), PUSH, SQUASH, FORCE_PUSH).then(DONE),
    given(REBASE_TRUSTED).worker(commit("a"), commit("b"), PUSH, SQUASH, FORCE_PUSH, edit("a"), PUSH).then(DONE),
    given(REBASE_TRUSTED)
    .worker(commit("a"), commit("b"), fixup("a"), PUSH, AUTOSQUASH, FORCE_PUSH, edit("a"), PUSH)
    .then(DONE),
    given(BRANCH_BEHIND_MAIN, REBASE_TRUSTED).worker(fixup("a"), AUTOSQUASH, FORCE_PUSH, edit("a"), PUSH).then(DONE),
    given(BRANCH_BEHIND_MAIN, REBASE_TRUSTED).worker(edit("a"), REBASE, SQUASH, FORCE_PUSH).then(DONE),
    given(BRANCH_BEHIND_MAIN, REBASE_TRUSTED)
    .worker(commit("c"), edit("c"), REBASE, SQUASH, FORCE_PUSH, edit("c", to="once more"), PUSH)
    .then(DONE),
    # A squash that leaves a commit's file out holds every commit but that one.
    given(REBASE_TRUSTED)
    .worker(commit("a"), commit("lost"), PUSH, squash_without("lost"), FORCE_PUSH, edit("a"), PUSH)
    .then(left_behind(1)),
    given(BRANCH_BEHIND_MAIN, REBASE_TRUSTED)
    .worker(REBASE, commit("lost"), edit("a"), squash_without("lost"), FORCE_PUSH)
    .then(left_behind(2)),
]


@pytest.mark.parametrize("story", STORIES, ids=str)
def test_what_canopy_concludes_of_what_the_worker_did_in_git(
    scenario: Scenario,
    git_pool: GitPool,
    story: Story,
) -> None:
    """The worker does what the story says, each step succeeding, and canopy pushes and concludes as it says."""
    play(story, scenario, git_pool)
