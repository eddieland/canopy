"""Idle pacing (DESIGN §6, ROADMAP M21): longer waits after idle ticks in a row, gates, and early wakes.

What makes a tick idle is checked on a journal written by hand, with no overseer; the waits the loop chooses, against
the fake overseer on a fake clock, as `test_loop.py` does.
"""

import contextlib
import json
import os
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import chore_runs, db, notice, review_runs
from canopy.core.context import Context
from canopy.core.vocab import ChoreRunStatus, Phase, ReviewRunStatus, StartStatus, TickStatus
from canopy.infra import resources
from canopy.loop import pacing, repeat, tick, tick_now
from tests.canopy.helpers import (
    KEY,
    FakeKeys,
    FakeTime,
    canopy,
    chore_toml,
    console,
    context,
    overseer_does,
    overseer_titles,
    titled_overseer,
)
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import CanopyEnv

PR = "https://example.test/pr/1"
#: What the overseer passes to dispatch KEY: a dry run records it without starting a run.
DISPATCH = ("--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement")
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
    env.append_user(f"\n[loop]\ninterval_minutes = {interval}\nidle_max_minutes = {cap}\n")


def log_lines(env: CanopyEnv, msg: str) -> list[dict[str, object]]:
    lines = [json.loads(line) for line in (env.state_dir / "canopy.log").read_text().splitlines()]
    return [line for line in lines if line["msg"] == msg]


def waits(env: CanopyEnv) -> list[tuple[object, object]]:
    """Each wait the loop chose, as (idle count, seconds), from its log."""
    return [(line["idle_count"], line["wait_seconds"]) for line in log_lines(env, "loop waits")]


def recorded(env: CanopyEnv) -> list[tuple[object, object]]:
    """Each tick's row: whether the loop found it idle, and what ended the wait before it."""
    conn = env.journal(migrate=False)
    return [(r["idle"], r["woken_by"]) for r in conn.execute("SELECT idle, woken_by FROM ticks ORDER BY id")]


def review_run(conn: sqlite3.Connection, tick_id: int) -> int:
    """A review run whose `_review` is this process, so reconcile leaves it running."""
    run_id = review_runs.insert_review_run(
        conn,
        tick_id=tick_id,
        pr_url=PR,
        sha="a" * 40,
        ticket=None,
        repo=None,
        purpose="query",
        logs_dir=LOGS,
    )
    assert db.claim_run(conn, "review_runs", run_id, os.getpid())
    return run_id


# What makes a tick idle, on a journal written by hand.


@dataclass(frozen=True)
class Case:
    """A previous tick, written after `setup`, then a tick that ends `status`, written with `during`."""

    setup: Step | None = None
    during: Step | None = None
    status: TickStatus = TickStatus.OK
    previous_read: bool = True


def was_idle(ctx: Context, case: Case) -> bool:
    """Write `case`'s two ticks, and say whether the second was idle."""
    outcome, _seen = two_ticks(ctx, case)
    return pacing.idle(ctx, outcome)


def churn_of(ctx: Context, case: Case) -> list[str]:
    """Write `case`'s two ticks, and say what the second changed with nothing new to see."""
    outcome, seen = two_ticks(ctx, case)
    return pacing.churn(ctx, outcome, seen)


def two_ticks(ctx: Context, case: Case) -> tuple[tick.Outcome, pacing.Before]:
    """Write `case`'s two ticks.

    Returns:
        How the second ended, and what the loop read before it.
    """
    setup, during, status, previous_read = case.setup, case.during, case.status, case.previous_read
    conn = ctx.conn
    db.migrate(conn, resources.migrations_dir())
    previous = db.start_tick(conn, dry_run=True)
    if setup is not None:
        setup(conn, previous)
    db.set_tick_read(conn, previous)
    read_at = stamp(datetime.now(UTC) - BACK) if previous_read else None
    conn.execute("UPDATE ticks SET read_at = ? WHERE id = ?", (read_at, previous))
    db.finish_tick(conn, previous, TickStatus.OK, "")
    seen = pacing.before(ctx)
    tick_id = db.start_tick(conn, dry_run=True)
    db.set_tick_read(conn, tick_id)
    db.record_decision(conn, tick_id, KEY, "wait", "checks pending")
    if during is not None:
        during(conn, tick_id)
    db.finish_tick(conn, tick_id, status, "")
    return tick.Outcome(tick_id, status, ""), seen


def decided(action: str) -> Step:
    return lambda conn, tick_id: db.record_decision(conn, tick_id, KEY, action, "because")


def listed(conn: sqlite3.Connection, tick_id: int) -> None:
    db.record_decision(conn, tick_id, KEY, "attention:needs_reviewer", PR)


def seen_ticket(conn: sqlite3.Connection, _tick_id: int) -> None:
    db.set_ticket(conn, KEY, "/r", phase=Phase.CI_RUNNING)
    db.set_unit(conn, KEY, "/r", "r", phase="ci_running", cursors={"ci": "1"}, pr_url=PR)


def sets_ticket(*, phase: Phase | None = None, done: bool = False) -> Step:
    return lambda conn, _tick_id: db.set_ticket(conn, KEY, "/r", phase=phase, done=done)


def moves_ci_cursor(conn: sqlite3.Connection, _tick_id: int) -> None:
    db.set_unit(conn, KEY, "/r", "r", cursors={"ci": "2"})


def sets_branch(conn: sqlite3.Connection, _tick_id: int) -> None:
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-1-x' WHERE key = ?", (KEY,))


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(Case(), id="only waits"),
        pytest.param(Case(during=decided("skip")), id="a ticket's skip"),
        pytest.param(Case(setup=listed, during=listed), id="an attention item already listed"),
        pytest.param(Case(setup=seen_ticket, during=seen_ticket), id="a ticket as it was"),
        pytest.param(Case(during=decided("refused:running")), id="a refusal that lifts by itself"),
        pytest.param(Case(during=decided("refused:review_limit")), id="a refusal that never lifts"),
        pytest.param(Case(during=decided("refused:bad_slug")), id="a refusal of a bad request"),
        pytest.param(Case(during=decided("done")), id="done"),
        pytest.param(Case(during=decided("mirror")), id="mirror"),
        pytest.param(Case(during=listed), id="attention item added"),
        pytest.param(Case(setup=listed), id="attention item resolved"),
        pytest.param(Case(during=seen_ticket), id="ticket first seen"),
        pytest.param(Case(setup=seen_ticket, during=sets_ticket(phase=Phase.CI_RED)), id="phase changed"),
        pytest.param(Case(setup=seen_ticket, during=sets_branch), id="branch changed"),
        pytest.param(Case(setup=seen_ticket, during=moves_ci_cursor), id="unit cursor moved"),
        pytest.param(Case(setup=seen_ticket, during=sets_ticket(done=True)), id="done flag"),
    ],
)
def test_a_tick_that_dispatched_nothing_is_idle(canopy_env: CanopyEnv, case: Case) -> None:
    assert was_idle(context(canopy_env), case)


def review_started_long_ago(conn: sqlite3.Connection, tick_id: int) -> None:
    run_id = review_run(conn, tick_id)
    conn.execute("UPDATE review_runs SET started_at = ? WHERE id = ?", (ago(hours=1), run_id))


def review_ends(conn: sqlite3.Connection, _tick_id: int) -> None:
    assert db.finish_run(conn, "review_runs", 1, ReviewRunStatus.DONE, None)


def chore_starts(conn: sqlite3.Connection, tick_id: int) -> None:
    chore_runs.insert_chore_run(conn, tick_id=tick_id, chore="nightly", logs_dir=LOGS)


def operator_reply(conn: sqlite3.Connection, _tick_id: int) -> None:
    db.insert_message(conn, db.SUBJECT_TICKET, KEY, source="operator", kind="reply", channel="cli", body="Go ahead.")


def ticket_started(conn: sqlite3.Connection, _tick_id: int) -> None:
    db.set_start(conn, db.SUBJECT_TICKET, KEY, status=StartStatus.STARTED, channel="web")


def ticket_stopped(conn: sqlite3.Connection, _tick_id: int) -> None:
    db.set_start(conn, db.SUBJECT_TICKET, KEY, status=StartStatus.STOPPED, channel="cli")


def started_long_ago(conn: sqlite3.Connection, tick_id: int) -> None:
    ticket_started(conn, tick_id)
    conn.execute("UPDATE starts SET started_at = ?", (ago(hours=1),))


def attempts_granted(conn: sqlite3.Connection, _tick_id: int) -> None:
    db.touch_ticket(conn, KEY, "/r")
    conn.execute(
        "INSERT INTO attempt_grants (ticket_key, repo, kind, runs, granted_at) VALUES (?, 'r', 'fix-ci', 1, ?)",
        (KEY, db.now()),
    )


def reviews_granted(conn: sqlite3.Connection, _tick_id: int) -> None:
    conn.execute("INSERT INTO review_grants (pr_url, runs, granted_at) VALUES (?, 1, ?)", (PR, db.now()))


def notice_set(conn: sqlite3.Connection, _tick_id: int) -> None:
    notice.set_notice(conn, "Artifactory is down.", minutes=60, channel="cli")


def notice_set_long_ago(conn: sqlite3.Connection, tick_id: int) -> None:
    notice_set(conn, tick_id)
    conn.execute("UPDATE notices SET set_at = ?", (ago(hours=1),))


def notice_cleared(conn: sqlite3.Connection, _tick_id: int) -> None:
    assert notice.clear(conn, channel="web") is not None


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(Case(during=decided("dispatch:implement")), id="dispatch"),
        pytest.param(Case(during=decided("dispatch:review")), id="review dispatched"),
        pytest.param(Case(during=decided("dispatch:chore")), id="chore dispatched"),
        pytest.param(Case(during=chore_starts), id="run started"),
        pytest.param(Case(setup=review_started_long_ago, during=review_ends), id="run ended"),
        pytest.param(Case(during=operator_reply), id="operator message"),
        pytest.param(Case(during=ticket_started), id="ticket started"),
        pytest.param(Case(setup=started_long_ago, during=ticket_stopped), id="ticket stopped"),
        pytest.param(Case(during=attempts_granted), id="attempts granted"),
        pytest.param(Case(during=reviews_granted), id="reviews granted"),
        pytest.param(Case(during=notice_set), id="notice set"),
        pytest.param(Case(setup=notice_set_long_ago, during=notice_cleared), id="notice cleared"),
        pytest.param(Case(status=TickStatus.OVERSEER_FAILED), id="not ok"),
        pytest.param(Case(previous_read=False), id="no previous read"),
    ],
)
def test_a_dispatch_or_anything_new_makes_a_tick_not_idle(canopy_env: CanopyEnv, case: Case) -> None:
    assert not was_idle(context(canopy_env), case)


def test_a_run_that_ended_before_the_previous_tick_read_does_not_count(canopy_env: CanopyEnv) -> None:
    def setup(conn: sqlite3.Connection, tick_id: int) -> None:
        run_id = review_run(conn, tick_id)
        assert db.finish_run(conn, "review_runs", run_id, ReviewRunStatus.DONE, None)
        conn.execute("UPDATE review_runs SET started_at = ?, ended_at = ?", (ago(hours=1), ago(minutes=30)))

    assert was_idle(context(canopy_env), Case(setup=setup))


# Churn: what a tick changed with nothing new to see (ROADMAP M28), measured on the same journals.


def both(*steps: Step) -> Step:
    def run(conn: sqlite3.Connection, tick_id: int) -> None:
        for step in steps:
            step(conn, tick_id)

    return run


RELABELLED = both(seen_ticket, sets_ticket(phase=Phase.CI_RED))


@pytest.mark.parametrize(
    ("case", "lines"),
    [
        pytest.param(Case(setup=seen_ticket, during=RELABELLED), ["PROJ-1 phase ci_running -> ci_red"], id="phase"),
        pytest.param(
            Case(
                setup=seen_ticket,
                during=both(seen_ticket, lambda c, _t: db.set_unit(c, KEY, "/r", "r", phase="ci_red")),
            ),
            ["PROJ-1 (r) phase ci_running -> ci_red"],
            id="a unit's phase",
        ),
        pytest.param(Case(during=listed), ["+PROJ-1 needs_reviewer"], id="item added"),
        pytest.param(Case(setup=listed), ["-PROJ-1 needs_reviewer"], id="item dropped"),
        pytest.param(Case(setup=seen_ticket, during=seen_ticket), [], id="nothing changed"),
        pytest.param(Case(during=seen_ticket), [], id="a ticket first seen"),
        pytest.param(Case(setup=seen_ticket, during=both(RELABELLED, chore_starts)), [], id="a run started"),
        pytest.param(
            Case(setup=both(seen_ticket, review_started_long_ago), during=both(RELABELLED, review_ends)),
            [],
            id="a run ended",
        ),
        pytest.param(Case(setup=seen_ticket, during=both(RELABELLED, operator_reply)), [], id="an operator message"),
        pytest.param(Case(setup=seen_ticket, during=both(RELABELLED, ticket_started)), [], id="a start"),
        pytest.param(Case(setup=seen_ticket, during=both(RELABELLED, attempts_granted)), [], id="a grant"),
        pytest.param(Case(setup=seen_ticket, during=RELABELLED, status=TickStatus.OVERSEER_FAILED), [], id="not ok"),
        pytest.param(Case(setup=seen_ticket, during=RELABELLED, previous_read=False), [], id="no previous read"),
    ],
)
def test_churn_is_a_change_with_nothing_new_to_see(canopy_env: CanopyEnv, case: Case, lines: list[str]) -> None:
    assert churn_of(context(canopy_env), case) == lines


def test_a_gate_that_opened_since_the_previous_tick_is_something_new(canopy_env: CanopyEnv) -> None:
    # A gate (a fix-ci cooldown's end, a chore's due time) half way between the two ticks' reads.
    def gate(_ctx: Context, now: datetime) -> datetime:
        return now + BACK / 2

    with mock.patch.object(pacing, "gate", autospec=True, side_effect=gate):
        assert churn_of(context(canopy_env), Case(setup=seen_ticket, during=RELABELLED)) == []


def test_the_loop_waits_line_says_what_a_tick_churned(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    ctx = context(canopy_env)
    time = FakeTime()
    term, _ = console()
    with contextlib.ExitStack() as stack:
        wait = canopy("decide", KEY, "wait", "--rationale", "checks pending")
        label = canopy("ticket", "set", KEY, "--repo", "repo", "--phase", "ci_running")
        stack.enter_context(overseer_does(label, wait))

        def relabel_at_the_first_wait() -> None:
            if len(time.slept) == 1:
                relabel = canopy("ticket", "set", KEY, "--repo", "repo", "--phase", "ci_red")
                stack.enter_context(overseer_does(relabel, wait))

        time.on_sleep = relabel_at_the_first_wait
        repeat.run(
            ctx,
            dry_run=True,
            interval_minutes=15,
            max_ticks=3,
            console=term,
            stop=repeat.Stop(),
            sleep=time.sleep,
            clock=time.clock,
        )

    # The first tick sees the ticket first; the second relabels it with nothing new to see; the third leaves it.
    assert [line["churn"] for line in log_lines(canopy_env, "loop waits")] == [
        [],
        [f"{KEY} (repo) phase ci_running -> ci_red"],
    ]


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
        "INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder) VALUES (1, NULL, '/s', 'l', 'h')",
    )


def chore_started(conn: sqlite3.Connection, started: datetime) -> None:
    tick_id = db.start_tick(conn, dry_run=False)
    run_id = chore_runs.insert_chore_run(conn, tick_id=tick_id, chore="build-health", logs_dir=LOGS)
    assert db.finish_run(conn, "chore_runs", run_id, ChoreRunStatus.OK, None)
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
    canopy_env.append_user(chore_toml())
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
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    loop_config(canopy_env, interval=1, cap=4)
    with (
        overseer_does(canopy("decide", KEY, "wait", "--rationale", "checks pending")),
        contextlib.ExitStack() as later,
    ):
        time = FakeTime()

        def at_each_wait() -> None:
            # The fourth tick finds work to start, and the fifth finds none again.
            if time.now == sum((60, 120, 240)):
                later.enter_context(overseer_does(canopy("dispatch", KEY, *DISPATCH)))
            elif time.now == sum((60, 120, 240, 60)):
                later.close()

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
        # The first tick had no tick before it, the next two dispatched nothing, the fourth dispatched, and the fifth
        # dispatched nothing again: idle counts restart from it.
        assert waits(canopy_env) == [(0, 60), (1, 120), (2, 240), (0, 60), (1, 120)]
        assert sum(time.slept) == sum((60, 120, 240, 60, 120))
        text = out.getvalue()
        assert "wait 1 minute after each tick ends, up to 4 minutes when idle" in text
        assert "idle 2, next tick in 4m at" in text
        assert "attention 0  ·  next tick in 1m at" in text
        [started] = log_lines(canopy_env, "loop started")
        assert started["idle_max_minutes"] == 4
        assert [line["idle"] for line in log_lines(canopy_env, "loop waits")] == [False, True, True, False, True]
        # The journal records the same, the last tick's included, for spend on idle ticks.
        assert recorded(canopy_env) == [
            (0, "start"),
            (1, "timer"),
            (1, "timer"),
            (0, "timer"),
            (1, "timer"),
            (1, "timer"),
        ]


def test_the_cap_stays_the_cap_however_long_nothing_changes(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    loop_config(canopy_env, interval=1, cap=3)
    with overseer_does():
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
    interval: int,
    cap: int,
    every: int | None,
) -> None:
    loop_config(canopy_env, interval=interval, cap=cap)
    with overseer_does():
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
        # Pacing does not count them, but the journal still says which ticks were idle.
        assert recorded(canopy_env) == [(0, "start"), (1, "timer"), (1, "timer"), (1, "timer")]


def test_the_cli_paces_from_every_with_the_configured_cap(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with overseer_does():
        assert main(["loop", "--dry-run", "--ticks", "1", "--every", "3"]) == 0
        assert " every_minutes=3 idle_max_minutes=120 " in capsys.readouterr().out


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
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    when: str,
) -> None:
    titled_overseer(canopy_env)
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    first = db.start_tick(ctx.conn, dry_run=True)
    db.finish_tick(ctx.conn, first, TickStatus.OK, "")
    db.touch_ticket(ctx.conn, KEY, "/r")
    run_id = review_run(ctx.conn, first)
    if when == "before the tick":
        assert db.finish_run(ctx.conn, "review_runs", run_id, ReviewRunStatus.DONE, None)
    commands = [finishes_review(canopy_env.state_dir / db.DB_FILE_NAME)] if when == "during the tick" else []
    with overseer_does(*commands):
        time = FakeTime()

        def at_each_wait() -> None:
            if len(time.slept) != 1:
                return
            if when == "during the wait":
                assert db.finish_run(ctx.conn, "review_runs", run_id, ReviewRunStatus.DONE, None)
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

        # The hand-made tick, the loop's first, then the tick the wait ended in.
        woken_by = {"an operator message": "message", "before the tick": "timer"}.get(when, "run")
        assert [w for _, w in recorded(canopy_env)] == [None, "start", woken_by]
        # The overseer's session title says so too (DESIGN §13).
        woke = {"message": "message", "timer": "timer", "run": "run ended"}[woken_by]
        assert overseer_titles(agent_log) == ["tick 2 · loop start · 1 ticket", f"tick 3 · {woke} · 1 ticket"]
        if when == "before the tick":
            # The tick could see that run end: nothing for the wait to wake for.
            assert sum(time.slept) == 900
            assert not log_lines(canopy_env, "a run ending ended the wait")
            return
        # Woken at once, but no sooner than a minute after the tick ended, not fifteen.
        assert sum(time.slept) == pytest.approx(60)  # loop.min_gap_minutes, by default
        message = (
            "an operator message ended the wait" if when == "an operator message" else "a run ending ended the wait"
        )
        assert len(log_lines(canopy_env, message)) == 1
        assert "next tick in 15m at" in out.getvalue()


@pytest.mark.parametrize(
    ("act", "woken", "message"),
    [
        ("start", "starts", "a ticket started or stopped ended the wait"),
        ("stop", "starts", "a ticket started or stopped ended the wait"),
        ("grant attempts", "grant", "a grant ended the wait"),
        ("grant reviews", "grant", "a grant ended the wait"),
        ("set a notice", "notice", "a notice to workers set or cleared ended the wait"),
        ("clear a notice", "notice", "a notice to workers set or cleared ended the wait"),
    ],
)
@pytest.mark.parametrize("pacing_on", [True, False], ids=["pacing on", "pacing off"])
def test_the_operators_acts_end_the_wait(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    act: str,
    woken: str,
    message: str,
    pacing_on: bool,  # noqa: FBT001
) -> None:
    loop_config(canopy_env, interval=15, cap=120 if pacing_on else 15)
    ctx = context(canopy_env)
    if act == "stop":
        assert main(["start", KEY]) == 0  # before the loop: its first tick sees it
    elif act == "clear a notice":
        assert main(["notice", "CI is down."]) == 0
    time = FakeTime()

    def at_first_wait() -> None:
        if len(time.slept) != 1:
            return
        if act in {"start", "stop"}:
            assert main([act, KEY]) == 0
        elif act == "grant attempts":
            attempts_granted(ctx.conn, 0)
        elif act == "set a notice":
            assert main(["notice", "CI is down."]) == 0
        elif act == "clear a notice":
            assert main(["notice", "--clear"]) == 0
        else:
            reviews_granted(ctx.conn, 0)

    time.on_sleep = at_first_wait
    term, out = console()
    with overseer_does():
        repeat.run(
            ctx,
            dry_run=True,
            interval_minutes=None,
            max_ticks=2,
            console=term,
            stop=repeat.Stop(),
            sleep=time.sleep,
            clock=time.clock,
        )

    # Woken at once, but no sooner than a minute after the tick ended, whatever the pacing; and the tick it woke is
    # not idle.
    assert sum(time.slept) == pytest.approx(60)  # loop.min_gap_minutes, by default
    assert recorded(canopy_env) == [(0, "start"), (0, woken)]
    assert len(log_lines(canopy_env, message)) == 1
    assert "next tick in 15m at" in out.getvalue()


def test_with_idle_pacing_off_a_run_ending_does_not_wake_the_wait(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    loop_config(canopy_env, interval=15, cap=15)
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    first = db.start_tick(ctx.conn, dry_run=True)
    db.finish_tick(ctx.conn, first, TickStatus.OK, "")
    run_id = review_run(ctx.conn, first)
    with overseer_does():

        def run_ends() -> None:
            db.finish_run(ctx.conn, "review_runs", run_id, ReviewRunStatus.DONE, None)

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


def test_a_tick_after_a_wait_a_gate_shortened_records_the_gate(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    (canopy_env.home / "chores").mkdir()
    (canopy_env.home / "chores" / "build-health.md").write_text("# Build health\n")
    canopy_env.append_user(chore_toml())
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    # The chore runs every 120 minutes: one that started 115 minutes ago is due in 5, before the 15-minute interval.
    chore_started(ctx.conn, datetime.now(UTC) - timedelta(minutes=115))
    with overseer_does():
        time = FakeTime()
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
        assert sum(time.slept) == pytest.approx(300, abs=5)
        # The hand-made tick that ran the chore, the loop's first, then the one the gate started.
        assert [w for _, w in recorded(canopy_env)] == [None, "start", "gate"]


def loop_ticks(
    ctx: Context,
    time: FakeTime,
    *,
    interval_minutes: int | None = 15,
    asked: tick_now.TickNow | None = None,
) -> None:
    """Two ticks of the loop on `time`, against the fakes, with `asked` for the web UI's Tick now."""
    term, _ = console()
    repeat.run(
        ctx,
        dry_run=True,
        interval_minutes=interval_minutes,
        max_ticks=2,
        console=term,
        stop=repeat.Stop(),
        asked=asked,
        sleep=time.sleep,
        clock=time.clock,
    )


def test_a_gate_opening_just_after_a_tick_waits_for_the_gap(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    (canopy_env.home / "chores").mkdir()
    (canopy_env.home / "chores" / "build-health.md").write_text("# Build health\n")
    canopy_env.append_user(chore_toml())
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    # Due 20 seconds after the tick: the gap holds the next tick to a minute after this one ended.
    chore_started(ctx.conn, datetime.now(UTC) - timedelta(minutes=120, seconds=-20))
    with overseer_does():
        time = FakeTime()
        loop_ticks(ctx, time)
    assert sum(time.slept) == pytest.approx(60)
    assert [w for _, w in recorded(canopy_env)] == [None, "start", "gate"]
    assert [seconds for _, seconds in waits(canopy_env)] == [60]


def test_a_configured_gap_holds_an_early_wake(canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path) -> None:
    canopy_env.append_user("\n[loop]\nmin_gap_minutes = 5\n")
    ctx = context(canopy_env)
    time = FakeTime()

    def reply_once() -> None:
        if len(time.slept) == 1:
            assert main(["reply", KEY, "Go ahead."]) == 0

    time.on_sleep = reply_once
    db.migrate(ctx.conn, resources.migrations_dir())
    db.touch_ticket(ctx.conn, KEY, "/r")
    with overseer_does():
        loop_ticks(ctx, time)
    assert sum(time.slept) == pytest.approx(300)
    assert [w for _, w in recorded(canopy_env)] == ["start", "message"]


def test_the_gap_runs_from_the_end_of_a_long_tick(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    canopy_env.append_user("\n[loop]\nmin_gap_minutes = 2\n")
    ctx = context(canopy_env)
    time = FakeTime()
    run = tick.run

    def runs_ninety_seconds(
        tick_ctx: Context,
        *,
        dry_run: bool,
        woken_by: tick.WokenBy | None = None,
        ui: str | None = None,
    ) -> tick.Outcome:
        time.now += 90
        return run(tick_ctx, dry_run=dry_run, woken_by=woken_by, ui=ui)

    def reply_once() -> None:
        if len(time.slept) == 1:
            assert main(["reply", KEY, "Go ahead."]) == 0

    time.on_sleep = reply_once
    db.migrate(ctx.conn, resources.migrations_dir())
    db.touch_ticket(ctx.conn, KEY, "/r")
    with overseer_does(), mock.patch.object(tick, "run", autospec=True, side_effect=runs_ninety_seconds):
        loop_ticks(ctx, time)
    # Two minutes from the first tick's end, not 30 seconds: the gap is quiet time between ticks.
    assert sum(time.slept) == pytest.approx(120)
    assert [w for _, w in recorded(canopy_env)] == ["start", "message"]


def test_a_gap_longer_than_the_interval_lengthens_the_wait(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    canopy_env.append_user("\n[loop]\nmin_gap_minutes = 3\n")
    ctx = context(canopy_env)
    with overseer_does():
        time = FakeTime()
        loop_ticks(ctx, time, interval_minutes=1)
    assert sum(time.slept) == pytest.approx(180)
    assert [w for _, w in recorded(canopy_env)] == ["start", "timer"]


def test_the_tick_now_key_is_not_held_by_the_gap(canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path) -> None:
    canopy_env.append_user("\n[loop]\nmin_gap_minutes = 5\n")
    ctx = context(canopy_env)
    keys = FakeKeys()
    time = FakeTime(on_sleep=lambda: keys.type(repeat.TICK_NOW_KEY))
    term, _ = console()
    with overseer_does():
        repeat.run(
            ctx,
            dry_run=True,
            interval_minutes=15,
            max_ticks=2,
            console=term,
            stop=repeat.Stop(),
            keys=keys.pressed,
            sleep=time.sleep,
            clock=time.clock,
        )
    assert time.slept == [0.5]
    assert [w for _, w in recorded(canopy_env)] == ["start", "key"]


def test_a_tick_asked_for_from_the_web_is_not_held_by_the_gap(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    canopy_env.append_user("\n[loop]\nmin_gap_minutes = 5\n")
    ctx = context(canopy_env)
    asked = tick_now.TickNow()
    time = FakeTime(on_sleep=asked.request)
    with overseer_does():
        loop_ticks(ctx, time, asked=asked)
    assert time.slept == [0.5]
    assert [w for _, w in recorded(canopy_env)] == ["start", "web"]


def test_a_tick_asked_for_during_a_tick_ends_the_wait_after_it(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    ctx = context(canopy_env)
    asked = tick_now.TickNow()
    time = FakeTime()
    run = tick.run

    def asked_during(
        tick_ctx: Context,
        *,
        dry_run: bool,
        woken_by: tick.WokenBy | None = None,
        ui: str | None = None,
    ) -> tick.Outcome:
        asked.request()
        return run(tick_ctx, dry_run=dry_run, woken_by=woken_by, ui=ui)

    with overseer_does(), mock.patch.object(tick, "run", autospec=True, side_effect=asked_during):
        loop_ticks(ctx, time, asked=asked)
    assert time.slept == []
    assert [w for _, w in recorded(canopy_env)] == ["start", "web"]


def test_the_tick_now_key_takes_a_web_request_with_it(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    ctx = context(canopy_env)
    asked, stop = tick_now.TickNow(), repeat.Stop()
    asked.request()  # kept through the first tick
    typed = iter(["", repeat.TICK_NOW_KEY])  # dropped after the tick, then pressed at the wait's first step
    time = FakeTime(on_sleep=lambda: setattr(stop, "requested", True))
    term, _ = console()
    with overseer_does():
        repeat.run(
            ctx,
            dry_run=True,
            interval_minutes=15,
            max_ticks=3,
            console=term,
            stop=stop,
            asked=asked,
            keys=lambda: next(typed, ""),
            sleep=time.sleep,
            clock=time.clock,
        )
    # One tick for the key and the web request together: the wait after it runs until the stop.
    assert [w for _, w in recorded(canopy_env)] == ["start", "key"]
    assert time.slept == [0.5]


def test_a_tick_run_by_hand_records_nothing_of_the_loop(scenario: Scenario) -> None:
    ticked = scenario.tick(dry_run=True)
    assert (ticked.tick.idle, ticked.tick.woken_by) == (None, None)
    assert recorded(scenario.env) == [(None, None)]
