"""The scenario DSL's own story: what a `Scenario` records of each move, for a failed test's report."""

import sys
import tomllib
from datetime import timedelta
from unittest import mock

import pytest

from canopy.core import db
from canopy.core.vocab import ResumeReason, RunKind
from tests.canopy import scenario_helpers
from tests.canopy.conftest import Ws
from tests.canopy.helpers import InlineRunner, waits
from tests.canopy.scenario_helpers import Printed, Scenario, asks, dispatches, fails, pushes, raises
from tests.conftest import GitPool, git


def test_the_story_tells_each_move_and_what_canopy_did_with_it(scenario: Scenario, git_pool: GitPool) -> None:
    fix = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI])
    scenario.run(worker=pushes())
    held = db.format_time(scenario.run(fix, worker=pushes()).ended_at + timedelta(minutes=30))
    scenario.refuses(fix)
    scenario.time_passes(hours=1, minutes=30)
    scenario.seen("PROJ-2")
    scenario.tick(*waits("PROJ-1"), raises("PROJ-2", "needs_human"))
    scenario.operator("grant", "PROJ-1", "resume")
    assert scenario.told().splitlines() == [
        "1. run 1, implement of PROJ-1: done: did it",
        "2. run 2, resume of PROJ-1 for ci: done: did it",
        "3. tick 3 refuses canopy dispatch PROJ-1 --repo repo --kind resume --label agent-ready-tester --reason ci",
        f"     PROJ-1 refused:cooldown: a resume for CI alone in PROJ-1 in repo may run again after {held}",
        "4. 1:30:00 passes",
        "5. an earlier tick saw PROJ-2",
        "6. tick 4, exits 0: ok: 3 decisions: attention:needs_human=1, queried=1, wait=1",
        "     - queried: the query returned no open ticket",
        "     PROJ-1 wait: nothing to do yet",
        "     PROJ-2 attention:needs_human: PROJ-2 detail",
        "7. the operator runs canopy grant PROJ-1 resume, which exits 0",
        "     PROJ-1 in repo has had 1 resume runs, and may now have 7. The next tick decides whether to dispatch it.",
        "The attention list now: PROJ-2 needs_human.",
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
        "2. tick 1, exits 0: ok: 1 decisions: queried=1",
        "     - queried: the query returned no open ticket",
        "The attention list now: nothing.",
    ]


def test_a_held_run_is_at_work_until_the_story_says_what_becomes_of_it(scenario: Scenario, git_pool: GitPool) -> None:
    working = scenario.starts(worker=pushes())
    assert working.row["status"] == "running"
    scenario.refuses(dispatches())
    assert working.finishes().status == "done"
    slot = git_pool.slots[0]  # run 1 gave it back
    [left] = scenario.tick(*waits("PROJ-1"), dispatches("PROJ-2"), hold=True).working
    left.dies()
    assert scenario.told().splitlines() == [
        "1. run 1, implement of PROJ-1: at work",
        "2. tick 2 refuses canopy dispatch PROJ-1 --repo repo --kind implement --label agent-ready-tester",
        "     PROJ-1 refused:running: run 1 is already working PROJ-1",
        "3. run 1, implement of PROJ-1: done: did it",
        "4. tick 3, exits 0: ok: 3 decisions: dispatch:implement=1, queried=1, wait=1",
        "     - queried: the query returned no open ticket",
        "     PROJ-1 wait: nothing to do yet",
        f"     PROJ-2 dispatch:implement: run 2: agent/PROJ-2-work in repo at {slot}; label agent-ready-tester",
        "     run 2, implement of PROJ-2: at work",
        "5. run 2, implement of PROJ-2: its `canopy _run` dies, its worker still at work",
        "The attention list now: nothing.",
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
    first, second = (dispatches(key, RunKind.RESUME, reasons=[ResumeReason.REVIEW]) for key in ("PROJ-1", "PROJ-2"))
    ticked = scenario.tick(first, second, workers={"PROJ-2": fails()})
    assert [(r.key, r.status) for r in ticked.runs] == [("PROJ-1", "done"), ("PROJ-2", "failed")]


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
    scenario: Scenario, capsys: pytest.CaptureFixture[str]
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
    scenario.configures(policy={"max_implement_attempts": 3}, tracker={"labels": ["mine"]})
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
        '2. the user file sets policy.max_implement_attempts = 3, tracker.labels = ["mine"]',
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
    ws_scenario: Scenario, ws: Ws
) -> None:
    both = ("api", "web")
    assert dispatches(repo=both)[:6] == ["canopy", "dispatch", "PROJ-1", "--repo", "api", "--repo"]
    joint = ws_scenario.run(dispatches(repo=both), worker=pushes(repos=both))
    assert (joint.status, joint.branch) == ("done", "agent/PROJ-1-work")
    assert all(ws.remote_head(name, "agent/PROJ-1-work") is not None for name in both)
    assert {u["repo"]: u["pr_url"] for u in db.units(ws_scenario.conn, "PROJ-1")} == {
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
