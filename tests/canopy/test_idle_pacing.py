"""Idle pacing (DESIGN §6, ROADMAP M21): longer waits after idle ticks in a row, gates, and early wakes.

What makes a tick idle is checked on a journal written by hand, with no overseer; the waits the loop chooses, against
the fake overseer on a fake clock, as `test_loop.py` does.
"""

import json
import os
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.context import Context
from canopy.infra import resources
from canopy.loop import pacing, repeat, tick
from tests.canopy.test_chores import chore_toml
from tests.canopy.test_loop import FakeTime, canopy, console, context, overseer_does
from tests.conftest import CanopyEnv

KEY = "PROJ-1"
PR = "https://example.test/pr/1"
# The journal's clock and the test's: a tick's `read_at` is put this far back, so what the test records after it is
# after it, whatever the millisecond.
BACK = timedelta(seconds=1)
# Where hand-made runs say they log; nothing is written there.
LOGS = Path("logs")

type Step = Callable[[sqlite3.Connection, int], object]


def stamp(moment: datetime) -> str:
    return db.format_time(moment)


def ago(**delta: float) -> str:
    return stamp(datetime.now(UTC) - timedelta(**delta))


def loop_config(env: CanopyEnv, *, interval: int, cap: int) -> None:
    env.write_user(env.user_file.read_text() + f"\n[loop]\ninterval_minutes = {interval}\nidle_max_minutes = {cap}\n")


def log_lines(env: CanopyEnv, msg: str) -> list[dict[str, object]]:
    lines = [json.loads(line) for line in (env.state_dir / "canopy.log").read_text().splitlines()]
    return [line for line in lines if line["msg"] == msg]


def waits(env: CanopyEnv) -> list[tuple[object, object]]:
    """Each wait the loop chose, as (idle count, seconds), from its log."""
    return [(line["idle_count"], line["wait_seconds"]) for line in log_lines(env, "loop waits")]


def review_run(conn: sqlite3.Connection, tick_id: int) -> int:
    """A review run whose `_review` is this process, so reconcile leaves it running."""
    run_id = db.insert_review_run(conn, tick_id=tick_id, pr_url=PR, sha="a" * 40, ticket=None, repo=None, logs_dir=LOGS)
    assert db.claim_review_run(conn, run_id, os.getpid())
    return run_id


# What makes a tick idle, on a journal written by hand.


@dataclass(frozen=True)
class Case:
    """A previous tick, written after `setup`, then a tick that ends `status`, written with `during`."""

    setup: Step | None = None
    during: Step | None = None
    status: str = "ok"
    previous_read: bool = True


def was_idle(ctx: Context, case: Case) -> bool:
    """Write `case`'s two ticks, and say whether the second was idle."""
    setup, during, status, previous_read = case.setup, case.during, case.status, case.previous_read
    conn = ctx.conn
    db.migrate(conn, resources.migrations_dir())
    previous = db.start_tick(conn, dry_run=True)
    if setup is not None:
        setup(conn, previous)
    db.set_tick_read(conn, previous)
    read_at = stamp(datetime.now(UTC) - BACK) if previous_read else None
    conn.execute("UPDATE ticks SET read_at = ? WHERE id = ?", (read_at, previous))
    db.finish_tick(conn, previous, "ok", "")
    seen = pacing.before(ctx)
    tick_id = db.start_tick(conn, dry_run=True)
    db.set_tick_read(conn, tick_id)
    db.record_decision(conn, tick_id, KEY, "wait", "checks pending")
    if during is not None:
        during(conn, tick_id)
    db.finish_tick(conn, tick_id, status, "")
    return pacing.idle(ctx, tick.Outcome(tick_id, status, ""), seen)


def decided(action: str) -> Step:
    return lambda conn, tick_id: db.record_decision(conn, tick_id, KEY, action, "because")


def listed(conn: sqlite3.Connection, tick_id: int) -> None:
    db.record_decision(conn, tick_id, KEY, "attention:needs_reviewer", PR)


def seen_ticket(conn: sqlite3.Connection, _tick_id: int) -> None:
    db.set_ticket(conn, KEY, "/r", phase="ci_running")
    db.set_unit(conn, KEY, "/r", "r", phase="ci_running", cursors={"ci": "1"}, pr_url=PR)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(Case(), id="only waits"),
        pytest.param(Case(during=decided("skip")), id="a ticket's skip"),
        pytest.param(Case(setup=listed, during=listed), id="an attention item already listed"),
        pytest.param(Case(setup=seen_ticket, during=seen_ticket), id="a ticket as it was"),
        *(pytest.param(Case(during=decided(f"refused:{g}")), id=f"refused {g}") for g in sorted(pacing.QUIET_REFUSALS)),
    ],
)
def test_a_tick_that_changed_nothing_is_idle(canopy_env: CanopyEnv, case: Case) -> None:
    assert was_idle(context(canopy_env), case)


def review_started_long_ago(conn: sqlite3.Connection, tick_id: int) -> None:
    run_id = review_run(conn, tick_id)
    conn.execute("UPDATE review_runs SET started_at = ? WHERE id = ?", (ago(hours=1), run_id))


def review_ends(conn: sqlite3.Connection, _tick_id: int) -> None:
    assert db.finish_review_run(conn, 1, "done", None)


def chore_starts(conn: sqlite3.Connection, tick_id: int) -> None:
    db.insert_chore_run(conn, tick_id=tick_id, chore="nightly", logs_dir=LOGS)


def operator_reply(conn: sqlite3.Connection, _tick_id: int) -> None:
    db.insert_message(conn, db.SUBJECT_TICKET, KEY, source="operator", kind="reply", channel="cli", body="Go ahead.")


def sets_ticket(*, phase: str | None = None, done: bool = False) -> Step:
    return lambda conn, _tick_id: db.set_ticket(conn, KEY, "/r", phase=phase, done=done)


def moves_ci_cursor(conn: sqlite3.Connection, _tick_id: int) -> None:
    db.set_unit(conn, KEY, "/r", "r", cursors={"ci": "2"})


def sets_branch(conn: sqlite3.Connection, _tick_id: int) -> None:
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-1-x' WHERE key = ?", (KEY,))


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(Case(during=decided("dispatch:implement")), id="dispatch"),
        pytest.param(Case(during=decided("done")), id="done"),
        pytest.param(Case(during=decided("mirror")), id="mirror"),
        pytest.param(Case(during=decided("refused:bad_slug")), id="other refusal"),
        pytest.param(Case(during=listed), id="attention item added"),
        pytest.param(Case(setup=listed), id="attention item resolved"),
        pytest.param(Case(during=seen_ticket), id="ticket first seen"),
        pytest.param(Case(setup=seen_ticket, during=sets_ticket(phase="ci_red")), id="phase changed"),
        pytest.param(Case(setup=seen_ticket, during=sets_branch), id="branch changed"),
        pytest.param(Case(setup=seen_ticket, during=moves_ci_cursor), id="unit cursor moved"),
        pytest.param(Case(setup=seen_ticket, during=sets_ticket(done=True)), id="done flag"),
        pytest.param(Case(during=chore_starts), id="run started"),
        pytest.param(Case(setup=review_started_long_ago, during=review_ends), id="run ended"),
        pytest.param(Case(during=operator_reply), id="operator message"),
        pytest.param(Case(status="overseer_failed"), id="not ok"),
        pytest.param(Case(previous_read=False), id="no previous read"),
    ],
)
def test_each_change_makes_a_tick_not_idle(canopy_env: CanopyEnv, case: Case) -> None:
    assert not was_idle(context(canopy_env), case)


def test_a_run_that_ended_before_the_previous_tick_read_does_not_count(canopy_env: CanopyEnv) -> None:
    def setup(conn: sqlite3.Connection, tick_id: int) -> None:
        run_id = review_run(conn, tick_id)
        assert db.finish_review_run(conn, run_id, "done", None)
        conn.execute("UPDATE review_runs SET started_at = ?, ended_at = ?", (ago(hours=1), ago(minutes=30)))

    assert was_idle(context(canopy_env), Case(setup=setup))


# The wait after a tick.


def test_the_wait_doubles_from_base_to_the_cap_and_never_below_base() -> None:
    pace = pacing.Pace(base_seconds=900, cap_seconds=7200)
    assert pace.on
    assert [pace.after(n) for n in range(6)] == [900, 1800, 3600, 7200, 7200, 7200]
    # A cap that is not a doubling of base is reached exactly.
    assert [pacing.Pace(600, 1500).after(n) for n in range(4)] == [600, 1200, 1500, 1500]
    for off in (pacing.Pace(900, 900), pacing.Pace(1800, 900)):
        assert not off.on
        assert [off.after(n) for n in range(4)] == [off.base_seconds] * 4


def fix_ci_ended(conn: sqlite3.Connection, ended: datetime) -> None:
    tick_id = db.start_tick(conn, dry_run=False)
    db.touch_ticket(conn, KEY, "/r")
    conn.execute(
        "INSERT INTO runs (id, tick_id, ticket_key, kind, branch, started_at, ended_at, status, log_path) "
        "VALUES (1, ?, ?, 'fix-ci', 'agent/PROJ-1-x', ?, ?, 'done', 'l')",
        (tick_id, KEY, stamp(ended - timedelta(minutes=5)), stamp(ended)),
    )
    conn.execute(
        "INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder) VALUES (1, NULL, '/s', 'l', 'h')"
    )


def chore_started(conn: sqlite3.Connection, started: datetime) -> None:
    tick_id = db.start_tick(conn, dry_run=False)
    run_id = db.insert_chore_run(conn, tick_id=tick_id, chore="build-health", logs_dir=LOGS)
    assert db.finish_chore_run(conn, run_id, "ok", None)
    conn.execute("UPDATE chore_runs SET started_at = ? WHERE id = ?", (stamp(started), run_id))


@pytest.mark.parametrize(
    ("gate", "minutes_ago", "expected"),
    [
        pytest.param(None, 0, 3600, id="no gate"),
        # The cooldown is 30 minutes by default: a fix that ended 20 minutes ago opens in 10.
        pytest.param(fix_ci_ended, 20, 600, id="cooldown ahead"),
        pytest.param(fix_ci_ended, 40, 3600, id="cooldown past"),
        # The chore runs every 120 minutes: one that started 115 minutes ago is due in 5.
        pytest.param(chore_started, 115, 300, id="chore due ahead"),
        pytest.param(chore_started, 125, 3600, id="chore due past"),
        # A gate further off than the wait does not lengthen it.
        pytest.param(chore_started, 10, 3600, id="chore due later"),
    ],
)
def test_a_gate_still_ahead_ends_the_wait_and_one_already_open_does_not(
    canopy_env: CanopyEnv,
    gate: Callable[[sqlite3.Connection, datetime], None] | None,
    minutes_ago: int,
    expected: float,
) -> None:
    (canopy_env.home / "chores").mkdir()
    (canopy_env.home / "chores" / "build-health.md").write_text("# Build health\n")
    canopy_env.write_user(canopy_env.user_file.read_text() + chore_toml())
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    now = datetime.now(UTC)
    if gate is not None:
        gate(ctx.conn, now - timedelta(minutes=minutes_ago))
    pace = pacing.Pace(base_seconds=900, cap_seconds=7200)
    assert pacing.wait(ctx, pace, 2, now) == pytest.approx(expected, abs=0.01)
    # With idle pacing off, no gate shortens the wait: today's pacing.
    assert pacing.wait(ctx, pacing.Pace(900, 900), 2, now) == 900


# The loop.


def test_idle_ticks_lengthen_the_wait_to_the_cap_and_a_change_resets_it(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop_config(canopy_env, interval=1, cap=4)
    overseer_does(monkeypatch, canopy("decide", KEY, "wait", "--rationale", "checks pending"))
    time = FakeTime()

    def at_each_wait() -> None:
        # The fourth tick finds something new: a reviewer asked for changes.
        if time.now == sum((60, 120, 240)):
            overseer_does(monkeypatch, canopy("attention", KEY, "needs_reviewer", "--detail", PR))

    time.on_sleep = at_each_wait
    term, out = console()

    statuses = repeat.run(
        context(canopy_env),
        dry_run=True,
        interval_minutes=1,
        max_ticks=6,
        console=term,
        stop=repeat.Stop(),
        sleep=time.sleep,
        clock=time.clock,
    )

    assert statuses == {"ok": 6}
    # The first tick saw PROJ-1 for the first time, the next two found nothing, the fourth raised an item, and the
    # fifth found nothing again: idle counts restart from it.
    assert waits(canopy_env) == [(0, 60), (1, 120), (2, 240), (0, 60), (1, 120)]
    assert sum(time.slept) == sum((60, 120, 240, 60, 120))
    text = out.getvalue()
    assert "wait 1 minute after each tick ends, up to 4 minutes when idle" in text
    assert "idle 2, next tick in 4m 00s at" in text
    assert "attention 0  ·  next tick in 1m 00s at" in text
    [started] = log_lines(canopy_env, "loop started")
    assert started["idle_max_minutes"] == 4
    assert [line["idle"] for line in log_lines(canopy_env, "loop waits")] == [False, True, True, False, True]


def test_the_cap_stays_the_cap_however_long_nothing_changes(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop_config(canopy_env, interval=1, cap=3)
    overseer_does(monkeypatch)
    time = FakeTime()
    term, _ = console()
    repeat.run(
        context(canopy_env),
        dry_run=True,
        interval_minutes=1,
        max_ticks=5,
        console=term,
        stop=repeat.Stop(),
        sleep=time.sleep,
        clock=time.clock,
    )
    assert waits(canopy_env) == [(0, 60), (1, 120), (2, 180), (3, 180)]


@pytest.mark.parametrize(("interval", "cap", "every"), [(1, 1, None), (1, 4, 4), (1, 4, 5)])
def test_a_cap_not_above_base_keeps_todays_pacing(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    interval: int,
    cap: int,
    every: int | None,
) -> None:
    loop_config(canopy_env, interval=interval, cap=cap)
    overseer_does(monkeypatch)
    base = (every or interval) * 60
    time = FakeTime()
    term, out = console()
    repeat.run(
        context(canopy_env),
        dry_run=True,
        interval_minutes=every or interval,
        max_ticks=4,
        console=term,
        stop=repeat.Stop(),
        sleep=time.sleep,
        clock=time.clock,
    )
    assert waits(canopy_env) == [(0, base)] * 3
    assert sum(time.slept) == 3 * base
    assert "when idle" not in out.getvalue()
    assert "idle " not in out.getvalue()


def test_the_cli_paces_from_every_with_the_configured_cap(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    overseer_does(monkeypatch)
    assert main(["loop", "--dry-run", "--ticks", "1", "--every", "3"]) == 0
    assert "wait 3 minutes after each tick ends, up to 120 minutes when idle" in capsys.readouterr().out


def finishes_review(db_path: Path) -> list[str]:
    """A command, for the fake overseer to run, that ends review run 1 the way its `_review` would."""
    sql = "UPDATE review_runs SET status = 'done', ended_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = 1"
    return [
        sys.executable,
        "-c",
        f"import sqlite3; sqlite3.connect({str(db_path)!r}, autocommit=True).execute({sql!r})",
    ]


@pytest.mark.parametrize("when", ["during the tick", "during the wait", "an operator message", "before the tick"])
def test_a_run_ending_after_the_tick_read_the_journal_wakes_the_wait(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    first = db.start_tick(ctx.conn, dry_run=True)
    db.finish_tick(ctx.conn, first, "ok", "")
    db.touch_ticket(ctx.conn, KEY, "/r")
    run_id = review_run(ctx.conn, first)
    if when == "before the tick":
        assert db.finish_review_run(ctx.conn, run_id, "done", None)
    commands = [finishes_review(canopy_env.state_dir / db.DB_FILE_NAME)] if when == "during the tick" else []
    overseer_does(monkeypatch, *commands)
    time = FakeTime()

    def at_each_wait() -> None:
        if len(time.slept) != 1:
            return
        if when == "during the wait":
            assert db.finish_review_run(ctx.conn, run_id, "done", None)
        elif when == "an operator message":
            assert main(["reply", KEY, "Go ahead."]) == 0

    time.on_sleep = at_each_wait
    term, out = console()

    repeat.run(
        ctx,
        dry_run=True,
        interval_minutes=15,
        max_ticks=2,
        console=term,
        stop=repeat.Stop(),
        sleep=time.sleep,
        clock=time.clock,
    )

    if when == "before the tick":
        # The tick could see that run end: nothing for the wait to wake for.
        assert sum(time.slept) == 900
        assert not log_lines(canopy_env, "a run ending ended the wait")
        return
    # Woken at once, but no sooner than a minute after the tick began, not fifteen.
    assert sum(time.slept) == pytest.approx(repeat.WAKE_MIN_SECONDS)
    message = "an operator message ended the wait" if when == "an operator message" else "a run ending ended the wait"
    assert len(log_lines(canopy_env, message)) == 1
    assert "next tick in 15m 00s at" in out.getvalue()


def test_with_idle_pacing_off_a_run_ending_does_not_wake_the_wait(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop_config(canopy_env, interval=15, cap=15)
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    first = db.start_tick(ctx.conn, dry_run=True)
    db.finish_tick(ctx.conn, first, "ok", "")
    run_id = review_run(ctx.conn, first)
    overseer_does(monkeypatch)

    def run_ends() -> None:
        db.finish_review_run(ctx.conn, run_id, "done", None)

    time = FakeTime(on_sleep=run_ends)
    term, _ = console()
    repeat.run(
        ctx,
        dry_run=True,
        interval_minutes=15,
        max_ticks=2,
        console=term,
        stop=repeat.Stop(),
        sleep=time.sleep,
        clock=time.clock,
    )
    assert sum(time.slept) == 900
