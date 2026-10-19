"""The scenario DSL's own story: what a `Scenario` records of each move, for a failed test's report."""

from datetime import timedelta

import pytest

from canopy.core import db
from canopy.core.vocab import ResumeReason, RunKind
from tests.canopy.helpers import waits
from tests.canopy.scenario_helpers import Printed, Scenario, dispatches, pushes, raises
from tests.conftest import GitPool


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
