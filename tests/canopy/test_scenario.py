"""The scenario DSL's own story: what a `Scenario` records of each move, for a failed test's report."""

from datetime import timedelta

import pytest

from canopy.core import db
from canopy.core.vocab import ResumeReason, RunKind
from tests.canopy.helpers import waits
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes, raises
from tests.conftest import GitPool


def test_the_story_tells_each_move_and_what_canopy_did_with_it(scenario: Scenario, git_pool: GitPool) -> None:
    fix = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI])
    scenario.run(worker=pushes())
    held = db.format_time(scenario.run(fix, worker=pushes()).ended_at + timedelta(minutes=30))
    scenario.refuses(fix)
    scenario.time_passes(hours=1, minutes=30)
    scenario.seen("PROJ-2")
    scenario.tick(*waits("PROJ-1"), raises("PROJ-2", "needs_human"))
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
        "The attention list now: PROJ-2 needs_human.",
    ]


def test_the_step_that_failed_is_in_the_story(scenario: Scenario) -> None:
    with pytest.raises(AssertionError):
        scenario.operator("grant", "PROJ-1", "fix-ci")
    with pytest.raises(AssertionError):
        scenario.tick(code=1)
    assert scenario.told().splitlines() == [
        "1. the operator runs canopy grant PROJ-1 fix-ci, which exits 1",
        "2. tick 1, exits 0: ok: 1 decisions: queried=1",
        "     - queried: the query returned no open ticket",
        "The attention list now: nothing.",
    ]
