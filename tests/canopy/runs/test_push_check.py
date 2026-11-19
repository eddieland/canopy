"""If a worker does this in git, canopy concludes that: the push check's verdicts, one story a row (DESIGN §8).

After the worker, `checkpoint.ensure_pushed` decides whether its work is on origin: `done` when it is, whether the
worker pushed it or canopy pushed what it left, and `unpushed` when a commit the worker made is on no branch of
origin's and no commit there holds its change. Each row below is one thing a worker does, played against a real
origin through the `git_pool` fixture, and the verdict canopy reaches. A row that reads wrong is a bug in the check.

The branch starts on origin with two commits, `a` and `b`, when a row says the base moved: `main` then has a commit
the branch lacks, as when the worker is asked to rebase. Otherwise origin has no branch yet.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import pytest

from canopy.core.vocab import RunStatus
from tests.canopy.helpers import branch_behind_main, commit_file, worker_does
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import GitPool

#: The run's branch, as an `implement` of KEY with no slug pushes it.
BRANCH: Final = "agent/PROJ-1-work"
#: The worker's push of HEAD to the branch.
PUSH: Final = ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"]
#: The worker's push that replaces the branch, as one that squashed or rebased it makes.
FORCE_PUSH: Final = ["git", "push", "--quiet", "--force-with-lease", "origin", f"HEAD:refs/heads/{BRANCH}"]
#: The worker moves HEAD off its commits, onto `main`, as a checkout of something else does.
LEAVES: Final = ["git", "checkout", "--quiet", "--detach", "origin/main"]
#: The worker's rebase onto `main`.
REBASE: Final = ["git", "rebase", "--quiet", "origin/main"]
#: The worker's squash of the branch into one commit on `main`.
SQUASH: Final = ["sh", "-c", "git reset --quiet --soft origin/main && git commit --quiet -m 'PROJ-1: squashed'"]
#: The squash below up to its message.
_WITHOUT_LOST: Final = "git reset --quiet --soft origin/main && git rm --quiet --cached lost.txt && git commit --quiet"
#: The worker's squash of the branch into one commit on `main`, leaving `lost.txt` out of it.
SQUASH_WITHOUT_LOST: Final = ["sh", "-c", f"{_WITHOUT_LOST} -m 'PROJ-1: squashed'"]
#: The worker's autosquash of the branch onto `main`, which folds each fixup into its target.
AUTOSQUASH: Final = ["sh", "-c", "GIT_SEQUENCE_EDITOR=: git rebase --quiet -i --autosquash origin/main"]
#: The worker's fixup of the commit that added `a.txt`.
FIXUP_A: Final = ["sh", "-c", "echo a2 > a.txt && git commit --quiet -am 'fixup! PROJ-1: a'"]
#: The worker's commit of its own that changes `a.txt`.
CHANGE_A: Final = ["sh", "-c", "echo again > a.txt && git commit --quiet -am 'PROJ-1: a again'"]
#: The worker's amend of its last commit, its message alone.
REWORD: Final = ["git", "commit", "--quiet", "--amend", "-m", "PROJ-1: reworded"]
#: The worker's amend of its last commit that changes `a.txt`.
AMEND_A: Final = ["sh", "-c", "echo a2 > a.txt && git commit --quiet -a --amend --no-edit"]
#: The worker's revert of its last commit.
REVERT: Final = ["git", "revert", "--quiet", "--no-edit", "HEAD"]
#: The worker throws its last commit away.
DROP_LAST: Final = ["git", "reset", "--quiet", "--hard", "HEAD~1"]
#: The worker commits on a local branch of its own.
ON_A_BRANCH: Final = ["git", "checkout", "--quiet", "-b", "mine"]
#: What canopy says of commits the worker left on no branch of origin's.
MOVED_OFF: Final = "the worker moved HEAD off {} commit(s) not on origin"
#: What canopy says when its own push of what the worker left fails.
PUSH_FAILED: Final = "not on origin; the push failed: "


@dataclass(frozen=True)
class Case:
    """One thing a worker does in git, and what canopy concludes of it."""

    #: The worker's commands, in order, in its slot.
    does: Sequence[Sequence[str]]
    #: The run's status after the push check.
    thinks: RunStatus
    #: What the harness's note on the result says, in part; "" for no note looked at.
    says: str = ""
    #: Whether `main` moved past the branch on origin before the run (`branch_behind_main`).
    base_moved: bool = False
    #: Whether `trust.rebase` lets a push replace the branch.
    rebase: bool = False


CASES: Final = [
    # Plain work.
    pytest.param(Case([commit_file("a"), PUSH], RunStatus.DONE), id="commits-and-pushes:done"),
    pytest.param(Case([commit_file("a")], RunStatus.DONE), id="commits-and-forgets-to-push:done,canopy-pushes"),
    pytest.param(
        Case([commit_file("a"), PUSH, commit_file("b")], RunStatus.DONE),
        id="pushes-then-commits-more:done,canopy-pushes-the-rest",
    ),
    pytest.param(
        Case([ON_A_BRANCH, commit_file("a")], RunStatus.DONE),
        id="commits-on-a-local-branch:done,canopy-pushes-head",
    ),
    pytest.param(
        Case([commit_file("a"), PUSH, REVERT, PUSH], RunStatus.DONE),
        id="pushes-a-commit-and-its-revert:done",
    ),
    # HEAD moved off the work.
    pytest.param(
        Case([commit_file("a"), LEAVES], RunStatus.UNPUSHED, MOVED_OFF.format(1)),
        id="commits-then-checks-out-main:unpushed",
    ),
    pytest.param(
        Case([commit_file("a"), PUSH, LEAVES], RunStatus.DONE),
        id="pushes-then-checks-out-main:done",
    ),
    pytest.param(
        Case([commit_file("a"), commit_file("b"), DROP_LAST], RunStatus.UNPUSHED, MOVED_OFF.format(1)),
        id="throws-away-an-unpushed-commit:unpushed",
    ),
    # Amends.
    pytest.param(
        Case([commit_file("a"), PUSH, REWORD, FORCE_PUSH], RunStatus.DONE, rebase=True),
        id="rewords-a-pushed-commit-and-force-pushes:done",
    ),
    # A false alarm the check still raises: the amended commit's change is replaced, not held, by the one pushed, and
    # nothing tells a revision from a loss.
    pytest.param(
        Case([commit_file("a"), PUSH, AMEND_A, FORCE_PUSH], RunStatus.UNPUSHED, MOVED_OFF.format(1), rebase=True),
        id="amends-a-pushed-commit's-change-and-force-pushes:unpushed",
    ),
    pytest.param(
        Case([commit_file("a"), PUSH, REWORD], RunStatus.UNPUSHED, PUSH_FAILED),
        id="rewords-a-pushed-commit-without-rebase:unpushed,canopy-will-not-force",
    ),
    # Rebases onto a base that moved.
    pytest.param(
        Case([REBASE], RunStatus.UNPUSHED, PUSH_FAILED, base_moved=True),
        id="rebases-without-rebase:unpushed,canopy-will-not-force",
    ),
    pytest.param(
        Case([REBASE], RunStatus.DONE, base_moved=True, rebase=True),
        id="rebases-and-forgets-to-push:done,canopy-pushes-with-a-lease",
    ),
    pytest.param(
        Case([commit_file("fix"), REBASE, FORCE_PUSH], RunStatus.DONE, base_moved=True, rebase=True),
        id="rebases-and-force-pushes:done",
    ),
    pytest.param(
        Case(
            [REBASE, ["git", "checkout", "--quiet", "--detach", f"origin/{BRANCH}"], commit_file("fix"), PUSH],
            RunStatus.DONE,
            base_moved=True,
        ),
        id="drops-its-rebase-and-pushes-a-fix-on-origin's-branch:done",
    ),
    pytest.param(
        Case(
            [
                REBASE,
                commit_file("lost"),
                ["git", "checkout", "--quiet", "--detach", f"origin/{BRANCH}"],
                commit_file("fix"),
                PUSH,
            ],
            RunStatus.UNPUSHED,
            MOVED_OFF.format(1),
            base_moved=True,
        ),
        id="drops-its-rebase-with-a-commit-of-its-own-on-it:unpushed",
    ),
    # Squashes and autosquashes (#2447).
    pytest.param(
        Case([commit_file("a"), commit_file("b"), PUSH, SQUASH, FORCE_PUSH], RunStatus.DONE, rebase=True),
        id="squashes-and-force-pushes:done",
    ),
    pytest.param(
        Case(
            [commit_file("a"), commit_file("b"), FORCE_PUSH, SQUASH, FORCE_PUSH, CHANGE_A, FORCE_PUSH],
            RunStatus.DONE,
            rebase=True,
        ),
        id="squashes-then-changes-a-line-the-squash-holds:done",
    ),
    pytest.param(
        Case(
            [commit_file("a"), commit_file("b"), FIXUP_A, FORCE_PUSH, AUTOSQUASH, FORCE_PUSH, CHANGE_A, FORCE_PUSH],
            RunStatus.DONE,
            rebase=True,
        ),
        id="autosquashes-a-fixup-then-changes-its-line:done",
    ),
    pytest.param(
        Case([FIXUP_A, AUTOSQUASH, FORCE_PUSH, CHANGE_A, FORCE_PUSH], RunStatus.DONE, base_moved=True, rebase=True),
        id="autosquashes-onto-a-moved-base-then-changes-the-line:done",
    ),
    pytest.param(
        Case(
            [
                commit_file("c"),
                ["sh", "-c", "echo c2 > c.txt && git commit --quiet -am 'PROJ-1: c again'"],
                REBASE,
                SQUASH,
                FORCE_PUSH,
                ["sh", "-c", "echo c3 > c.txt && git commit --quiet -am 'PROJ-1: c once more'"],
                FORCE_PUSH,
            ],
            RunStatus.DONE,
            base_moved=True,
            rebase=True,
        ),
        id="rebases-and-squashes-onto-a-moved-base-then-changes-the-line:done",
    ),
    pytest.param(
        Case(
            [
                ["sh", "-c", "echo fix > a.txt && git commit --quiet -am 'PROJ-1: fix'"],
                REBASE,
                SQUASH,
                FORCE_PUSH,
            ],
            RunStatus.DONE,
            base_moved=True,
            rebase=True,
        ),
        id="rebases-and-squashes-a-fix-onto-a-moved-base:done",
    ),
    pytest.param(
        Case(
            [commit_file("a"), commit_file("lost"), FORCE_PUSH, SQUASH_WITHOUT_LOST, FORCE_PUSH, CHANGE_A, FORCE_PUSH],
            RunStatus.UNPUSHED,
            MOVED_OFF.format(1),
            rebase=True,
        ),
        id="squashes-a-commit-out-then-changes-a-line:unpushed",
    ),
    pytest.param(
        Case(
            [
                REBASE,
                commit_file("lost"),
                ["sh", "-c", "echo fix > a.txt && git commit --quiet -am 'PROJ-1: fix'"],
                SQUASH_WITHOUT_LOST,
                FORCE_PUSH,
            ],
            RunStatus.UNPUSHED,
            MOVED_OFF.format(2),
            base_moved=True,
            rebase=True,
        ),
        id="rebases-and-squashes-a-commit-out:unpushed",
    ),
]


@pytest.mark.parametrize("case", CASES)
def test_what_canopy_concludes_of_what_the_worker_did_in_git(
    scenario: Scenario,
    git_pool: GitPool,
    case: Case,
) -> None:
    """The worker does `case.does`, and the run ends `case.thinks`, its note saying `case.says`."""
    if case.rebase:
        scenario.configures(trust={"rebase": True})
    if case.base_moved:
        branch_behind_main(git_pool)
    run = scenario.run(worker=worker_does(*[list(command) for command in case.does]))
    harness = json.loads(run.row["result_json"]).get("harness", "")
    assert (run.status, case.says in harness) == (case.thinks, True), harness
