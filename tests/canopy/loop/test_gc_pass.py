"""The pass of garbage collection a live tick runs (DESIGN §26), over journals and files written by hand.

The tests cover the files it removes, what it never removes, and the `gc_passes` row it records.
"""

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import db, records, sql
from canopy.core.context import Context
from canopy.core.vocab import GcPassStatus
from canopy.infra import lock, logs
from canopy.loop import attention, gc, gc_pass
from canopy.notify import journal
from tests.canopy.helpers import KEY, context, earlier, ended_tick, run_with_files, write_file
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import CanopyEnv

MIB = 1024 * 1024
# The kinds of file a pass removes, as the dry run names them.
FILE_KINDS = ("run files", "tick files", "chore run files", "review files", "unrecorded files")
# The tables whose rows a test counts before and after a pass.
type Table = Literal["decisions", "connector_runs", "derivations", "ticks"]
TABLES: tuple[Table, ...] = ("decisions", "connector_runs", "derivations", "ticks")


def passes(conn: sqlite3.Connection) -> list[records.GcPass]:
    """Every pass the journal recorded, oldest first."""
    return records.fetch_all(conn, records.GcPass, sql.select("*").from_("gc_passes").order_by("id"))


def removed_by_kind(row: records.GcPass) -> dict[str, tuple[int, int]]:
    """What a pass recorded it removed: each kind's files and bytes."""
    return {kind: (n["files"], n["bytes"]) for kind, n in json.loads(row.removed).items()}


def predicted(capsys: pytest.CaptureFixture[str]) -> dict[str, tuple[int, int]]:
    """What `canopy gc --dry-run --json` says a pass would remove of each kind of file, the kinds with none left out."""
    assert main(["gc", "--dry-run", "--json"]) == 0
    kinds = json.loads(capsys.readouterr().out)["kinds"]
    return {
        k["name"]: (k["removable"], k["removable_size"]) for k in kinds if k["name"] in FILE_KINDS and k["removable"]
    }


def run_pass(ctx: Context) -> records.GcPass:
    """Run the pass in a live tick of its own, and give back the row it recorded."""
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    pass_id = gc_pass.run(ctx, tick_id, logs.for_tick(tick_id))
    assert pass_id is not None, "no pass ran"
    [row] = [p for p in passes(ctx.conn) if p.id == pass_id]
    assert row.tick_id == tick_id
    return row


def files_under(root: Path) -> set[Path]:
    """Every file and link under `root`."""
    return {p for p in root.rglob("*") if p.is_file() or p.is_symlink()}


def test_a_pass_removes_what_the_dry_run_predicted_and_never_a_live_runs_files_a_running_ticks_or_a_link(
    canopy_env: CanopyEnv,
    ctx: Context,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime.now(UTC)
    conn = canopy_env.journal()
    old_ok = ended_tick(conn, earlier(now, 10))
    old_failed = ended_tick(conn, earlier(now, 10), "overseer_failed")
    running_tick = ended_tick(conn, None, "running")
    for tick_id in (old_ok, old_failed, running_tick):
        write_file(canopy_env.state_dir / "ticks" / f"{tick_id}.log", 7, hours_old=240)
    old = run_with_files(conn, canopy_env, old_ok, earlier(now, 40))
    recent = run_with_files(conn, canopy_env, old_ok, earlier(now, 2))
    running = run_with_files(conn, canopy_env, old_ok, None)
    live = run_with_files(conn, canopy_env, old_ok, earlier(now, 40))
    unrecorded = write_file(canopy_env.state_dir / "reviews" / "9.prompt", 5, hours_old=2)
    write_file(canopy_env.state_dir / "reviews" / "10.prompt", 5)
    link = canopy_env.state_dir / "reviews" / "11.prompt"
    link.symlink_to(recent)
    old_link = canopy_env.state_dir / "runs" / "77.log"
    old_link.symlink_to(recent.with_suffix(".prompt"))
    os.utime(old_link, (now.timestamp() - 7200, now.timestamp() - 7200), follow_symlinks=False)
    before = files_under(canopy_env.state_dir)

    held = lock.take(live.with_suffix(".lock"))
    try:
        expected = predicted(capsys)
        row = run_pass(ctx)
        after = predicted(capsys)
    finally:
        os.close(held)

    assert expected == {"run files": (2, 110), "tick files": (1, 7), "unrecorded files": (1, 5)}
    assert removed_by_kind(row) == expected
    assert (row.status, row.failures, row.error) == (GcPassStatus.OK, 0, None)
    gone = {old, old.with_suffix(".prompt"), canopy_env.state_dir / "ticks" / f"{old_ok}.log", unrecorded}
    assert before - files_under(canopy_env.state_dir) == gone
    # What it kept: a live run's files, a running run's, a running tick's, a failed tick's, and every link.
    for kept in (live, running, recent, canopy_env.state_dir / "ticks" / f"{running_tick}.log", link, old_link):
        assert kept.is_symlink() or kept.is_file(), kept
    assert recent.read_bytes() == b"x" * 100, "a link's target is not touched"
    # A dry run after it finds nothing more to remove of what the pass removed.
    assert after == {}


def test_a_file_with_no_row_goes_only_after_an_hour(canopy_env: CanopyEnv, ctx: Context) -> None:
    state = canopy_env.state_dir
    young = [
        write_file(state / directory / name, 3, hours_old=0.9)
        for directory, name in [("runs", "98.log"), ("ticks", "98.prompt"), ("chore-runs/tidy", "98.log")]
    ]
    old = [
        write_file(state / directory / name, 3, hours_old=1.1)
        for directory, name in [("runs", "99.log"), ("reviews", "99.diff"), ("chore-runs/tidy", "99.prompt")]
    ]

    row = run_pass(ctx)

    assert removed_by_kind(row) == {"unrecorded files": (3, 9)}
    assert [p.exists() for p in young] == [True, True, True]
    assert [p.exists() for p in old] == [False, False, False]


def test_a_pass_runs_at_most_once_a_day(canopy_env: CanopyEnv, ctx: Context) -> None:
    run_pass(ctx)
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    assert gc_pass.run(ctx, tick_id, logs.for_tick(tick_id)) is None
    assert len(passes(ctx.conn)) == 1
    ctx.conn.execute("UPDATE gc_passes SET started_at = ?", (earlier(datetime.now(UTC), 1, hours=0.1),))
    run_pass(ctx)
    assert len(passes(ctx.conn)) == 2


def test_a_dry_tick_runs_no_pass_and_a_live_tick_runs_one(scenario: Scenario) -> None:
    orphan = write_file(scenario.env.state_dir / "runs" / "99.log", 3, hours_old=2)

    scenario.tick(dry_run=True)
    assert passes(scenario.conn) == []
    assert orphan.exists()

    ticked = scenario.tick()
    [row] = passes(scenario.conn)
    assert row.tick_id == ticked.tick.id
    assert removed_by_kind(row) == {"unrecorded files": (1, 3)}
    assert not orphan.exists()

    # The next live tick that day runs none; one a day later does.
    scenario.tick()
    assert len(passes(scenario.conn)) == 1
    scenario.time_passes(hours=25)
    scenario.tick()
    assert len(passes(scenario.conn)) == 2


def test_a_failed_pass_is_logged_and_recorded_and_the_tick_goes_on(scenario: Scenario) -> None:
    with mock.patch.object(gc, "file_kinds", autospec=True, side_effect=OSError("No space left on device")):
        ticked = scenario.tick()
    assert ticked.tick.status == "ok"
    [row] = passes(scenario.conn)
    assert (row.status, row.error, row.removed) == (GcPassStatus.FAILED, "OSError: No space left on device", "{}")
    lines = [json.loads(line) for line in (scenario.env.state_dir / logs.LOG_FILE_NAME).read_text().splitlines()]
    assert any(line["msg"] == "gc pass failed" and line["tick_id"] == ticked.tick.id for line in lines)


def test_a_file_it_cannot_remove_is_counted_and_the_pass_goes_on(canopy_env: CanopyEnv, ctx: Context) -> None:
    state = canopy_env.state_dir
    stuck = write_file(state / "runs" / "98.log", 3, hours_old=2)
    freed = write_file(state / "runs" / "99.log", 4, hours_old=2)
    unlink = Path.unlink

    def refuse(path: Path, *, missing_ok: bool = False) -> None:
        if path == stuck:
            raise PermissionError(13, "Permission denied", str(path))
        unlink(path, missing_ok=missing_ok)

    with mock.patch.object(Path, "unlink", autospec=True, side_effect=refuse):
        row = run_pass(ctx)

    assert (row.status, row.failures) == (GcPassStatus.OK, 1)
    assert removed_by_kind(row) == {"unrecorded files": (1, 4)}
    assert stuck.exists()
    assert not freed.exists()


def test_retention_of_zero_keeps_a_kind_and_records_no_cutoff(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user("\n[retention]\nrun_files_days = 0\n")
    ctx = context(canopy_env)
    conn = canopy_env.journal()
    now = datetime.now(UTC)
    old = run_with_files(conn, canopy_env, ended_tick(conn, earlier(now, 400)), earlier(now, 400))

    row = run_pass(ctx)

    assert old.exists()
    assert (row.run_files_days, row.run_cutoff) == (0, None)
    assert row.tick_cutoff is not None


def test_a_live_tick_rotates_canopy_log_past_log_max_mib_as_the_dry_run_predicted(
    scenario: Scenario,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scenario.configures(retention={"log_max_mib": 1, "log_keep": 1})
    state = scenario.env.state_dir
    log = state / logs.LOG_FILE_NAME
    with log.open("a") as f:
        f.write("x" * (MIB + 1) + "\n")
    write_file(state / f"{logs.LOG_FILE_NAME}.1", 3)

    scenario.tick(dry_run=True)
    assert log.stat().st_size > MIB, "a dry tick rotates nothing"
    assert main(["gc", "--dry-run", "--json"]) == 0
    [kind] = [k for k in json.loads(capsys.readouterr().out)["kinds"] if k["name"] == "canopy.log"]
    assert (kind["removable"], kind["removable_size"]) == (1, 3)

    ticked = scenario.tick()

    rotated = state / f"{logs.LOG_FILE_NAME}.1"
    assert rotated.stat().st_size > MIB
    assert not (state / f"{logs.LOG_FILE_NAME}.2").exists(), "past log_keep"
    # This process's handler followed the move: the tick's later lines are in the new log.
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(line["msg"] == "tick finished" and line["tick_id"] == ticked.tick.id for line in lines)


def attention_row(conn: sqlite3.Connection, tick_id: int, key: str, reason: str, at: str) -> int:
    """An attention item tick `tick_id` recorded at `at`, as the harness or the overseer does each tick it holds."""
    cursor = conn.execute(
        "INSERT INTO decisions (tick_id, ticket_key, action, rationale, created_at) VALUES (?, ?, ?, ?, ?)",
        (tick_id, key, f"{attention.ACTION_PREFIX}{reason}", f"{reason} of {key}", at),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def connector_run(conn: sqlite3.Connection, tick_id: int | None, source: str, at: str, query: str | None = None) -> int:
    """A run of `source` that started at `at`: a tick's, or a poll's with no tick, recording `query` if it read it."""
    cursor = conn.execute(
        "INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, "
        "missed, stderr, query_result) VALUES (?, ?, 'tracker', ?, ?, 'ok', '{}', '{}', '{}', NULL, '', ?)",
        (tick_id, source, at, at, query),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def derived(conn: sqlite3.Connection, tick_id: int) -> int:
    """What tick `tick_id` derived of KEY, in shadow."""
    cursor = conn.execute(
        "INSERT INTO derivations (tick_id, ticket_key, repo, candidate, closed, phases) VALUES (?, ?, NULL, 1, 0, ?)",
        (tick_id, KEY, '["ready"]'),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def rows_of(conn: sqlite3.Connection) -> dict[Table, set[int]]:
    """The ids of every row of each table a test counts."""
    return {table: {int(r[0]) for r in sql.execute(conn, sql.select("id").from_(table))} for table in TABLES}


def told(conn: sqlite3.Connection, key: str, reason: str) -> None:
    """The sink `slack` was told of `key`'s `reason` item, as a delivery records it."""
    conn.execute(
        "INSERT INTO notifications (sink, fingerprint, ticket_key, reason, sent_at) VALUES ('slack', ?, ?, ?, ?)",
        (attention.fingerprint(key, reason, None), key, reason, db.now()),
    )


def what_the_operator_sees(conn: sqlite3.Connection) -> tuple[object, ...]:
    """The attention list, each item with its open-since, and what the sink `slack` would be told of it now."""
    items = attention.current(conn)
    change = journal.diff(conn, "slack", items)
    return (items, change.added, change.resolved)


def test_a_pass_deletes_journal_rows_outside_the_window_and_the_operator_sees_the_same_after(
    canopy_env: CanopyEnv,
    ctx: Context,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The window is the newest three `ok` ticks here, not a thousand.
    with mock.patch.object(attention, "HISTORY_TICKS", 3):
        conn = canopy_env.journal()
        now = datetime.now(UTC)
        old, young = earlier(now, 200), earlier(now, 10)
        # A poll between ticks, made long before the window, and not its source's newest run.
        poll = connector_run(conn, None, "jira", earlier(now, 300))
        failed = ended_tick(conn, old, "overseer_failed")
        gone = {attention_row(conn, failed, KEY, "crashed", old)}
        # Six `ok` ticks, the window the newest three. Of the three before it, the third is younger than journal_days.
        ticks = [ended_tick(conn, young if n == 2 else old) for n in range(6)]
        runs: list[int] = []
        derivations: list[int] = []
        for n, tick_id in enumerate(ticks):
            at = young if n == 2 else old
            harness = [attention_row(conn, tick_id, KEY, "crashed", at)]
            attention_row(conn, tick_id, "PROJ-4", "needs_reviewer", at)
            if n < 2:
                harness.append(attention_row(conn, tick_id, "PROJ-2", "unpushed", at))
            if n > 3:
                attention_row(conn, tick_id, "PROJ-3", "worker_failed", at)
            if n < 2:
                gone.update(harness)
            runs.append(connector_run(conn, tick_id, "jira", at, query='["PROJ-1"]' if n == 0 else None))
            derivations.append(derived(conn, tick_id))
        github = connector_run(conn, ticks[1], "github", old)
        told(conn, KEY, "crashed")
        told(conn, "PROJ-2", "unpushed")
        before = rows_of(conn)
        seen = what_the_operator_sees(conn)
        assert main(["gc", "--dry-run", "--json"]) == 0
        predicted = {k["name"]: k for k in json.loads(capsys.readouterr().out)["kinds"] if k["unit"] == "rows"}

        row = run_pass(ctx)

        assert what_the_operator_sees(conn) == seen
        removed = {kind: n for kind, n in json.loads(row.removed).items() if "rows" in n}
        assert {kind: n["rows"] for kind, n in removed.items()} == {
            "harness attention": 5,
            "connector runs": 2,
            "derivations": 2,
        }
        assert {kind: (n["rows"], n["bytes"]) for kind, n in removed.items()} == {
            kind: (predicted[kind]["removable"], predicted[kind]["removable_size"]) for kind in removed
        }
        after = rows_of(conn)
        # The harness's items of the failed tick and of the two old ticks before the window; never the overseer's.
        assert before["decisions"] - after["decisions"] == gone
        # jira's run that recorded the query's result and github's only run stay, however old.
        assert before["connector_runs"] - after["connector_runs"] == {poll, runs[1]}
        assert {runs[0], github} <= after["connector_runs"]
        assert before["derivations"] - after["derivations"] == set(derivations[:2])
        assert before["ticks"] <= after["ticks"], "no tick is deleted"
        # A dry run after it finds nothing more to remove.
        assert main(["gc", "--dry-run", "--json"]) == 0
        kinds = json.loads(capsys.readouterr().out)["kinds"]
        assert {k["name"]: k["removable"] for k in kinds if k["unit"] == "rows"} == dict.fromkeys(predicted, 0)


def test_with_fewer_ok_ticks_than_the_window_a_pass_deletes_no_row(canopy_env: CanopyEnv, ctx: Context) -> None:
    # The window is the newest three `ok` ticks here, not a thousand.
    with mock.patch.object(attention, "HISTORY_TICKS", 3):
        conn = canopy_env.journal()
        old = earlier(datetime.now(UTC), 400)
        # Two `ok` ticks and four that are not: a tick that did not close `ok` is no part of the window.
        for status in ("ok", "overseer_failed", "error", "overseer_failed", "error", "ok"):
            tick_id = ended_tick(conn, old, status)
            attention_row(conn, tick_id, KEY, "crashed", old)
            connector_run(conn, tick_id, "jira", old)
            derived(conn, tick_id)
        before = rows_of(conn)

        row = run_pass(ctx)

        after = rows_of(conn)
        assert after["decisions"] == before["decisions"]
        assert after["connector_runs"] == before["connector_runs"]
        assert after["derivations"] == before["derivations"]
        assert json.loads(row.removed) == {}


def test_a_pass_empties_the_journals_wal(canopy_env: CanopyEnv, ctx: Context) -> None:
    run_pass(ctx)
    assert (canopy_env.state_dir / f"{db.DB_FILE_NAME}-wal").stat().st_size == 0
