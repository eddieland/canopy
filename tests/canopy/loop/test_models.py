"""Which models served each agent run (DESIGN §13, Each agent's model).

Each live tick reads its overseer's session, and the wait after it reads the runs left unread.
"""

import json
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import pause, run_models
from canopy.core.context import Context
from canopy.core.vocab import ModelsRead
from canopy.infra import logs
from canopy.loop import models, repeat
from tests.canopy.helpers import KEY, FakeTime, console, context, overseer_does, waits, with_events
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import CanopyEnv

#: The fake agent's session id on every event it prints.
SESSION = "ses_fake"


def sessions(state: Path, **calls: list[tuple[str, str, float]]) -> None:
    """Have the fake `opencode` know each session named, with its replies' provider, model, and cost in order."""
    state.write_text(json.dumps({"sessions": calls}))


def exports(state: Path) -> list[tuple[list[str], str]]:
    """What the fake `opencode` was run with, and where, in order."""
    log = state.with_name("opencode.jsonl")
    lines: list[str] = log.read_text().splitlines() if log.exists() else []
    return [(entry["argv"], entry["cwd"]) for entry in map(json.loads, lines)]


def ended_ticks(conn: sqlite3.Connection, n: int) -> None:
    """Record `n` live ticks that ended with sessions `ses_0` up, a day apart and older than any tick a test runs."""
    for i in range(n):
        conn.execute(
            "INSERT INTO ticks (started_at, ended_at, dry_run, status, session_id) VALUES (?, ?, 0, 'ok', ?)",
            (f"2026-10-{i + 10}T00:00:00.000Z", f"2026-10-{i + 10}T00:01:00.000Z", f"ses_{i}"),
        )


def exported(state: Path) -> list[str]:
    """The sessions the fake `opencode` exported, in order."""
    return [argv[1] for argv, _ in exports(state)]


def reads(conn: sqlite3.Connection) -> list[tuple[str, int, str, str | None, int]]:
    return [
        (str(r[0]), int(r[1]), str(r[2]), r[3], int(r[4]))
        for r in conn.execute(
            "SELECT run_table, run_id, status, error, attempts FROM run_model_reads ORDER BY run_table, run_id",
        )
    ]


def test_a_live_tick_reads_which_models_served_its_overseer_once(scenario: Scenario, opencode_state: Path) -> None:
    with_events(scenario.env, "canopy-overseer")
    sessions(opencode_state, **{SESSION: [("anthropic", "claude-x", 0.25), ("openai", "gpt-y", 0.5)] * 2})
    first = scenario.tick(*waits(KEY))
    assert [(m.model, m.replies, m.cost_usd) for m in run_models.of_run(scenario.conn, "ticks", first.tick.id)] == [
        ("openai/gpt-y", 2, 1.0),
        ("anthropic/claude-x", 2, 0.5),
    ]
    # Read where the overseer runs, its text left out.
    assert exports(opencode_state) == [(["export", SESSION, "--sanitize"], str(scenario.env.root))]
    second = scenario.tick(*waits(KEY))
    # Each tick reads its own overseer's session, and none read already.
    assert reads(scenario.conn) == [
        ("ticks", first.tick.id, "found", None, 1),
        ("ticks", second.tick.id, "found", None, 1),
    ]
    assert len(exports(opencode_state)) == 2


def test_opencode_2_is_asked_for_its_session_by_its_own_command(scenario: Scenario, opencode_state: Path) -> None:
    with_events(scenario.env, "canopy-overseer")
    scenario.configures(runtime={"version": 2})
    sessions(opencode_state, **{SESSION: [("anthropic", "claude-x", 0.25)]})
    ticked = scenario.tick(*waits(KEY))
    assert [(m.model, m.replies) for m in run_models.of_run(scenario.conn, "ticks", ticked.tick.id)] == [
        ("anthropic/claude-x", 1),
    ]
    assert exports(opencode_state) == [
        (["session", "export", "--standalone", "--sanitize", SESSION], str(scenario.env.root)),
    ]


def test_an_opencode_2_tick_its_events_left_unpriced_costs_what_its_session_says(
    scenario: Scenario,
    opencode_state: Path,
) -> None:
    with_events(scenario.env, "canopy-overseer")
    scenario.configures(runtime={"version": 2})
    sessions(opencode_state, **{SESSION: [("anthropic", "claude-x", 0.25), ("anthropic", "claude-x", 0.5)]})
    # As OpenCode 2 prints a run: its last call's cost never is, so its events leave it unpriced.
    ticked = scenario.tick(*waits(KEY), step_cost='"lost"')
    assert scenario.conn.execute("SELECT cost_usd FROM ticks WHERE id = ?", (ticked.tick.id,)).fetchone()[0] == 0.75


def test_a_dry_run_reads_no_session(scenario: Scenario, opencode_state: Path) -> None:
    with_events(scenario.env, "canopy-overseer")
    scenario.tick(dry_run=True)
    assert (exports(opencode_state), reads(scenario.conn)) == ([], [])


def test_a_session_opencode_no_longer_has_is_missing_and_not_read_again(
    scenario: Scenario,
    opencode_state: Path,
) -> None:
    with_events(scenario.env, "canopy-overseer")
    first = scenario.tick(*waits(KEY))
    assert reads(scenario.conn) == [("ticks", first.tick.id, "missing", None, 1)]
    assert run_models.of_run(scenario.conn, "ticks", first.tick.id) == []


def test_a_tick_reads_its_own_overseer_and_no_run_left_unread(scenario: Scenario, opencode_state: Path) -> None:
    ended_ticks(scenario.conn, 3)
    with_events(scenario.env, "canopy-overseer")
    scenario.tick(*waits(KEY))
    # The wait after a tick reads the rest, not the tick.
    assert exported(opencode_state) == [SESSION]


def test_a_failing_opencode_never_fails_the_tick(scenario: Scenario, opencode_state: Path) -> None:
    opencode_state.write_text(json.dumps({"exit": 1, "stderr": "Error: database is locked\n"}))
    with_events(scenario.env, "canopy-overseer")
    ticked = scenario.tick(*waits(KEY))
    assert ticked.tick.status == "ok"
    # Failed in canopy's words, not OpenCode's, and read again later.
    assert reads(scenario.conn) == [
        ("ticks", ticked.tick.id, "failed", "`opencode export --sanitize` exited 1", 1),
    ]


def test_the_backlog_reads_one_run_a_step_the_newest_first_until_none_is_due(
    opencode_state: Path,
    ctx: Context,
) -> None:
    ended_ticks(ctx.conn, 3)
    sessions(opencode_state, ses_2=[("anthropic", "claude-x", 0.1)])
    time = FakeTime()
    backlog = models.Backlog(time.clock, logs.for_tick(None))
    assert backlog.step(ctx) is ModelsRead.FOUND
    # Too soon after the last read: none.
    assert backlog.step(ctx) is None
    time.sleep(models.GAP_SECONDS)
    assert backlog.step(ctx) is ModelsRead.MISSING
    time.sleep(models.GAP_SECONDS)
    assert backlog.step(ctx) is ModelsRead.MISSING
    time.sleep(models.GAP_SECONDS)
    assert backlog.step(ctx) is None  # none is due
    assert exported(opencode_state) == ["ses_2", "ses_1", "ses_0"]
    assert [(m.model, m.replies) for m in run_models.of_run(ctx.conn, "ticks", 3)] == [("anthropic/claude-x", 1)]

    # Finding none due ends the reading for this wait; the wait after the next tick reads again.
    ended_ticks(ctx.conn, 4)
    time.sleep(models.GAP_SECONDS)
    assert backlog.step(ctx) is None
    backlog.ticked()
    assert backlog.step(ctx) is ModelsRead.MISSING
    assert exported(opencode_state)[-1] == "ses_3"


def test_a_failed_read_ends_the_backlogs_reading_for_the_wait(opencode_state: Path, ctx: Context) -> None:
    ended_ticks(ctx.conn, 2)
    opencode_state.write_text(json.dumps({"exit": 1, "stderr": "Error: database is locked\n"}))
    time = FakeTime()
    backlog = models.Backlog(time.clock, logs.for_tick(None))
    assert backlog.step(ctx) is ModelsRead.FAILED
    time.sleep(models.GAP_SECONDS)
    assert backlog.step(ctx) is None
    assert exported(opencode_state) == ["ses_1"]
    # The next wait reads the run never read, before the failed one, which waits a day.
    opencode_state.write_text("{}")
    backlog.ticked()
    assert backlog.step(ctx) is ModelsRead.MISSING
    assert exported(opencode_state) == ["ses_1", "ses_0"]


def test_what_a_read_raises_ends_the_backlogs_reading_and_never_the_loop(opencode_state: Path, ctx: Context) -> None:
    ended_ticks(ctx.conn, 2)
    time = FakeTime()
    backlog = models.Backlog(time.clock, logs.for_tick(None))
    with mock.patch.object(run_models, "read", autospec=True, side_effect=RuntimeError("boom")):
        assert backlog.step(ctx) is ModelsRead.FAILED
    time.sleep(models.GAP_SECONDS)
    assert backlog.step(ctx) is None


def test_the_backlog_reads_nothing_while_the_loop_is_paused(opencode_state: Path, ctx: Context) -> None:
    ended_ticks(ctx.conn, 1)
    backlog = models.Backlog(FakeTime().clock, logs.for_tick(None))
    pause.pause(ctx.conn, channel=pause.LOOP)
    assert backlog.step(ctx) is None
    pause.resume(ctx.conn)
    assert backlog.step(ctx) is ModelsRead.MISSING


def test_an_export_longer_than_a_pipe_holds_is_read_whole(opencode_state: Path, ctx: Context) -> None:
    ctx.conn.execute(
        "INSERT INTO ticks (started_at, ended_at, dry_run, status, session_id) VALUES (?, ?, 0, 'ok', 'ses_big')",
        ("2026-10-01T00:00:00.000Z", "2026-10-01T00:01:00.000Z"),
    )
    # Far past the 64 KiB a pipe holds, which the fake, as OpenCode does, would cut it to.
    sessions(opencode_state, ses_big=[("anthropic", "claude-x", 0.5)] * 1000)
    assert models.Backlog(FakeTime().clock, logs.for_tick(None)).step(ctx) is ModelsRead.FOUND
    assert reads(ctx.conn) == [("ticks", 1, "found", None, 1)]
    assert [(m.model, m.replies) for m in run_models.of_run(ctx.conn, "ticks", 1)] == [("anthropic/claude-x", 1000)]


@pytest.mark.parametrize("dry_run", [False, True])
def test_the_wait_between_live_ticks_reads_the_runs_left_unread(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    opencode_state: Path,
    dry_run: bool,  # noqa: FBT001
) -> None:
    ended_ticks(canopy_env.journal(), 3)
    ctx = context(canopy_env)
    with overseer_does():
        time = FakeTime()
        term, _ = console()
        repeat.run(
            ctx,
            dry_run=dry_run,
            interval_minutes=1,
            max_ticks=2,
            console=term,
            stop=repeat.Stop(),
            sleep=time.sleep,
            clock=time.clock,
        )
    # A minute's wait reads them all, `GAP_SECONDS` apart; a dry run reads none.
    assert exported(opencode_state) == ([] if dry_run else ["ses_2", "ses_1", "ses_0"])
