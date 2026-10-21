"""What canopy keeps, measured by `canopy gc --dry-run` over journals and files written by hand (DESIGN §26)."""

import json
import operator
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli import gc as gc_cli
from canopy.cli.main import main
from canopy.core import conversation, db
from canopy.infra import lock, logs
from canopy.loop import attention, gc
from tests.canopy.helpers import KEY, earlier
from tests.conftest import CanopyEnv

MIB = 1024 * 1024


def tick(conn: sqlite3.Connection, ended: str | None, status: str = "ok") -> int:
    cursor = conn.execute(
        "INSERT INTO ticks (started_at, ended_at, status) VALUES (?, ?, ?)",
        (ended or db.now(), ended, status),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def run(conn: sqlite3.Connection, env: CanopyEnv, tick_id: int, ended: str | None) -> Path:
    """A worker run of `tick_id` that ended at `ended`, or is running, with its log and prompt written."""
    db.touch_ticket(conn, KEY, str(env.root))
    cursor = conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, status, log_path) "
        "VALUES (?, ?, 'implement', 'agent/x', ?, ?, ?, '')",
        (tick_id, KEY, ended or db.now(), ended, "done" if ended else "running"),
    )
    log = env.state_dir / "runs" / f"{cursor.lastrowid}.log"
    conn.execute("UPDATE runs SET log_path = ? WHERE id = ?", (str(log), cursor.lastrowid))
    write(log, 100)
    write(log.with_suffix(".prompt"), 10)
    return log


def write(path: Path, size: int, *, hours_old: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if hours_old:
        moment = datetime.now(UTC).timestamp() - hours_old * 3600
        os.utime(path, (moment, moment))
    return path


def dry_run(capsys: pytest.CaptureFixture[str]) -> dict[str, dict[str, object]]:
    """Each kind `canopy gc --dry-run --json` reports, by name."""
    assert main(["gc", "--dry-run", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    return {k["name"]: k for k in report["kinds"]}


# A kind's count and size, then how many a pass removes and their size.
removes = operator.itemgetter("count", "size", "removable", "removable_size")


def test_a_dry_run_counts_what_a_pass_would_remove_and_removes_nothing(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime.now(UTC)
    conn = canopy_env.journal()
    old_ok = tick(conn, earlier(now, 10))
    old_failed = tick(conn, earlier(now, 10), "overseer_failed")
    tick(conn, None, "running")
    for tick_id in (old_ok, old_failed):
        write(canopy_env.state_dir / "ticks" / f"{tick_id}.log", 7)
    old = run(conn, canopy_env, old_ok, earlier(now, 40))
    run(conn, canopy_env, old_ok, earlier(now, 2))
    run(conn, canopy_env, old_ok, None)
    live = run(conn, canopy_env, old_ok, earlier(now, 40))
    write(canopy_env.state_dir / "reviews" / "9.prompt", 5, hours_old=2)
    write(canopy_env.state_dir / "reviews" / "10.prompt", 5)
    (canopy_env.state_dir / "reviews" / "11.prompt").symlink_to(old)
    conn.commit()
    before = sorted(p for p in canopy_env.state_dir.rglob("*") if p.is_file())

    held = lock.take(live.with_suffix(".lock"))
    try:
        kinds = dry_run(capsys)
    finally:
        os.close(held)

    # One run past `run_files_days`; the recent one, the running one, and the one holding its lifelock stay.
    assert removes(kinds["run files"]) == (8, 440, 2, 110)
    # The ok tick is past `tick_files_days`; the failed one keeps its files for `run_files_days`.
    assert removes(kinds["tick files"]) == (2, 14, 1, 7)
    # A file no row names goes once an hour old, and a link is never counted.
    assert removes(kinds["unrecorded files"]) == (2, 10, 1, 5)
    assert [p for p in before if not p.exists()] == []


def test_a_runs_kept_diffs_are_its_run_files(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    """A run under `approve` keeps a diff and its head per repository (DESIGN §29): its files, not unrecorded ones."""
    now = datetime.now(UTC)
    conn = canopy_env.journal()
    old = run(conn, canopy_env, tick(conn, earlier(now, 10)), earlier(now, 40))
    run_id = int(old.stem)
    conn.execute(
        "INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder) VALUES (?, 'api', '/s', 'l', 'h')",
        (run_id,),
    )
    write(old.with_name(f"{run_id}.api.diff"), 30, hours_old=2)
    write(old.with_name(f"{run_id}.api.head"), 41, hours_old=2)
    conn.commit()
    kinds = dry_run(capsys)
    assert removes(kinds["run files"]) == (4, 181, 4, 181)
    assert removes(kinds["unrecorded files"])[0] == 0


def test_retention_of_zero_keeps_a_kind_forever(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    canopy_env.append_user("\n[retention]\nrun_files_days = 0\ntick_files_days = 0\n")
    conn = canopy_env.journal()
    now = datetime.now(UTC)
    old = tick(conn, earlier(now, 400))
    write(canopy_env.state_dir / "ticks" / f"{old}.log", 7)
    run(conn, canopy_env, old, earlier(now, 400))
    conn.commit()

    kinds = dry_run(capsys)

    assert removes(kinds["run files"]) == (2, 110, 0, 0)
    assert removes(kinds["tick files"]) == (1, 7, 0, 0)


def test_canopy_log_rotation_would_drop_what_passes_log_keep(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.append_user("\n[retention]\nlog_max_mib = 1\nlog_keep = 2\n")
    for name, size in (("", MIB + 1), (".1", 3), (".2", 4)):
        write(canopy_env.state_dir / f"{logs.LOG_FILE_NAME}{name}", size)

    kinds = dry_run(capsys)

    # Over the limit, the log rotates, and what was `.2` would be `.3`, past `log_keep`. The command's own lines land in
    # the log before it is measured.
    count, size, removable, removable_size = removes(kinds["canopy.log"])
    assert (count, removable, removable_size) == (3, 1, 4)
    assert isinstance(size, int)
    assert size >= MIB + 8
    assert "due to rotate" in str(kinds["canopy.log"]["rule"])


def test_harness_attention_goes_only_outside_the_window_and_after_journal_days(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = canopy_env.journal()
    now = datetime.now(UTC)
    ticks = [tick(conn, earlier(now, 200)) for _ in range(3)]
    recent = tick(conn, earlier(now, 1))
    for tick_id in [*ticks, recent]:
        conn.execute(
            "INSERT INTO decisions (tick_id, ticket_key, action, rationale, created_at) VALUES (?, ?, ?, 'r', ?)",
            (tick_id, KEY, "attention:crashed", earlier(now, 200 if tick_id != recent else 1)),
        )
        db.record_decision(conn, tick_id, KEY, "attention:needs_review", "the overseer's")
    conn.commit()

    # With fewer `ok` ticks than the window, nothing goes, whatever `journal_days` says.
    kinds = dry_run(capsys)
    assert removes(kinds["harness attention"])[2] == 0
    assert removes(kinds["overseer attention"])[:1] == (4,)

    # The window is the newest two ticks here: the two before them are outside it, and older than 90 days.
    with mock.patch.object(attention, "HISTORY_TICKS", 2):
        kinds = dry_run(capsys)
    assert kinds["harness attention"]["count"] == 4
    assert kinds["harness attention"]["removable"] == 2
    assert kinds["overseer attention"]["removable"] == 0


def test_a_connector_run_goes_outside_the_window_after_journal_days_but_each_sources_newest_stays(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = canopy_env.journal()
    now = datetime.now(UTC)
    old = earlier(now, 200)
    for source, query in [("jira", "[]"), ("jira", None), ("jira", None), ("github", None)]:
        tick_id = tick(conn, old)
        conn.execute(
            "INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, "
            "refused, missed, stderr, query_result) VALUES (?, ?, ?, ?, ?, 'ok', '{}', '{}', '{}', NULL, '', ?)",
            (tick_id, source, "vcs" if source == "github" else "tracker", old, old, query),
        )
    tick(conn, db.now())
    conn.commit()
    assert dry_run(capsys)["connector runs"]["removable"] == 0, "nothing goes while the window holds every tick"
    with mock.patch.object(attention, "HISTORY_TICKS", 1):
        kinds = dry_run(capsys)
    # jira's newest run and its newest with the query's result stay, and so does github's only run.
    assert (kinds["connector runs"]["count"], kinds["connector runs"]["removable"]) == (4, 1)


def test_a_polls_connector_run_is_outside_the_window_once_it_started_before_the_windows_oldest_tick(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = canopy_env.journal()
    now = datetime.now(UTC)
    old, newer = earlier(now, 200), earlier(now, 100)
    tick(conn, old)
    # Two polls between ticks, made by no tick: one before the window's oldest tick, one after it.
    for started in (old, db.now()):
        conn.execute(
            "INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, "
            "refused, missed, stderr) VALUES (NULL, 'github', 'vcs', ?, ?, 'ok', '{}', '{}', '{}', NULL, '')",
            (started, started),
        )
    tick(conn, newer)
    conn.commit()
    with mock.patch.object(attention, "HISTORY_TICKS", 1):
        kinds = dry_run(capsys)
    # The older poll goes; the newer is inside the window, and is github's newest besides.
    assert (kinds["connector runs"]["count"], kinds["connector runs"]["removable"]) == (2, 1)


def test_a_ticks_derivations_go_outside_the_window_after_journal_days(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = canopy_env.journal()
    now = datetime.now(UTC)
    for started in (earlier(now, 200), earlier(now, 200), db.now()):
        conn.execute(
            "INSERT INTO derivations (tick_id, ticket_key, repo, candidate, closed, phases) "
            "VALUES (?, ?, NULL, 1, 0, ?)",
            (tick(conn, started), KEY, '["ready"]'),
        )
    conn.commit()
    assert dry_run(capsys)["derivations"]["removable"] == 0, "nothing goes while the window holds every tick"
    with mock.patch.object(attention, "HISTORY_TICKS", 1):
        kinds = dry_run(capsys)
    # The newest tick is inside the window; both older ones are past journal_days.
    assert (kinds["derivations"]["count"], kinds["derivations"]["removable"]) == (3, 2)


@pytest.mark.parametrize("env", [conversation.TICK_ID_ENV, conversation.RUN_ID_ENV])
def test_an_agent_cannot_run_gc(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str], env: str) -> None:
    with mock.patch.dict(os.environ, {env: "3"}):
        assert main(["gc", "--dry-run"]) == 1
    assert "gc refused (inside_run)" in capsys.readouterr().err


def test_gc_without_dry_run_removes_nothing_yet(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["gc"]) == 2
    assert "only `canopy gc --dry-run` is built yet" in capsys.readouterr().err


def test_the_text_report(snapshot: SnapshotAssertion) -> None:
    report = gc.Report(
        at="2026-10-18T09:30:00.000Z",
        kinds=[
            gc.Kind("run files", "files", 812, 1_288_490_188, 301, 430_000_000, "run_files_days = 30"),
            gc.Kind("harness attention", "rows", 52_000, 9_100_000, 0, 0, "journal_days = 90"),
            gc.Kind("journal WAL", "files", 0, 0, 0, 0, "checkpointed"),
        ],
        journal_size=126_000_000,
        notes=["repo: git count-objects failed in /ws/repos/repo"],
    )
    assert "\n".join(gc_cli.render(report)) == snapshot
