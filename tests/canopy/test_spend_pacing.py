"""Spend pacing (DESIGN §6, ROADMAP M13): a daily budget spaces ticks by what the overseer recently cost.

The rule is checked on ticks written by hand; the waits the loop chooses, against the fake overseer on a fake clock, as
`test_idle_pacing.py` does. The fake overseer costs $0.25 a tick unless told otherwise: two steps of $0.125.
"""

import contextlib
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import db
from canopy.infra import resources
from canopy.loop import pacing, repeat
from tests.canopy.test_idle_pacing import KEY, log_lines, recorded, waits
from tests.canopy.test_loop import FakeTime, canopy, console, context, overseer_does
from tests.conftest import CanopyEnv

DAY = 24 * 60 * 60


def loop_config(env: CanopyEnv, *, interval: int, cap: int, budget: float) -> None:
    """Pace the loop, and have the overseer report what it cost, as `--format json` does."""
    text = env.user_file.read_text().replace("--agent canopy-overseer", "--agent canopy-overseer --format json")
    env.write_user(
        text + f"\n[loop]\ninterval_minutes = {interval}\nidle_max_minutes = {cap}\ndaily_budget_usd = {budget}\n"
    )


@contextlib.contextmanager
def overseer_costs(dollars: float) -> Iterator[None]:
    """Until the block ends, each fake overseer run costs `dollars`, over its two steps."""
    with mock.patch.dict(os.environ, {"FAKE_OVERSEER_STEP_COST": str(dollars / 2)}):
        yield


def priced_ticks(env: CanopyEnv, *costs: float | None) -> None:
    """Write a finished tick per cost, oldest first; None is a tick the runtime reported no cost for."""
    conn = env.journal(migrate=False)
    db.migrate(conn, resources.migrations_dir())
    for cost in costs:
        tick_id = db.start_tick(conn, dry_run=True)
        conn.execute("UPDATE ticks SET cost_usd = ? WHERE id = ?", (cost, tick_id))
        db.finish_tick(conn, tick_id, "ok", "")


@pytest.mark.parametrize(
    ("budget", "costs", "expected"),
    [
        pytest.param(0.0, (1.0,), 0, id="no budget"),
        pytest.param(24.0, (), 0, id="no tick yet"),
        pytest.param(24.0, (None, None), 0, id="no tick priced"),
        # $0.50 a tick at $24 a day: 48 ticks a day, 30 minutes apart.
        pytest.param(24.0, (0.5,), 1800, id="one tick"),
        # The mean of the latest five priced ticks, newest last: the $9 one is the sixth back, and the unpriced ones
        # do not count as free.
        pytest.param(24.0, (9.0, 1.0, None, 0.0, 0.5, None, 0.5, 0.5), 1800, id="latest five priced"),
    ],
)
def test_the_budget_asks_for_the_recent_mean_cost_as_a_share_of_a_day(
    canopy_env: CanopyEnv, budget: float, costs: tuple[float | None, ...], expected: float
) -> None:
    priced_ticks(canopy_env, *costs)
    pace = pacing.Pace(base_seconds=60, cap_seconds=60, budget_usd_per_day=budget)
    assert pacing.spent(context(canopy_env), pace) == pytest.approx(expected)


def test_a_gate_ends_a_budget_wait_sooner_with_idle_pacing_on(canopy_env: CanopyEnv) -> None:
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    now = datetime.now(UTC)
    with mock.patch.object(pacing, "gate", autospec=True, return_value=now + timedelta(minutes=10)):
        assert pacing.wait(ctx, pacing.Pace(60, 240, budget_usd_per_day=1.0), 7200, now) == pytest.approx(600)
        # With idle pacing off, nothing shortens it, as before M21.
        assert pacing.wait(ctx, pacing.Pace(60, 60, budget_usd_per_day=1.0), 7200, now) == 7200


def test_costly_ticks_lengthen_the_wait_and_cheaper_ones_bring_it_back_to_base(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    # Idle pacing off, so the waits are the budget's alone. $0.25 a tick at $6 a day: an hour apart.
    loop_config(canopy_env, interval=1, cap=1, budget=6)
    with (
        overseer_does(canopy("decide", KEY, "wait", "--rationale", "checks pending")),
        overseer_costs(0.25),
        contextlib.ExitStack() as later,
    ):
        time = FakeTime()

        def at_first_wait() -> None:
            # From here ticks cost nothing: the mean falls as they replace the costly one, until it is gone.
            if len(time.slept) == 1:
                later.enter_context(overseer_costs(0))

        time.on_sleep = at_first_wait
        term, out = console()

        statuses = repeat.run(
            context(canopy_env),
            dry_run=True,
            interval_minutes=None,
            max_ticks=7,
            console=term,
            stop=repeat.Stop(),
            sleep=time.sleep,
            clock=time.clock,
        )

        assert statuses == {"ok": 7}
        # The mean of [0.25], [0.25, 0], ... over five ticks, then five free ones: back to the interval.
        assert waits(canopy_env) == [(0, 3600), (0, 1800), (0, 1200), (0, 900), (0, 720), (0, 60)]
        assert [line["spend_seconds"] for line in log_lines(canopy_env, "loop waits")] == [
            3600,
            1800,
            1200,
            900,
            720,
            0,
        ]
        text = out.getvalue()
        assert "wait 1 minute after each tick ends, longer if the overseer would spend over $6.00 a day" in text
        assert "paced by budget, next tick in 1h at" in text
        assert "attention 0  ·  cost $0.25, 11.5k tokens  ·  paced by budget, next tick in 1h at" in text
        assert "paced by budget, next tick in 1m at" not in text
        [started] = log_lines(canopy_env, "loop started")
        assert started["daily_budget_usd"] == 6
        # A wait the budget chose and that ran its length is the timer's, not a gate's.
        assert [woken for _, woken in recorded(canopy_env)] == ["start", *["timer"] * 6]


def test_the_loop_waits_the_longer_of_idle_pacing_and_the_budget(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    # $0.25 a tick at $72 a day: 5 minutes apart. Idle pacing doubles from 1 minute up to 8.
    loop_config(canopy_env, interval=1, cap=8, budget=72)
    with overseer_does(), overseer_costs(0.25):
        time = FakeTime()
        term, out = console()
        repeat.run(
            context(canopy_env),
            dry_run=True,
            interval_minutes=None,
            max_ticks=5,
            console=term,
            stop=repeat.Stop(),
            sleep=time.sleep,
            clock=time.clock,
        )
        assert waits(canopy_env) == [(0, 300), (1, 300), (2, 300), (3, 480)]
        text = out.getvalue()
        assert "idle 2, paced by budget, next tick in 5m at" in text
        # Once idle pacing asks for longer, the budget did not choose the wait.
        assert "idle 3, next tick in 8m at" in text


def test_a_budget_the_ticks_stay_under_keeps_todays_pacing(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    loop_config(canopy_env, interval=1, cap=1, budget=1000)
    with overseer_does(), overseer_costs(0.25):
        time = FakeTime()
        term, out = console()
        repeat.run(
            context(canopy_env),
            dry_run=True,
            interval_minutes=None,
            max_ticks=3,
            console=term,
            stop=repeat.Stop(),
            sleep=time.sleep,
            clock=time.clock,
        )
        assert waits(canopy_env) == [(0, 60), (0, 60)]
        assert "paced by budget" not in out.getvalue()
