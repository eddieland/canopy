"""A language for the push check's stories: what a worker did in git, and what canopy concluded of it (DESIGN §8).

A story is one line, read left to right:

    given(REBASE_TRUSTED).worker(commit("a"), PUSH, REWORD, FORCE_PUSH).then(DONE)
    worker(commit("a")).canopy_pushes().then(DONE)
    worker(commit("a"), CHECKOUT_MAIN).then(left_behind(1))

**The world.** Origin has `main`, at one empty commit. The run is an `implement` of PROJ-1, whose branch is BRANCH,
and its worker starts in a slot with HEAD detached at `origin/main`: origin has no BRANCH yet. A `Given` changes that
before the run:

- `BRANCH_BEHIND_MAIN`: origin has BRANCH, holding `a.txt` and `b.txt` in a commit each, and `main` has since gained
  a commit, `m.txt`, the branch lacks. The worker starts at origin's BRANCH.
- `REBASE_TRUSTED`: `trust.rebase` is on, so a push may replace BRANCH: the worker's own `FORCE_PUSH` is the same
  either way, origin refusing none, but canopy's push forces only with it.

**The worker.** `worker(...)` takes the `Step`s the worker runs, in order, each one git command line; the ones below
are the whole vocabulary. Every step must exit 0, or the story fails as mistold: a step git refused tells nothing of
the check.

**Canopy.** After the worker, the push check (`checkpoint.ensure_pushed`) runs. `canopy_pushes()` says its own push
put the worker's HEAD on origin; without it, canopy must have pushed nothing, or had its push refused. `then(...)`
takes the `Verdict`:

- `DONE`: the run ends `done`. Every commit the worker made is on origin, or its change is.
- `left_behind(n)`: the run ends `unpushed`, canopy naming `n` commits the worker moved HEAD off that no commit on
  origin holds.
- `PUSH_REFUSED`: the run ends `unpushed`, because HEAD holds work origin lacks and origin refused canopy's push of
  it: the push would replace BRANCH, and canopy forces nothing without `REBASE_TRUSTED`.

`play` plays a story against real git, through the `scenario` and `git_pool` fixtures, and fails on the first thing
that differs from it. A failed test's report tells it as it went: each step and its exit code, what canopy said, and
origin's commits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from canopy.core import run_changes
from canopy.core.vocab import RunStatus
from tests.canopy.helpers import branch_behind_main, commands_run, commit_file, worker_does
from tests.conftest import git

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import GitPool

#: The run's branch, as an `implement` of PROJ-1 with no slug names it.
BRANCH: Final = "agent/PROJ-1-work"


class Given(StrEnum):
    """Something true of the world before the run, named as a story's id tells it."""

    #: Origin has BRANCH, with `a.txt` and `b.txt`, and `main` has a commit past it. The worker starts on BRANCH.
    BRANCH_BEHIND_MAIN = "branch behind main"
    #: `trust.rebase` is on: a push of canopy's may replace BRANCH.
    REBASE_TRUSTED = "rebase trusted"


BRANCH_BEHIND_MAIN: Final = Given.BRANCH_BEHIND_MAIN
REBASE_TRUSTED: Final = Given.REBASE_TRUSTED


@dataclass(frozen=True)
class Step:
    """One thing the worker does in its slot."""

    #: The step as a story's id tells it.
    says: str
    #: The command line the worker runs.
    argv: Sequence[str]


def commit(name: str) -> Step:
    """The worker commits a new file, `NAME.txt`, as `PROJ-1: NAME`.

    Returns:
        The step.
    """
    return Step(f"commit {name}", commit_file(name))


def edit(name: str, to: str = "again") -> Step:
    """The worker commits a change to `NAME.txt`, a file HEAD has: its one line becomes `to`.

    Returns:
        The step.
    """
    return _sh(f"edit {name}", f"echo {to} > {name}.txt && git commit --quiet -am 'PROJ-1: {name} {to}'")


def fixup(name: str) -> Step:
    """The worker commits a change to `NAME.txt` as a fixup of the commit that added it, for AUTOSQUASH to fold.

    Returns:
        The step.
    """
    return _sh(f"fixup {name}", f"echo fixed > {name}.txt && git commit --quiet -am 'fixup! PROJ-1: {name}'")


def amend(name: str) -> Step:
    """The worker amends its last commit with a change to `NAME.txt`, so the commit's change is another.

    Returns:
        The step.
    """
    return _sh(f"amend {name}", f"echo amended > {name}.txt && git commit --quiet -a --amend --no-edit")


def squash_without(name: str) -> Step:
    """The worker squashes the branch into one commit on `main`, as SQUASH does, leaving `NAME.txt` out of it.

    Returns:
        The step.
    """
    return _sh(
        f"squash without {name}",
        f"git reset --quiet --soft origin/main && git rm --quiet --cached {name}.txt"
        " && git commit --quiet -m 'PROJ-1: squashed'",
    )


def new_branch(name: str) -> Step:
    """The worker makes a local branch at HEAD and switches to it, so its commits are on a branch, not detached.

    Returns:
        The step.
    """
    return Step(f"new branch {name}", ["git", "checkout", "--quiet", "-b", name])


def _sh(says: str, script: str) -> Step:
    return Step(says, ["sh", "-c", script])


#: The worker pushes HEAD to BRANCH. Origin takes it only if it adds to what BRANCH has.
PUSH: Final = Step("push", ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"])
#: The worker pushes HEAD to BRANCH with a lease, replacing what origin has, as after a squash or rebase.
FORCE_PUSH: Final = Step(
    "force-push",
    ["git", "push", "--quiet", "--force-with-lease", "origin", f"HEAD:refs/heads/{BRANCH}"],
)
#: The worker amends its last commit's message alone: a new commit with the same change.
REWORD: Final = Step("reword", ["git", "commit", "--quiet", "--amend", "-m", "PROJ-1: reworded"])
#: The worker commits a revert of its last commit.
REVERT: Final = Step("revert", ["git", "revert", "--quiet", "--no-edit", "HEAD"])
#: The worker throws its last commit away, `git reset --hard HEAD~1`.
DROP_LAST: Final = Step("drop last", ["git", "reset", "--quiet", "--hard", "HEAD~1"])
#: The worker rebases its commits onto origin's `main`.
REBASE: Final = Step("rebase", ["git", "rebase", "--quiet", "origin/main"])
#: The worker squashes everything the branch has past `main` into one commit on `main`.
SQUASH: Final = _sh("squash", "git reset --quiet --soft origin/main && git commit --quiet -m 'PROJ-1: squashed'")
#: The worker rebases onto origin's `main` with `--autosquash`, which folds each fixup into its target.
AUTOSQUASH: Final = _sh("autosquash", "GIT_SEQUENCE_EDITOR=: git rebase --quiet -i --autosquash origin/main")
#: The worker moves HEAD to origin's `main`, off whatever it committed.
CHECKOUT_MAIN: Final = Step("checkout main", ["git", "checkout", "--quiet", "--detach", "origin/main"])
#: The worker moves HEAD to BRANCH as origin has it, off whatever it committed or rebased.
CHECKOUT_BRANCH: Final = Step("checkout branch", ["git", "checkout", "--quiet", "--detach", f"origin/{BRANCH}"])


@dataclass(frozen=True)
class Verdict:
    """How the run ends after the push check."""

    #: The verdict as a story's id tells it.
    says: str
    #: The run's status.
    status: RunStatus
    #: What the harness's note on the run's result says, in part; "" for a verdict that says nothing.
    note: str = ""


#: The work is on origin.
DONE: Final = Verdict("done", RunStatus.DONE)
#: HEAD holds work origin lacks, and origin refused canopy's push of it.
PUSH_REFUSED: Final = Verdict("push refused", RunStatus.UNPUSHED, "not on origin; the push failed: ")


def left_behind(commits: int) -> Verdict:
    """The worker moved HEAD off `commits` commits whose work nothing on origin holds.

    Returns:
        The verdict.
    """
    return Verdict(
        f"{commits} left behind",
        RunStatus.UNPUSHED,
        f"the worker moved HEAD off {commits} commit(s) not on origin",
    )


@dataclass(frozen=True)
class Story:
    """One thing a worker does in git, and what canopy concludes of it."""

    #: What is true before the run.
    given: Sequence[Given]
    #: What the worker does, in order.
    steps: Sequence[Step]
    #: Whether canopy's own push puts the worker's HEAD on origin.
    pushes: bool
    #: How the run ends.
    verdict: Verdict

    def __str__(self) -> str:
        """The story in a line, which is its test's id."""
        given = f"{', '.join(self.given)}: " if self.given else ""
        steps = ", ".join(step.says for step in self.steps)
        pushes = "canopy pushes, " if self.pushes else ""
        return f"{given}{steps} -> {pushes}{self.verdict.says}"


@dataclass(frozen=True)
class Telling:
    """A story not yet ended: say what the worker does, whether canopy pushes, and then the verdict."""

    given: Sequence[Given] = ()
    steps: Sequence[Step] = ()
    pushes: bool = False

    def worker(self, *steps: Step) -> Telling:
        """The worker runs `steps`, in order.

        Returns:
            The story so far.
        """
        return replace(self, steps=steps)

    def canopy_pushes(self) -> Telling:
        """Canopy's own push puts the worker's HEAD on origin.

        Returns:
            The story so far.
        """
        return replace(self, pushes=True)

    def then(self, verdict: Verdict) -> Story:
        """The run ends as `verdict` says.

        Returns:
            The story, whole.
        """
        return Story(self.given, self.steps, self.pushes, verdict)


def given(*conditions: Given) -> Telling:
    """Start a story in a world where each of `conditions` holds.

    Returns:
        The story so far.
    """
    return Telling(given=conditions)


def worker(*steps: Step) -> Telling:
    """Start a story in the plain world, origin without the branch, with what the worker does.

    Returns:
        The story so far.
    """
    return Telling(steps=steps)


def play(story: Story, scenario: Scenario, git_pool: GitPool) -> None:
    """Play `story` as PROJ-1's `implement`, against real git, and fail on the first thing that differs from it.

    Raises:
        AssertionError: a step of the worker's failed, canopy pushed when the story says it does not or the other way,
            the run ended with another status, or the harness's note does not say what the verdict does.
    """
    __tracebackhide__ = True  # a failure reads as its message and the story as it went, not as this function
    if REBASE_TRUSTED in story.given:
        scenario.configures(trust={"rebase": True})
    if BRANCH_BEHIND_MAIN in story.given:
        branch_behind_main(git_pool, BRANCH)
    run = scenario.run(worker=worker_does(*[list(step.argv) for step in story.steps]))

    ran = commands_run(scenario.agent_log)[-1]
    for step, command in zip(story.steps, ran, strict=True):
        code, said = command["returncode"], str(command["stderr"]).strip()
        scenario.story.append(f"the worker: {step.says}, exit {code}" + (f": {said}" if code else ""))
    note = json.loads(run.row["result_json"]).get("harness", "")
    commits = run_changes.commits_of(scenario.conn, run.id).values()
    pushed = any(commit.harness_pushed for found in commits for commit in found)
    scenario.story.append(f"canopy: {'pushes, ' if pushed else ''}{run.status}" + (f": {note}" if note else ""))
    scenario.story.append("origin:\n" + git("log", "--graph", "--all", "--format=%h%d %s", cwd=git_pool.origin))

    failed = [step.says for step, command in zip(story.steps, ran, strict=True) if command["returncode"]]
    if failed:
        raise AssertionError(f"the story is mistold: the worker's {failed[0]!r} failed")
    if pushed != story.pushes:
        raise AssertionError(f"canopy {'pushed' if pushed else 'did not push'}, which is not what the story says")
    if run.status != story.verdict.status:
        raise AssertionError(f"the run ended {run.status}, not {story.verdict.status}: {note}")
    if story.verdict.note not in note:
        raise AssertionError(f"canopy's note lacks {story.verdict.note!r}: {note}")
