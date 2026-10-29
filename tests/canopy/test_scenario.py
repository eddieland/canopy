"""The scenario DSL's own story: what a `Scenario` records of each move, for a failed test's report."""

import json
import os
import shlex
import sys
import tomllib
from datetime import timedelta
from unittest import mock

import pytest

from canopy.core import db
from canopy.core.vocab import ResumeReason, RunKind
from tests.canopy import scenario_helpers
from tests.canopy.conftest import Ws
from tests.canopy.helpers import (
    DRAFTS_PR,
    UNOBSERVED,
    UNOBSERVED_ITEM,
    InlineRunner,
    agent_runs,
    last_tick,
    present,
    waits,
)
from tests.canopy.review_helpers import CLEAN, PR, head, reviewer_reports
from tests.canopy.scenario_helpers import (
    Printed,
    Scenario,
    asks,
    dispatches,
    fails,
    pushes,
    raises,
    reviews,
    sends_drafts,
)
from tests.conftest import GitPool, git


def test_the_story_tells_each_move_and_what_canopy_did_with_it(scenario: Scenario, git_pool: GitPool) -> None:
    fix = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI])
    scenario.run(worker=pushes())
    held = db.format_time(scenario.run(fix, worker=pushes()).ended_at + timedelta(minutes=30))
    scenario.refuses(fix)
    scenario.time_passes(hours=1, minutes=30)
    scenario.seen("PROJ-2")
    # PROJ-1's PR is one no source reads, so the harness waits on it (DESIGN §39).
    scenario.tick(raises("PROJ-2", "needs_human"))
    scenario.operator("grant", "PROJ-1", "resume")
    assert scenario.told().splitlines() == [
        "1. run 1, implement of PROJ-1: done: did it",
        "2. run 2, resume of PROJ-1 for ci: done: did it",
        "3. tick 3 refuses canopy dispatch PROJ-1 --repo repo --kind resume --label agent-ready-tester --reason ci",
        f"     PROJ-1 refused:cooldown: a resume for CI alone in PROJ-1 in repo may run again after {held}",
        "4. 1:30:00 passes",
        "5. an earlier tick saw PROJ-2",
        "6. tick 4, exits 0: ok: 4 decisions: attention:needs_human=1, attention:unobserved_pr=1, queried=1, wait=1",
        f"     PROJ-1 attention:unobserved_pr: {UNOBSERVED_ITEM}",
        f"     PROJ-1 wait: {UNOBSERVED}",
        "     - queried: the query returned no open ticket",
        "     PROJ-2 attention:needs_human: PROJ-2 detail",
        "7. the operator runs canopy grant PROJ-1 resume, which exits 0",
        "     PROJ-1 in repo has had 1 resume runs, and may now have 7. The next tick decides whether to dispatch it.",
        "The attention list now: PROJ-1 unobserved_pr, PROJ-2 needs_human.",
    ]


def test_the_step_that_failed_is_in_the_story(scenario: Scenario) -> None:
    with pytest.raises(AssertionError, match="canopy grant PROJ-1 fix-ci exited 1, not 0: Error: grant refused"):
        scenario.operator("grant", "PROJ-1", "fix-ci")
    with pytest.raises(AssertionError):
        scenario.tick(code=1)
    assert scenario.told().splitlines() == [
        "1. the operator runs canopy grant PROJ-1 fix-ci, which exits 1",
        (
            "     Error: grant refused (bad_kind): a resume now fixes CI, and fix-ci runs count as resume runs: grant "
            "resume instead"
        ),
        "2. tick 1, exits 0: ok: no overseer, nothing left to judge; 1 decisions: queried=1",
        "     - queried: the query returned no open ticket",
        "The attention list now: nothing.",
    ]


def test_a_held_run_is_at_work_until_the_story_says_what_becomes_of_it(scenario: Scenario, git_pool: GitPool) -> None:
    working = scenario.starts(worker=pushes())
    assert working.row["status"] == "running"
    scenario.refuses(dispatches())
    assert working.finishes().status == "done"
    slot = git_pool.slots[0]  # run 1 gave it back
    [left] = scenario.tick(dispatches("PROJ-2"), hold=True).working
    left.dies()
    assert scenario.told().splitlines() == [
        "1. run 1, implement of PROJ-1: at work",
        "2. tick 2 refuses canopy dispatch PROJ-1 --repo repo --kind implement --label agent-ready-tester",
        "     PROJ-1 refused:running: run 1 is already working PROJ-1",
        "3. run 1, implement of PROJ-1: done: did it",
        "4. tick 3, exits 0: ok: 4 decisions: attention:unobserved_pr=1, dispatch:implement=1, queried=1, wait=1",
        f"     PROJ-1 attention:unobserved_pr: {UNOBSERVED_ITEM}",
        f"     PROJ-1 wait: {UNOBSERVED}",
        "     - queried: the query returned no open ticket",
        f"     PROJ-2 dispatch:implement: run 2: agent/PROJ-2-work in repo at {slot}; label agent-ready-tester",
        "     run 2, implement of PROJ-2: at work",
        "5. run 2, implement of PROJ-2: its `canopy _run` dies, its worker still at work",
        "The attention list now: PROJ-1 unobserved_pr.",
    ]


def test_each_ticket_a_tick_dispatches_plays_its_own_worker(scenario: Scenario, git_pool: GitPool) -> None:
    ticked = scenario.tick(dispatches(), dispatches("PROJ-2"), worker=pushes())
    # One script for both, each run playing it as made for its ticket: its own branch, message, and PR.
    assert [(r.key, r.status, r.branch) for r in ticked.runs] == [
        ("PROJ-1", "done", "agent/PROJ-1-work"),
        ("PROJ-2", "done", "agent/PROJ-2-work"),
    ]
    assert git("log", "-1", "--format=%s", "agent/PROJ-2-work", cwd=git_pool.origin) == "PROJ-2: the change"
    resumed = scenario.run(dispatches("PROJ-2", RunKind.RESUME, reasons=[ResumeReason.CI]))
    assert "PR: https://example.test/pr/2." in resumed.prompt  # the PR PROJ-2's own implement reported

    # And a ticket `workers` names plays the script it gives instead.
    ticked = scenario.tick(dispatches("PROJ-3"), dispatches("PROJ-4"), workers={"PROJ-4": fails()})
    assert [(r.key, r.status) for r in ticked.runs] == [("PROJ-3", "done"), ("PROJ-4", "failed")]


def test_a_held_run_plays_its_tickets_own_worker_once_it_finishes(scenario: Scenario, git_pool: GitPool) -> None:
    held = scenario.tick(dispatches(), dispatches("PROJ-2"), hold=True, worker=fails(), workers={"PROJ-2": asks()})
    assert [w.finishes().status for w in held.working] == ["failed", "blocked"]
    pushed = scenario.starts(dispatches("PROJ-3"), worker=pushes())
    assert pushed.finishes().branch == "agent/PROJ-3-work"
    assert git_pool.remote_head("agent/PROJ-3-work") is not None


def test_a_command_canopy_refuses_is_a_move_and_what_it_printed_is_the_operators_to_read(scenario: Scenario) -> None:
    refused = scenario.operator("show", "PROJ-1", code=1)
    assert refused.out == ""
    assert "PROJ-1" in refused.err
    paused = scenario.operator("pause")
    assert paused == Printed("Paused: the loop starts no tick until `canopy resume`.\n", "")
    [step, *said] = scenario.story[1].splitlines()
    assert (step, said) == ("the operator runs canopy pause, which exits 0", [f"  {paused.out.strip()}"])


def test_a_step_keeps_the_first_lines_a_command_printed_and_every_line_of_its_errors() -> None:
    printed = Printed("first\n\nsecond\nthird\nfourth\n", "Error: no\n")
    assert printed.told() == ["  first", "  second", "  (2 more lines)", "  Error: no"]
    assert Printed("one\ntwo\n", "").told() == ["  one", "  two"]


def test_a_tick_gives_back_what_it_printed(scenario: Scenario) -> None:
    ticked = scenario.tick(dry_run=True)
    assert ticked.printed.out.startswith(f"tick {ticked.tick.id}: ok: dry run")


def test_what_a_command_that_raises_printed_is_left_in_the_tests_own_output(
    scenario: Scenario,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def crashes(*args: str) -> int:
        sys.stdout.write(f"{args[0]}: half done\n")
        sys.stderr.write("then this\n")
        raise RuntimeError("a bug in canopy")

    with (
        mock.patch.object(scenario_helpers, "operator", autospec=True, side_effect=crashes),
        pytest.raises(RuntimeError, match="a bug in canopy"),
    ):
        scenario.operator("pause")
    assert capsys.readouterr() == ("pause: half done\n", "then this\n")
    assert scenario.story == []


def test_the_config_a_test_sets_is_a_move_and_lands_in_its_own_table(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(policy={"max_resume_attempts": 1})
    # The tests' tracker labels the tickets it holds with the queue label it is given.
    mine = {"sources": {"jira": {"cmd": "connector jira --labeled mine"}}}
    scenario.configures(policy={"max_implement_attempts": 3}, tracker={"labels": ["mine"]}, connect=mine)
    scenario.configures("workspace", tracker={"needs_human_label": "blocked-on-team"})
    scenario.configures("private", notify={"sinks": {"log": {"cmd": "true", "events": ["runs"]}}})
    # Each key in its own table, though the user file ended on `[paths]`; a key set again takes the place of the old.
    user = tomllib.loads(scenario.env.user_file.read_text())
    assert user["policy"] == {"max_resume_attempts": 1, "max_implement_attempts": 3}
    assert (user["tracker"], user["paths"]) == ({"labels": ["mine"]}, {})
    assert user["runtime"]["worker_cmd"].endswith("--agent canopy-worker --title={title} {prompt}")
    tracker = tomllib.loads(scenario.env.shared_file.read_text())["tracker"]
    assert tracker == {"provider": "jira", "query": "project = PROJ", "needs_human_label": "blocked-on-team"}
    assert scenario.told().splitlines()[:4] == [
        "1. the user file sets policy.max_resume_attempts = 1",
        (
            '2. the user file sets policy.max_implement_attempts = 3, tracker.labels = ["mine"], '
            'connect.sources.jira.cmd = "connector jira --labeled mine"'
        ),
        '3. the workspace file sets tracker.needs_human_label = "blocked-on-team"',
        '4. the private file sets notify.sinks.log.cmd = "true", notify.sinks.log.events = ["runs"]',
    ]

    # And the next command reads them: one resume, then the limit.
    resume = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW], label="mine")
    scenario.run(dispatches(label="mine"), worker=pushes())
    scenario.run(resume, worker=pushes())
    [(action, _), _] = scenario.refuses(resume)
    assert action == "refused:attempt_limit"


def test_time_passes_for_every_time_the_journal_recorded(scenario: Scenario) -> None:
    db.record_event(scenario.conn, db.Event("runs", "run.started", {"ticket": "PROJ-1"}))
    scenario.operator("start", "PROJ-1")
    scenario.operator("reply", "PROJ-1", "Use the v2 client.")
    scenario.tick(*waits("PROJ-1"))
    times = "SELECT (SELECT at FROM notify_events), (SELECT at FROM messages), (SELECT started_at FROM ticks)"
    before = [db.parse_time(t) for t in scenario.conn.execute(times).fetchone()]
    scenario.time_passes(hours=2)
    after = [db.parse_time(t) for t in scenario.conn.execute(times).fetchone()]
    # A plain `at` moves with the `_at` columns, so an event or a message stays where it was beside the tick.
    assert [b - a for a, b in zip(after, before, strict=True)] == [timedelta(hours=2)] * 3


def test_a_run_takes_a_runner_of_its_own_and_gives_back_what_it_printed(scenario: Scenario, git_pool: GitPool) -> None:
    timed_out = scenario.run(runner=InlineRunner(timeout_agent=True))
    assert timed_out.status == "timeout"
    assert "run 1: timeout" in timed_out.printed.out
    assert scenario.story == [str(timed_out)]


def test_a_story_in_two_repositories_names_them_and_a_joint_worker_pushes_in_each(
    ws_scenario: Scenario,
    ws: Ws,
) -> None:
    both = ("api", "web")
    assert dispatches(repo=both)[:6] == ["canopy", "dispatch", "PROJ-1", "--repo", "api", "--repo"]
    joint = ws_scenario.run(dispatches(repo=both), worker=pushes(repos=both))
    assert (joint.status, joint.branch) == ("done", "agent/PROJ-1-work")
    assert all(ws.remote_head(name, "agent/PROJ-1-work") is not None for name in both)
    assert {u.repo: u.pr_url for u in db.units(ws_scenario.conn, "PROJ-1")} == {
        "api": "https://example.test/api/pr/1",
        "web": "https://example.test/web/pr/1",
    }
    # A ticket in one repository of the two pushes there alone, as a run in one slot does.
    alone = ws_scenario.run(dispatches("PROJ-2", repo="web"), worker=pushes())
    assert alone.status == "done"
    assert ws.remote_head("web", "agent/PROJ-2-work") is not None
    assert ws.remote_head("api", "agent/PROJ-2-work") is None
    assert ws_scenario.told().splitlines()[:2] == [
        "1. run 1, implement of PROJ-1: done: did it",
        "2. run 2, implement of PROJ-2: done: did it",
    ]


def reviews_on(scenario: Scenario) -> None:
    """Reviews on for the loop's own PRs, the reviewer running the fake agent, and PROJ-1's unit having opened PR."""
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"
    scenario.configures(runtime={"review_cmd": template}, review={"agent_prs": True})
    db.set_unit(scenario.conn, "PROJ-1", str(scenario.env.root), "repo", pr_url=PR)


def test_a_review_is_a_move_and_so_is_one_canopy_refuses(scenario: Scenario, git_pool: GitPool) -> None:
    reviews_on(scenario)
    sha = head(git_pool)
    assert reviews(sha, ticket="PROJ-1")[-2:] == ["--ticket", "PROJ-1"]

    reviewed = scenario.review(reviews(sha), reviewer=reviewer_reports(CLEAN))
    assert (reviewed.status, reviewed.row.sha, reviewed.row.pr_url) == ("done", sha, PR)
    assert reviewed.prompt.startswith("# canopy reviewer\n")
    assert f"review run {reviewed.id}" in reviewed.printed.out
    [(action, _)] = scenario.refuses(reviews(sha))
    assert action == "refused:reviewed"
    _, review_step, refused_step, _ = scenario.told().split("\n", 3)
    # What canopy noted of the report is told with it.
    noted = "reported low impact, but review.low_impact is not set; recorded as normal"
    assert review_step == f"2. review run 1 of {PR} at {sha[:7]}: done: clean: Nothing found.: {noted}"
    assert refused_step == f"3. tick 2 refuses {shlex.join(reviews(sha))}"


def test_a_review_held_at_work_runs_until_the_story_says_what_becomes_of_it(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    reviews_on(scenario)
    sha = head(git_pool)
    reviewing = scenario.starts_review(reviews(sha), reviewer=reviewer_reports(CLEAN))
    assert reviewing.row.status == "running"
    assert scenario.refuses(reviews(sha)) == [("refused:running", f"review run {reviewing.id} of this PR is running")]
    reviewed = reviewing.finishes()
    assert (reviewed.status, reviewed.row.sha) == ("done", sha)
    assert "--- reviewer exit 0 ---" in reviewed.printed.out
    killed = scenario.starts_review(reviews(sha, pr=f"{PR}0"), reviewer=reviewer_reports(CLEAN))
    killed.dies()
    assert killed.row.status == "running"  # for the next tick's reconcile to find
    _, at_work, refused, done, _, _ = [line for line in scenario.told().splitlines() if line[0].isdigit()]
    assert (at_work, refused) == (
        f"2. review run 1 of {PR} at {sha[:7]}: at work",
        f"3. tick 2 refuses {shlex.join(reviews(sha))}",
    )
    assert done.startswith(f"4. review run 1 of {PR} at {sha[:7]}: done: clean")
    assert (
        scenario.story[-1]
        == f"review run 2 of {PR}0 at {sha[:7]}: its `canopy _review` dies, its reviewer still at work"
    )


def test_every_role_a_run_plays_is_held(scenario: Scenario, git_pool: GitPool) -> None:
    # A started ticket's run is worked privately, by its own role, and held as a worker is.
    scenario.operator("start", "PROJ-1")
    working = scenario.starts(dispatches(label=None))
    assert agent_runs(scenario.agent_log) == []  # held before it did anything
    assert working.finishes().status == "done"
    [agent] = agent_runs(scenario.agent_log)
    assert agent["argv"][:3] == ["run", "--agent", "canopy-worker-private"]
    with scenario._held():  # noqa: SLF001  (each role's script, as a held run reads it)
        gated = {role: json.loads(os.environ[f"FAKE_{role}_COMMANDS"])[0][2] for role in scenario_helpers.HELD_ROLES}
        assert "FAKE_OVERSEER_COMMANDS" not in os.environ
    assert set(gated.values()) == {scenario_helpers.GATE}


def test_a_worker_sends_drafts_beside_its_pr(scenario: Scenario, git_pool: GitPool) -> None:
    ran = scenario.run(worker=sends_drafts([{"on": "pr", "pr": DRAFTS_PR, "text": "Ready for review."}]))
    assert json.loads(ran.row["result_json"])["prs"] == {"repo": DRAFTS_PR}
    # What the worker reported, as the run log carries it; canopy keeps the drafts where `trust.review_replies` says.
    [reported] = [json.loads(line) for line in ran.printed.out.splitlines() if line.startswith('{"status"')]
    assert reported["drafts"] == [{"on": "pr", "pr": DRAFTS_PR, "text": "Ready for review."}]


def test_a_key_set_to_none_is_dropped_and_the_story_says_so(scenario: Scenario) -> None:
    scenario.configures(notify={"sinks": {"log": {"cmd": "true"}, "phone": {"cmd": "true"}}})
    scenario.configures(notify={"sinks": {"log": None}}, policy={"max_resume_attempts": 2})
    user = tomllib.loads(scenario.env.user_file.read_text())
    assert (user["notify"]["sinks"], user["policy"]) == ({"phone": {"cmd": "true"}}, {"max_resume_attempts": 2})
    assert scenario.story[-1] == "the user file sets no notify.sinks.log, policy.max_resume_attempts = 2"


def test_a_refusal_gives_back_its_tick_its_decisions_whole_and_what_it_printed(scenario: Scenario) -> None:
    refused = scenario.refuses(dispatches(repo="nope"))
    assert refused == [("refused:unknown_repo", "'nope' is not a repository in this workspace (repo)")]
    assert refused.tick == last_tick(scenario.conn).id
    [decision] = refused.decisions
    assert (decision.tick_id, decision.ticket_key) == (refused.tick, "PROJ-1")
    assert "dispatch refused (unknown_repo)" in refused.printed.err
    # A list's own methods make a plain one of what was decided.
    assert refused[:1] == [("refused:unknown_repo", "'nope' is not a repository in this workspace (repo)")]


def test_the_overseer_runs_a_command_in_a_tick_of_its_own_or_in_one_held_open(scenario: Scenario) -> None:
    refused = scenario.overseer("ticket", "set", "PROJ-1", "--phase", "conflicted", "--repo", "nope", code=1)
    assert "'nope' is not a repository" in refused.err
    with scenario.ticking() as tick_id:
        scenario.overseer("attention", "PROJ-1", "needs_human", "--detail", "one")
        scenario.overseer("attention", "PROJ-2", "needs_human", "--detail", "two")
    # Both raised in the one tick, which ended ok, so both are on the attention list.
    assert scenario.attention() == [("PROJ-1", "needs_human"), ("PROJ-2", "needs_human")]
    steps = [line for line in scenario.told().splitlines() if line[0].isdigit()]
    assert steps[1:] == [
        f"2. tick {tick_id} begins, for the overseer's commands",
        f"3. the overseer runs canopy attention PROJ-1 needs_human --detail one in tick {tick_id}, which exits 0",
        f"4. the overseer runs canopy attention PROJ-2 needs_human --detail two in tick {tick_id}, which exits 0",
        f"5. tick {tick_id} ends ok",
    ]


def test_the_overseer_acts_in_a_dry_run_tick_as_in_any_other(scenario: Scenario) -> None:
    with scenario.ticking(dry_run=True) as tick_id:
        # Still running while the block lasts, so the test may look at it.
        assert present(db.get_tick(scenario.conn, tick_id)).ended_at is None
        scenario.overseer("decide", "PROJ-1", "wait", "--rationale", "dry")
    assert present(db.get_tick(scenario.conn, tick_id)).dry_run
    scenario.overseer("decide", "PROJ-2", "wait", "--rationale", "dry too", dry_run=True)
    assert present(db.get_tick(scenario.conn, last_tick(scenario.conn).id)).dry_run
    assert scenario.story[0] == f"dry-run tick {tick_id} begins, for the overseer's commands"
