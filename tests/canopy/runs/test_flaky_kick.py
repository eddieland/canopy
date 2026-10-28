"""Flaky kicks (DESIGN §23): the harness rebases and leases a branch to rerun checks a worker judged flaky."""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from unittest import mock

from canopy.core import contract
from canopy.core.vocab import ResumeReason, RunKind
from tests.canopy.helpers import KEY, WORKER_DONE, waits, worker_does
from tests.canopy.scenario_helpers import Ran, Scenario, dispatches, pushes
from tests.conftest import GitPool, git

BRANCH = "agent/PROJ-1-work"
#: A `resume` worker's result that leaves a failed check as flaky, changing nothing.
LEAVES_FLAKY = json.dumps(
    json.loads(WORKER_DONE) | {"branch": BRANCH, "summary": "unit-tests lost its runner", "flaky": True},
)


def resumes(*reasons: ResumeReason) -> list[str]:
    """The overseer resumes PROJ-1 for `reasons`."""
    return dispatches(kind=RunKind.RESUME, reasons=reasons)


def leaves_flaky(scenario: Scenario, reason: ResumeReason = ResumeReason.CI) -> Ran:
    """A `resume` for `reason`, past the CI cooldown, whose worker leaves a failed check as flaky and pushes nothing."""
    scenario.time_passes(minutes=31)
    return scenario.run(resumes(reason), worker=worker_does(result=LEAVES_FLAKY))


@contextmanager
def committed_at(when: str) -> Iterator[None]:
    """Date every commit made in the block, the harness's included, so a commit made again is a new one."""
    with mock.patch.dict(os.environ, {"GIT_COMMITTER_DATE": when}):
        yield


def main_moves(git_pool: GitPool, name: str) -> None:
    """Push a commit to `main` on origin that the ticket's branch lacks, touching `name`.txt."""
    seed = git_pool.slots[1]
    git("fetch", "--quiet", "origin", cwd=seed)
    git("checkout", "--quiet", "--detach", "origin/main", cwd=seed)
    (seed / f"{name}.txt").write_text(f"{name}\n")
    git("add", f"{name}.txt", cwd=seed)
    git("commit", "--quiet", "-m", f"main: {name}", cwd=seed)
    git("push", "--quiet", "origin", "HEAD:refs/heads/main", cwd=seed)


def harness_note(ran: Ran) -> str:
    return str(contract.stored_object(ran.row["result_json"]).get("harness", ""))


def test_without_kicks_a_flaky_check_is_left_to_the_operator(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.run(worker=pushes())
    before = git_pool.remote_head(BRANCH)
    main_moves(git_pool, "m")

    left = leaves_flaky(scenario)
    assert left.status == "done"
    assert git_pool.remote_head(BRANCH) == before
    assert "kicked" not in contract.stored_object(left.row["result_json"])


def test_a_flaky_check_is_kicked_onto_the_base_until_the_head_has_had_its_kicks(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.configures(trust={"max_flaky_kicks": 2})
    scenario.run(worker=pushes())
    heads = [git_pool.remote_head(BRANCH)]
    for name in ("m1", "m2"):
        main_moves(git_pool, name)
        kicked = leaves_flaky(scenario)
        assert kicked.status == "done", harness_note(kicked)
        assert contract.stored_object(kicked.row["result_json"])["kicked"] == ["repo"]
        head = git_pool.remote_head(BRANCH)
        assert head not in heads
        heads.append(head)
        # Rebased onto the base as it is, with the ticket's work as before.
        assert git("merge-base", "--is-ancestor", "main", BRANCH, cwd=git_pool.origin) == ""
        assert git("log", "-1", "--format=%s", BRANCH, cwd=git_pool.origin) == "PROJ-1: the change"
    # The overseer reads that the checks run again on a new head, and raises no rerun for the old one.
    scenario.tick(*waits(KEY, rationale="the kicked checks run"))
    assert scenario.ticket_state()["last_run"]["kicked"] is True

    main_moves(git_pool, "m3")
    spent = leaves_flaky(scenario)
    assert spent.status == "done"
    assert git_pool.remote_head(BRANCH) == heads[-1]
    assert f"repo: not kicked: {BRANCH} has had 2 kick(s) since its work was pushed" in harness_note(spent)
    scenario.tick(*waits(KEY, rationale="the operator reruns it"))
    last = scenario.ticket_state()["last_run"]
    assert last["flaky"] is True
    assert "kicked" not in last


def test_a_push_of_work_gives_the_new_head_its_kicks(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"max_flaky_kicks": 1})
    scenario.run(worker=pushes())
    with committed_at("2030-01-01T00:00:00"):
        assert leaves_flaky(scenario).status == "done"
    kicked = git_pool.remote_head(BRANCH)
    with committed_at("2030-01-02T00:00:00"):
        assert "not kicked" in harness_note(leaves_flaky(scenario))
    assert git_pool.remote_head(BRANCH) == kicked

    scenario.time_passes(minutes=31)
    scenario.run(resumes(ResumeReason.CI), worker=pushes(message="PROJ-1: fix the build"))
    fixed = git_pool.remote_head(BRANCH)
    with committed_at("2030-01-03T00:00:00"):
        again = leaves_flaky(scenario)
    assert harness_note(again) == ""
    assert git_pool.remote_head(BRANCH) not in {kicked, fixed}


def test_a_branch_that_does_not_rebase_is_left_as_it_was(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"max_flaky_kicks": 2})
    writes = ["sh", "-c", "echo ours > a.txt && git add a.txt && git commit --quiet -m 'PROJ-1: a'"]
    pushed = ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"]
    scenario.run(worker=worker_does(writes, pushed))
    before = git_pool.remote_head(BRANCH)
    main_moves(git_pool, "a")  # main writes a.txt too

    left = leaves_flaky(scenario)
    assert left.status == "done"
    note = harness_note(left)
    assert note.startswith(f"repo: not kicked: {BRANCH} does not rebase onto main: error: could not apply"), note
    assert "\n" not in note
    assert git_pool.remote_head(BRANCH) == before
    assert "kicked" not in contract.stored_object(left.row["result_json"])


def test_only_a_resume_for_ci_is_kicked(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"max_flaky_kicks": 2})
    scenario.run(worker=pushes())
    before = git_pool.remote_head(BRANCH)
    main_moves(git_pool, "m")
    leaves_flaky(scenario, ResumeReason.REVIEW)
    assert git_pool.remote_head(BRANCH) == before
