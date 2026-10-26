"""canopy's commit trailers (TRUST_MODEL T5): git adds them to every commit a worker makes.

It adds them through canopy's hooks, and the repository's own hooks still run; a commit made around them is named in
the run's harness note, never rewritten.
"""

import json
from pathlib import Path

from tests.canopy.helpers import commit_and_push, trailers_on, worker_does
from tests.canopy.scenario_helpers import Scenario, pushes
from tests.conftest import GitPool, executable, git

TRAILER = "Co-authored-by: canopy worker <noreply@canopy.invalid>"
BRANCH = "agent/PROJ-1-work"


def test_git_adds_canopys_trailer_to_each_commit_a_worker_makes(scenario: Scenario, git_pool: GitPool) -> None:
    run = scenario.run(
        worker=worker_does(
            ["git", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: one"],
            # Skipping the repository's checks skips none of canopy's.
            ["git", "commit", "--quiet", "--allow-empty", "--no-verify", "-m", "PROJ-1: two", "-m", "Why."],
            ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"],
        ),
    )
    assert run.status == "done"
    assert trailers_on(git_pool.origin, BRANCH) == [[TRAILER], [TRAILER]]
    assert git("log", "-1", "--format=%B", BRANCH, cwd=git_pool.origin) == f"PROJ-1: two\n\nWhy.\n\n{TRAILER}"
    assert "harness" not in json.loads(run.row["result_json"])


def test_a_trailer_the_worker_wrote_itself_is_not_added_again(scenario: Scenario, git_pool: GitPool) -> None:
    run = scenario.run(worker=pushes(message=f"PROJ-1: the change\n\n{TRAILER}"))
    assert run.status == "done"
    assert trailers_on(git_pool.origin, BRANCH) == [[TRAILER]]


def test_a_commit_with_trailers_of_its_own_is_not_named(scenario: Scenario, git_pool: GitPool) -> None:
    """A trailer of the worker's own beside canopy's: git separates them with a character `splitlines` splits on."""
    run = scenario.run(worker=pushes(message="PROJ-1: the change\n\nSigned-off-by: someone <someone@example.test>"))
    assert run.status == "done"
    assert trailers_on(git_pool.origin, BRANCH) == [["Signed-off-by: someone <someone@example.test>", TRAILER]]
    assert "harness" not in json.loads(run.row["result_json"])


def test_a_commit_made_around_the_hooks_is_named_and_left_as_it_is(scenario: Scenario, git_pool: GitPool) -> None:
    around = ["git", "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: around"]
    run = scenario.run(worker=worker_does(around, *commit_and_push(BRANCH)))
    assert run.status == "done"
    assert trailers_on(git_pool.origin, BRANCH) == [[TRAILER], []]
    note = json.loads(run.row["result_json"])["harness"]
    named = f"repo: 1 commit pushed to {BRANCH} lacks canopy's trailer: "
    assert note.startswith(named)
    assert git("rev-parse", f"{BRANCH}~1", cwd=git_pool.origin).startswith(note.removeprefix(named))


def test_the_repositorys_own_hooks_still_run(scenario: Scenario, git_pool: GitPool, tmp_path: Path) -> None:
    ran = tmp_path / "ran"
    for slot in git_pool.slots:
        for name in ("pre-commit", "prepare-commit-msg"):
            executable(slot / ".git" / "hooks" / name, f'#!/bin/sh\necho {name} "$@" >>"{ran}"\n')
    run = scenario.run(worker=pushes())
    assert run.status == "done"
    assert ran.read_text().splitlines() == ["pre-commit", "prepare-commit-msg .git/COMMIT_EDITMSG message"]
    assert trailers_on(git_pool.origin, BRANCH) == [[TRAILER]]


def test_with_canopys_trailer_off_git_adds_none(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"commit_trailer": False})
    run = scenario.run(worker=pushes())
    assert run.status == "done"
    assert trailers_on(git_pool.origin, BRANCH) == [[]]
    assert "harness" not in json.loads(run.row["result_json"])


def test_git_puts_the_prefix_before_each_subject_but_a_fixups(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"commit_prefix": "[{key}] "})
    run = scenario.run(
        worker=worker_does(
            ["git", "commit", "--quiet", "--allow-empty", "-m", "add the button"],
            # One that already has it keeps it once.
            ["git", "commit", "--quiet", "--allow-empty", "-m", "[PROJ-1] style it"],
            # --autosquash finds the commit a fixup is for by the subject after `fixup! `, so that stays as it is.
            ["git", "commit", "--quiet", "--allow-empty", "--fixup", "HEAD~1"],
            ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"],
        ),
    )
    assert run.status == "done"
    subjects = git("log", "--format=%s", BRANCH, "^main", cwd=git_pool.origin).splitlines()
    assert subjects == ["fixup! [PROJ-1] add the button", "[PROJ-1] style it", "[PROJ-1] add the button"]
    assert trailers_on(git_pool.origin, BRANCH) == [[TRAILER]] * 3
    assert "harness" not in json.loads(run.row["result_json"])
    assert "git starts each commit's subject with `[PROJ-1] `" in run.prompt


def test_a_commit_without_the_prefix_is_named_and_left_as_it_is(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"commit_prefix": "{key}: "})
    around = ["git", "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "--allow-empty", "-m", "around"]
    run = scenario.run(worker=worker_does(around, *commit_and_push(BRANCH, "the change")))
    assert run.status == "done"
    assert git("log", "--format=%s", BRANCH, "^main", cwd=git_pool.origin).splitlines() == [
        "PROJ-1: the change",
        "around",
    ]
    note = json.loads(run.row["result_json"])["harness"]
    trailer, prefix = note.split("; ")
    assert trailer.startswith(f"repo: 1 commit pushed to {BRANCH} lacks canopy's trailer: ")
    assert prefix.startswith(f"repo: 1 commit pushed to {BRANCH} lacks the prefix `PROJ-1: `: ")


def test_an_entry_a_tool_adds_after_canopys_still_finds_the_repositorys_hooks(
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    ran = tmp_path / "ran"
    for slot in git_pool.slots:
        executable(slot / ".git" / "hooks" / "pre-commit", f'#!/bin/sh\necho pre-commit >>"{ran}"\n')
    # The fixtures' git has one entry and canopy's is the second, so this third comes after it; bounded, so a hook
    # that handed on to itself fails the commit rather than the test's time.
    added = ["env", "GIT_CONFIG_COUNT=3", "GIT_CONFIG_KEY_2=user.name", "GIT_CONFIG_VALUE_2=tool"]
    commit = ["timeout", "30", *added, "git", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: the change"]
    run = scenario.run(worker=worker_does(commit, commit_and_push(BRANCH)[1]))
    assert run.status == "done"
    assert ran.read_text().splitlines() == ["pre-commit"]
    assert trailers_on(git_pool.origin, BRANCH) == [[TRAILER]]
