"""Flaky kicks (DESIGN §23): the harness rebases and leases a branch to rerun checks a worker judged flaky."""

import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

from canopy.core import contract
from canopy.core.vocab import ResumeReason, RunKind
from canopy.notify import message
from tests.canopy.helpers import KEY, READ_PR, WORKER_DONE, Called, messages, raises, waits, worker_does
from tests.canopy.scenario_helpers import Ran, Scenario, dispatches, pushes
from tests.conftest import GitPool, git

BRANCH = "agent/PROJ-1-work"
#: The PR a worker's result names, `WORKER_DONE`'s.
PR = "https://example.test/pr/1"
#: A `resume` worker's result that leaves a failed check as flaky, changing nothing.
LEAVES_FLAKY = json.dumps(
    json.loads(WORKER_DONE) | {"branch": BRANCH, "summary": "unit-tests lost its runner", "flaky": True},
)


def resumes(*reasons: ResumeReason) -> Called:
    """The overseer resumes PROJ-1 for `reasons`."""
    return dispatches(kind=RunKind.RESUME, reasons=reasons)


def leaves_flaky(
    scenario: Scenario,
    reason: ResumeReason = ResumeReason.CI,
    adds: Mapping[str, object] | None = None,
) -> Ran:
    """A `resume` for `reason`, past the CI cooldown, whose worker leaves a failed check as flaky and pushes nothing.

    `adds` adds to the worker's result, such as the `flaky_cause` it names.
    """
    scenario.time_passes(minutes=31)
    said = json.dumps(json.loads(LEAVES_FLAKY) | dict(adds or {}))
    return scenario.run(resumes(reason), worker=worker_does(result=said))


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


def takes_runs(scenario: Scenario) -> None:
    """Configure a sink that takes the `runs` events, so they are recorded."""
    scenario.configures(notify={"sinks": {"slack": {"cmd": "true", "events": ["runs"]}}})


def told(scenario: Scenario, kind: str = "ci.flaky") -> list[dict[str, object]]:
    """The fields of each `kind` event in the outbox, in order."""
    rows = scenario.conn.execute("SELECT fields FROM notify_events WHERE kind = ? ORDER BY id", (kind,))
    return [json.loads(str(r["fields"])) for r in rows]


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
    github_state: Path,
) -> None:
    scenario.configures(trust={"max_flaky_kicks": 2})
    # A PR the `vcs` source reads, so the overseer is listed the ticket (DESIGN §39), read within the hour.
    scenario.configures("private", connect={"max_age_minutes": 60})
    scenario.run(worker=pushes(prs={"repo": READ_PR}))
    run_ids = iter(range(77, 80))

    def red_again() -> Ran:
        """A tick reads a new head of the PR whose check failed, and a `resume` leaves the failure as flaky."""
        run_id = next(run_ids)
        failed = {"name": "unit-tests", "status": "completed", "conclusion": "failure", "run_id": run_id}
        github_state.write_text(
            json.dumps({"prs": {READ_PR: {"pr": {"head_sha": f"abc{run_id:04d}"}, "checks": [failed]}}}),
        )
        scenario.tick(*waits(KEY, rationale="its check failed"))
        scenario.time_passes(minutes=31)
        leaves = json.loads(LEAVES_FLAKY) | {"pr": READ_PR}
        return scenario.run(resumes(ResumeReason.CI), worker=worker_does(result=json.dumps(leaves)))

    heads = [git_pool.remote_head(BRANCH)]
    for name in ("m1", "m2"):
        main_moves(git_pool, name)
        kicked = red_again()
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
    assert scenario.ticket_state()["last_run"]["kicked"] == ["repo"]

    main_moves(git_pool, "m3")
    spent = red_again()
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


def test_a_rebase_that_would_drop_a_merges_own_change_is_no_kick(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"max_flaky_kicks": 2})
    scenario.run(worker=pushes())
    main_moves(git_pool, "m")
    # The branch merges main in, and the merge adds a file of its own, as a resolution would.
    seed = git_pool.slots[1]
    git("fetch", "--quiet", "origin", cwd=seed)
    git("checkout", "--quiet", "--detach", f"origin/{BRANCH}", cwd=seed)
    git("merge", "--quiet", "--no-ff", "--no-commit", "origin/main", cwd=seed)
    (seed / "resolved.txt").write_text("the merge's own\n")
    git("add", "resolved.txt", cwd=seed)
    git("commit", "--quiet", "-m", "PROJ-1: merge main", cwd=seed)
    git("push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=seed)
    before = git_pool.remote_head(BRANCH)

    left = leaves_flaky(scenario)
    assert left.status == "done"
    assert harness_note(left) == (
        f"repo: not kicked: rebasing {BRANCH} onto main would drop changes it holds, such as a merge's own"
    )
    assert git_pool.remote_head(BRANCH) == before


def test_a_kick_whose_push_fails_is_not_counted(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"max_flaky_kicks": 1})
    scenario.run(worker=pushes())
    main_moves(git_pool, "m")
    git_pool.reject_pushes()
    refused = leaves_flaky(scenario)
    assert harness_note(refused).startswith("repo: not kicked: the push failed: "), harness_note(refused)
    assert scenario.conn.execute("SELECT count(*) FROM flaky_kicks").fetchone()[0] == 0
    assert "kicked" not in contract.stored_object(refused.row["result_json"])


def test_only_a_resume_for_ci_is_kicked(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"max_flaky_kicks": 2})
    scenario.run(worker=pushes())
    before = git_pool.remote_head(BRANCH)
    main_moves(git_pool, "m")
    leaves_flaky(scenario, ResumeReason.REVIEW)
    assert git_pool.remote_head(BRANCH) == before


def test_the_sinks_hear_the_workers_estimate_of_why_a_check_is_flaky(scenario: Scenario, git_pool: GitPool) -> None:
    takes_runs(scenario)
    scenario.run(worker=pushes())
    left = leaves_flaky(scenario)
    [fields] = told(scenario)
    assert fields == {
        "ticket": KEY,
        "run": left.id,
        "prs": ["https://example.test/pr/1"],
        "kicked": [],
        "estimate": "unit-tests lost its runner",
        "cause": None,
        "note": None,
    }
    assert message.event_line("ci.flaky", fields) == (
        f"? {KEY} run {left.id} left a failed check as flaky; rerun it, or `canopy reply` that it is real: "
        "https://example.test/pr/1 why: unit-tests lost its runner"
    )

    scenario.configures(trust={"max_flaky_kicks": 1})
    main_moves(git_pool, "m")
    kicked = leaves_flaky(scenario)
    assert told(scenario)[-1]["kicked"] == ["repo"]
    assert message.event_line("ci.flaky", told(scenario)[-1]).startswith(
        f"+ {KEY} run {kicked.id} left a failed check as flaky; canopy pushed repo again to rerun it: ",
    )
    # Out of kicks: the note says why, and the operator reruns it.
    main_moves(git_pool, "m2")
    leaves_flaky(scenario)
    spent = told(scenario)[-1]
    assert spent["kicked"] == []
    assert "has had 1 kick(s) since its work was pushed" in str(spent["note"])


def test_the_cause_a_worker_names_reaches_the_overseer_as_a_word_and_its_line_on_why_only_the_sinks(
    scenario: Scenario,
    git_pool: GitPool,
    github_state: Path,
) -> None:
    takes_runs(scenario)
    # A PR the `vcs` source reads, so the overseer is listed the ticket (DESIGN §39), read within the hour.
    scenario.configures("private", connect={"max_age_minutes": 60})
    scenario.run(worker=pushes(prs={"repo": READ_PR}))
    run_ids = iter(range(77, 80))

    def last_run(said: Mapping[str, object]) -> tuple[Ran, dict[str, Any]]:
        """A check fails on a new head, and a `resume` leaves it flaky, saying `said`; and `last_run` after it."""
        run_id = next(run_ids)
        failed = {"name": "unit-tests", "status": "completed", "conclusion": "failure", "run_id": run_id}
        github_state.write_text(
            json.dumps({"prs": {READ_PR: {"pr": {"head_sha": f"abc{run_id:04d}"}, "checks": [failed]}}}),
        )
        scenario.tick(*waits(KEY, rationale="its check failed"))
        ran = leaves_flaky(scenario, adds={"pr": READ_PR, **said})
        scenario.tick(*waits(KEY, rationale="the operator reruns it"))
        return ran, scenario.ticket_state()["last_run"]

    left, seen = last_run({"flaky_cause": "service", "flaky_detail": "registry.npmjs.org returned 503"})
    assert seen["flaky_cause"] == "service"
    # Its line on why is kept with the run, and told to the sinks, never to the overseer.
    assert contract.stored_object(left.row["result_json"])["flaky_detail"] == "registry.npmjs.org returned 503"
    assert "registry" not in json.dumps(seen)
    [fields] = told(scenario)
    assert fields["cause"] == "service"
    assert message.event_line("ci.flaky", fields) == (
        f"? {KEY} run {left.id} left a failed check as flaky, likely a service the job calls; rerun it, or "
        f"`canopy reply` that it is real: {READ_PR} why: registry.npmjs.org returned 503"
    )

    # Unsure, or a word outside the vocabulary: no cause anywhere, and no guess.
    unsure_said: list[Mapping[str, object]] = [{}, {"flaky_cause": "the network"}]
    for said in unsure_said:
        unsure, seen = last_run(said)
        assert seen["flaky"] is True
        assert "flaky_cause" not in seen
        assert told(scenario)[-1]["cause"] is None
        assert message.event_line("ci.flaky", told(scenario)[-1]).startswith(
            f"? {KEY} run {unsure.id} left a failed check as flaky; rerun it, ",
        )


def test_a_flaky_bit_from_a_run_not_sent_for_ci_tells_the_sinks_nothing(scenario: Scenario, git_pool: GitPool) -> None:
    takes_runs(scenario)
    scenario.run(worker=pushes())
    leaves_flaky(scenario, ResumeReason.REVIEW)
    assert told(scenario) == []


def test_a_sink_with_the_default_groups_hears_of_each_forced_push(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(notify={"sinks": {"phone": {"cmd": "true"}}}, trust={"max_flaky_kicks": 1})
    scenario.run(worker=pushes())
    before = git_pool.remote_head(BRANCH)
    main_moves(git_pool, "m")

    kicked = leaves_flaky(scenario)
    [fields] = told(scenario, "ci.kicked")
    after = git_pool.remote_head(BRANCH)
    assert before is not None
    assert after is not None
    assert fields == {
        "ticket": KEY,
        "run": kicked.id,
        "repo": "repo",
        "branch": BRANCH,
        "pr": PR,
        "from_head": before,
        "to_head": after,
        "kick": 1,
        "limit": 1,
    }
    assert message.event_line("ci.kicked", fields) == (
        f"! {KEY} run {kicked.id}: canopy force-pushed {BRANCH} in repo to rerun a check left as flaky (kick 1 of 1): "
        f"{before[:12]} -> {after[:12]} {PR}"
    )
    # Out of kicks, nothing is pushed, so nothing is told; `ci.flaky` is in `runs`, which this sink does not take.
    main_moves(git_pool, "m2")
    leaves_flaky(scenario)
    assert len(told(scenario, "ci.kicked")) == 1
    assert told(scenario) == []


def test_a_kick_whose_push_fails_tells_no_sink(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(notify={"sinks": {"phone": {"cmd": "true"}}}, trust={"max_flaky_kicks": 1})
    scenario.run(worker=pushes())
    main_moves(git_pool, "m")
    git_pool.reject_pushes()
    leaves_flaky(scenario)
    assert told(scenario, "ci.kicked") == []


def test_a_batching_sink_hears_of_a_forced_push_at_once(
    scenario: Scenario,
    git_pool: GitPool,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "desk.txt"
    desk = {"cmd": f"{sink_script} {out}", "batch_minutes": 30}
    scenario.configures(notify={"sinks": {"desk": desk}}, trust={"max_flaky_kicks": 1})
    scenario.run(worker=pushes())
    main_moves(git_pool, "m")
    scenario.time_passes(minutes=31)  # past the CI cooldown, before the first delivery opens the batch window
    scenario.tick(raises("PROJ-9", "flaky_rerun"), *waits(KEY))
    assert len(messages(out)) == 1

    scenario.run(resumes(ResumeReason.CI), worker=worker_does(result=LEAVES_FLAKY))
    scenario.tick(raises("PROJ-9", "flaky_rerun"), *waits(KEY))
    [_, sent] = [json.loads(m) for m in messages(out)]
    assert [e["kind"] for e in sent["events"]] == ["ci.kicked"]
