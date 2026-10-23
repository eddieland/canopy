"""A tick without the overseer (DESIGN §39, ROADMAP M39): when the harness's decisions leave it nothing, the tick makes
the harness's dispatches and closes `ok` with the attention list as it stands, running no overseer and costing nothing.

Each story spaces the tracker query an hour apart and runs it once in a first tick, so a later one owes no query, the
one duty no ticket is needed for.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest

from canopy.core import db
from canopy.core.vocab import Decider, TickStatus
from canopy.loop import pacing, tick
from tests.canopy.helpers import KEY, agent_runs, context, in_tick, present, waits
from tests.canopy.observation_helpers import branches_read
from tests.canopy.scenario_helpers import dispatches, raises

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario, Working
    from tests.conftest import CanopyEnv, GitPool

#: A chore with no `when`, which the harness runs (DESIGN §37), and one with a `when`, which the overseer decides.
MINE, THEIRS = "deps", "build-health"
#: How long a test waits on a chore run to end.
CHORE_SECONDS = 30


@pytest.fixture
def quiet(scenario: Scenario) -> Scenario:
    """The query spaced an hour apart, and run by a first tick, so no tick after it owes one."""
    scenario.configures(tracker={"query_every_minutes": 60})
    scenario.tick()
    return scenario


def test_a_tick_with_nothing_left_runs_no_overseer_makes_the_harnesss_dispatches_and_keeps_the_list(
    quiet: Scenario,
    git_pool: GitPool,
) -> None:
    working = at_work_with_an_item(quiet)
    chores(quiet, MINE)
    overseers = overseer_runs(quiet.agent_log)
    ticked = quiet.tick()
    assert overseer_runs(quiet.agent_log) == overseers
    assert (ticked.tick.status, ticked.tick.overseer_ran, ticked.tick.cost_usd) == (TickStatus.OK, False, None)
    assert present(ticked.tick.summary).startswith(f"{tick.NO_OVERSEER}; 2 decisions")
    assert [(d.ticket_key, d.chore, d.action, d.decider) for d in ticked.decisions if d.decider is not None] == [
        (KEY, None, "wait", Decider.HARNESS),
        (None, MINE, "dispatch:chore", Decider.HARNESS),
    ]
    # The overseer's item stands, and the list is published as it stands.
    assert quiet.attention() == [(KEY, "needs_author")]
    assert f"- {KEY}, " in (quiet.env.state_dir / "attention.md").read_text()
    chore_ended(quiet.conn)
    working.finishes()


def test_a_tick_with_a_ticket_left_runs_the_overseer(quiet: Scenario) -> None:
    quiet.seen("PROJ-2")
    ticked = quiet.tick(*waits("PROJ-2"))
    assert (ticked.tick.status, ticked.tick.overseer_ran) == (TickStatus.OK, True)
    assert overseer_runs(quiet.agent_log) == 2


def test_a_tick_with_a_due_chore_with_a_when_runs_the_overseer(quiet: Scenario) -> None:
    chores(quiet, THEIRS, when="Weekdays only.")
    ticked = quiet.tick(["canopy", "chore", "wait", THEIRS, "--rationale", "not a weekday"])
    assert ticked.tick.overseer_ran is True


def test_a_dry_run_with_nothing_left_runs_no_overseer_and_starts_nothing(quiet: Scenario) -> None:
    chores(quiet, MINE)
    ticked = quiet.tick(dry_run=True)
    assert (ticked.tick.status, ticked.tick.overseer_ran) == (TickStatus.OK, False)
    assert present(ticked.tick.summary).startswith(f"dry run; {tick.NO_OVERSEER}")
    assert overseer_runs(quiet.agent_log) == 1
    assert quiet.conn.execute("SELECT count(*) FROM chore_runs").fetchone()[0] == 0


def test_a_tick_with_nothing_left_and_too_little_disk_closes_disk_low_and_starts_nothing(quiet: Scenario) -> None:
    chores(quiet, MINE)
    quiet.configures(loop={"min_free_disk_mib": 2**40})  # more than any disk the tests run on has free
    ticked = quiet.tick(code=1)
    assert (ticked.tick.status, ticked.tick.overseer_ran) == (TickStatus.DISK_LOW, False)
    assert ticked.actions == ["attention:disk_low"]
    assert quiet.conn.execute("SELECT count(*) FROM chore_runs").fetchone()[0] == 0


def test_a_tick_that_ran_no_overseer_leaves_the_idle_count_as_it_was(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    # Idle pacing paces the overseer's runs alone (DESIGN §39); any other tick counts as it did.
    with in_tick(conn, ends_ok=True) as without:
        db.set_tick_overseer(conn, without, ran=False)
    with in_tick(conn, ends_ok=True) as ran:
        db.set_tick_overseer(conn, ran, ran=True)
    ctx = context(canopy_env)
    assert pacing.count(ctx, tick.Outcome(without, TickStatus.OK, ""), 3, idle=True, on=True) == 3
    assert pacing.count(ctx, tick.Outcome(without, TickStatus.OK, ""), 3, idle=False, on=True) == 3
    assert pacing.count(ctx, tick.Outcome(ran, TickStatus.OK, ""), 3, idle=True, on=True) == 4
    assert pacing.count(ctx, tick.Outcome(ran, TickStatus.OK, ""), 3, idle=False, on=True) == 0
    assert pacing.count(ctx, tick.Outcome(None, "lock_busy", ""), 3, idle=False, on=True) == 0


def at_work_with_an_item(scenario: Scenario) -> Working:
    """KEY started privately, its worker held at work, and an item the overseer raised on it.

    Its repository's branches are read whole, so every row the derivation finds for it is `running`: the harness's.

    Returns:
        The run at work.
    """
    scenario.operator("start", KEY)
    [working] = scenario.tick(dispatches(label=None), raises(KEY, "needs_author"), hold=True).working
    branches_read(scenario.conn, at=db.now())
    scenario.conn.commit()
    return working


def chores(scenario: Scenario, name: str, *, when: str | None = None) -> None:
    """Configure chore `name`, due as it has never run, its command the fake agent, and its `when` if given."""
    prompt = scenario.env.home / "chores" / f"{name}.md"
    prompt.parent.mkdir(exist_ok=True)
    prompt.write_text(f"# {name}\n")
    table: dict[str, Any] = {
        "prompt": str(prompt),
        "cmd": "agent run --agent canopy-chore {prompt}",
        "every_minutes": 120,
    }
    if when is not None:
        table["when"] = when
    scenario.configures(chores={name: table})


def overseer_runs(agent_log: Path) -> int:
    """How many overseer runs the fake agent logged."""
    return sum(run["argv"][:3] == ["run", "--agent", "canopy-overseer"] for run in agent_runs(agent_log))


def chore_ended(conn: sqlite3.Connection) -> None:
    """Wait for every chore run to end, so none outlives the test."""
    deadline = time.monotonic() + CHORE_SECONDS
    while conn.execute("SELECT count(*) FROM chore_runs WHERE status = 'running'").fetchone()[0]:
        assert time.monotonic() < deadline, "a chore run did not end"
        time.sleep(0.05)
