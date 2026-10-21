"""Which models served each agent run, read from its session after each live tick (DESIGN §13, Each agent's model)."""

import json
import sqlite3
from pathlib import Path

from canopy.core import run_models
from canopy.core.context import Context
from canopy.infra import logs
from canopy.loop import models
from tests.canopy.helpers import with_events
from tests.canopy.scenario_helpers import Scenario

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


def reads(conn: sqlite3.Connection) -> list[tuple[str, int, str, str | None, int]]:
    return [
        (str(r[0]), int(r[1]), str(r[2]), r[3], int(r[4]))
        for r in conn.execute(
            "SELECT run_table, run_id, status, error, attempts FROM run_model_reads ORDER BY run_table, run_id"
        )
    ]


def test_a_live_tick_reads_which_models_served_its_overseer_once(scenario: Scenario, opencode_state: Path) -> None:
    with_events(scenario.env, "canopy-overseer")
    sessions(opencode_state, **{SESSION: [("anthropic", "claude-x", 0.25), ("openai", "gpt-y", 0.5)] * 2})
    first = scenario.tick()
    assert [(m.model, m.replies, m.cost_usd) for m in run_models.of_run(scenario.conn, "ticks", first.tick.id)] == [
        ("openai/gpt-y", 2, 1.0),
        ("anthropic/claude-x", 2, 0.5),
    ]
    # Read where the overseer runs, its text left out.
    assert exports(opencode_state) == [(["export", SESSION, "--sanitize"], str(scenario.env.root))]
    second = scenario.tick()
    # Each tick reads its own overseer's session, and none read already.
    assert reads(scenario.conn) == [
        ("ticks", first.tick.id, "found", None, 1),
        ("ticks", second.tick.id, "found", None, 1),
    ]
    assert len(exports(opencode_state)) == 2


def test_a_dry_run_reads_no_session(scenario: Scenario, opencode_state: Path) -> None:
    with_events(scenario.env, "canopy-overseer")
    scenario.tick(dry_run=True)
    assert (exports(opencode_state), reads(scenario.conn)) == ([], [])


def test_a_session_opencode_no_longer_has_is_missing_and_not_read_again(
    scenario: Scenario, opencode_state: Path
) -> None:
    with_events(scenario.env, "canopy-overseer")
    first = scenario.tick()
    assert reads(scenario.conn) == [("ticks", first.tick.id, "missing", None, 1)]
    assert run_models.of_run(scenario.conn, "ticks", first.tick.id) == []


def test_a_failing_opencode_ends_the_batch_and_never_the_tick(
    scenario: Scenario, opencode_state: Path, ctx: Context
) -> None:
    for i in range(3):
        scenario.conn.execute(
            "INSERT INTO ticks (started_at, ended_at, dry_run, status, session_id) VALUES (?, ?, 0, 'ok', ?)",
            (f"2026-10-0{i + 1}T00:00:00.000Z", f"2026-10-0{i + 1}T00:01:00.000Z", f"ses_{i}"),
        )
    opencode_state.write_text(json.dumps({"exit": 1, "stderr": "Error: database is locked\n"}))
    assert models.attribute(ctx, logs.for_tick(None)) == 1
    [(table, run_id, status, error, attempts)] = reads(scenario.conn)
    # The newest first, failed in canopy's words, not OpenCode's.
    assert (table, run_id, status, error, attempts) == (
        "ticks",
        3,
        "failed",
        "`opencode export --sanitize` exited 1",
        1,
    )
    with_events(scenario.env, "canopy-overseer")
    # The tick's own overseer is due first, being newest, and fails the same; the tick still closes `ok`.
    assert scenario.tick().tick.status == "ok"
    assert reads(scenario.conn)[-1][2:] == ("failed", "`opencode export --sanitize` exited 1", 1)


def test_a_tick_reads_at_most_a_few_sessions_the_newest_first(opencode_state: Path, ctx: Context) -> None:
    for i in range(models.PER_TICK + 2):
        ctx.conn.execute(
            "INSERT INTO ticks (started_at, ended_at, dry_run, status, session_id) VALUES (?, ?, 0, 'ok', ?)",
            (f"2026-10-{i + 10}T00:00:00.000Z", f"2026-10-{i + 10}T00:01:00.000Z", f"ses_{i}"),
        )
    sessions(opencode_state, ses_6=[("anthropic", "claude-x", 0.1)])
    assert models.attribute(ctx, logs.for_tick(None)) == models.PER_TICK
    assert [argv[1] for argv, _ in exports(opencode_state)] == ["ses_6", "ses_5", "ses_4", "ses_3", "ses_2"]
    assert models.attribute(ctx, logs.for_tick(None)) == 2
    assert models.attribute(ctx, logs.for_tick(None)) == 0


def test_an_export_longer_than_a_pipe_holds_is_read_whole(opencode_state: Path, ctx: Context) -> None:
    ctx.conn.execute(
        "INSERT INTO ticks (started_at, ended_at, dry_run, status, session_id) VALUES (?, ?, 0, 'ok', 'ses_big')",
        ("2026-10-01T00:00:00.000Z", "2026-10-01T00:01:00.000Z"),
    )
    # Far past the 64 KiB a pipe holds, which the fake, as OpenCode does, would cut it to.
    sessions(opencode_state, ses_big=[("anthropic", "claude-x", 0.5)] * 1000)
    assert models.attribute(ctx, logs.for_tick(None)) == 1
    assert reads(ctx.conn) == [("ticks", 1, "found", None, 1)]
    assert [(m.model, m.replies) for m in run_models.of_run(ctx.conn, "ticks", 1)] == [("anthropic/claude-x", 1000)]
