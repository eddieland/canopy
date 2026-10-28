"""What canopy keeps, measured by `canopy gc --dry-run` over journals and files written by hand (DESIGN §26)."""

import json
import operator
import os
from datetime import UTC, datetime
from typing import Final
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli import gc as gc_cli
from canopy.cli.main import main
from canopy.core import conversation, db, plans
from canopy.core.vocab import Decider
from canopy.infra import lock, logs
from canopy.loop import attention, gc
from tests.canopy.helpers import KEY, PLAN, earlier, ended_tick, run_with_files, write_file
from tests.conftest import CanopyEnv

MIB: Final = 1024 * 1024


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
    old_ok = ended_tick(conn, earlier(now, 10))
    old_failed = ended_tick(conn, earlier(now, 10), "overseer_failed")
    ended_tick(conn, None, "running")
    for tick_id in (old_ok, old_failed):
        write_file(canopy_env.state_dir / "ticks" / f"{tick_id}.log", 7)
    old = run_with_files(conn, canopy_env, old_ok, earlier(now, 40))
    run_with_files(conn, canopy_env, old_ok, earlier(now, 2))
    run_with_files(conn, canopy_env, old_ok, None)
    live = run_with_files(conn, canopy_env, old_ok, earlier(now, 40))
    write_file(canopy_env.state_dir / "reviews" / "9.prompt", 5, hours_old=2)
    write_file(canopy_env.state_dir / "reviews" / "10.prompt", 5)
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
    old = run_with_files(conn, canopy_env, ended_tick(conn, earlier(now, 10)), earlier(now, 40))
    run_id = int(old.stem)
    conn.execute(
        "INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder) VALUES (?, 'api', '/s', 'l', 'h')",
        (run_id,),
    )
    write_file(old.with_name(f"{run_id}.api.diff"), 30, hours_old=2)
    write_file(old.with_name(f"{run_id}.api.head"), 41, hours_old=2)
    conn.commit()
    kinds = dry_run(capsys)
    assert removes(kinds["run files"]) == (4, 181, 4, 181)
    assert removes(kinds["unrecorded files"])[0] == 0


def test_a_plans_prompt_is_kept_with_its_plan(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    """The archive says what each plan's planner was given (DESIGN §25), so its prompt is kept as long as the plan."""
    now = datetime.now(UTC)
    conn = canopy_env.journal()
    old = run_with_files(conn, canopy_env, ended_tick(conn, earlier(now, 10)), earlier(now, 40))
    plans.record(conn, KEY, int(old.stem), plans.write(canopy_env.state_dir, KEY, int(old.stem), PLAN))
    conn.commit()

    kinds = dry_run(capsys)

    # The log goes; the prompt stays.
    assert removes(kinds["run files"]) == (2, 110, 1, 100)


def test_retention_of_zero_keeps_a_kind_forever(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    canopy_env.append_user("\n[retention]\nrun_files_days = 0\ntick_files_days = 0\n")
    conn = canopy_env.journal()
    now = datetime.now(UTC)
    old = ended_tick(conn, earlier(now, 400))
    write_file(canopy_env.state_dir / "ticks" / f"{old}.log", 7)
    run_with_files(conn, canopy_env, old, earlier(now, 400))
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
        write_file(canopy_env.state_dir / f"{logs.LOG_FILE_NAME}{name}", size)

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
    ticks = [ended_tick(conn, earlier(now, 200)) for _ in range(3)]
    recent = ended_tick(conn, earlier(now, 1))
    for tick_id in [*ticks, recent]:
        at = earlier(now, 200 if tick_id != recent else 1)
        # The harness's own, and one it raises from its cause, marked as its own (DESIGN §37).
        conn.execute(
            "INSERT INTO decisions (tick_id, ticket_key, action, rationale, created_at) VALUES (?, ?, ?, 'r', ?)",
            (tick_id, KEY, "attention:crashed", at),
        )
        conn.execute(
            "INSERT INTO decisions (tick_id, ticket_key, action, rationale, created_at, decider) "
            "VALUES (?, ?, ?, 'r', ?, ?)",
            (tick_id, KEY, "attention:needs_reviewer", at, Decider.HARNESS),
        )
        # The overseer's, of the same reason before the harness raised it: the corpus.
        db.record_decision(conn, tick_id, KEY, "attention:needs_reviewer", "the overseer's")
    conn.commit()

    # With fewer `ok` ticks than the window, nothing goes, whatever `journal_days` says.
    kinds = dry_run(capsys)
    assert removes(kinds["harness attention"])[2] == 0
    assert removes(kinds["overseer attention"])[:1] == (4,)

    # The window is the newest two ticks here: the two before them are outside it, and older than 90 days.
    with mock.patch.object(attention, "HISTORY_TICKS", 2):
        kinds = dry_run(capsys)
    assert kinds["harness attention"]["count"] == 8
    assert kinds["harness attention"]["removable"] == 4
    assert kinds["overseer attention"]["removable"] == 0


def test_a_connector_run_goes_outside_the_window_after_journal_days_but_each_sources_newest_stays(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = canopy_env.journal()
    now = datetime.now(UTC)
    old = earlier(now, 200)
    for source, query in [("jira", "[]"), ("jira", None), ("jira", None), ("github", None)]:
        tick_id = ended_tick(conn, old)
        conn.execute(
            "INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, "
            "refused, missed, stderr, query_result) VALUES (?, ?, ?, ?, ?, 'ok', '{}', '{}', '{}', NULL, '', ?)",
            (tick_id, source, "vcs" if source == "github" else "tracker", old, old, query),
        )
    ended_tick(conn, db.now())
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
    ended_tick(conn, old)
    # Two polls between ticks, made by no tick: one before the window's oldest tick, one after it.
    for started in (old, db.now()):
        conn.execute(
            "INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, "
            "refused, missed, stderr) VALUES (NULL, 'github', 'vcs', ?, ?, 'ok', '{}', '{}', '{}', NULL, '')",
            (started, started),
        )
    ended_tick(conn, newer)
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
            (ended_tick(conn, started), KEY, '["ready"]'),
        )
    conn.commit()
    assert dry_run(capsys)["derivations"]["removable"] == 0, "nothing goes while the window holds every tick"
    with mock.patch.object(attention, "HISTORY_TICKS", 1):
        kinds = dry_run(capsys)
    # The newest tick is inside the window; both older ones are past journal_days.
    assert (kinds["derivations"]["count"], kinds["derivations"]["removable"]) == (3, 2)


def test_a_kept_check_run_goes_after_journal_days_once_its_pr_is_seen_past_its_head(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Only a check run at its PR's head is read (DESIGN §35), so one goes once its PR moved on or ended."""
    conn = canopy_env.journal()
    now = datetime.now(UTC)
    old = earlier(now, 200)
    prs = [
        ("moved", "bbb", "open"),
        ("merged", "aaa", "merged"),
        ("closed", "aaa", "closed"),
        ("at-head", "aaa", "open"),
        ("no-head", None, "open"),
    ]
    for name, head, state in prs:
        conn.execute(
            "INSERT INTO observed_prs (url, repository, number, head_sha, state, draft, observed_at) "
            "VALUES (?, 'o/r', 1, ?, ?, 0, ?)",
            (f"https://x/{name}", head, state, old),
        )
    runs = [(*(f"https://x/{name}" for name, _, _ in prs), "https://x/unread"), ("https://x/moved", "https://x/merged")]
    for run_id, (pr, observed_at) in enumerate([*((pr, old) for pr in runs[0]), *((pr, db.now()) for pr in runs[1])]):
        conn.execute(
            "INSERT INTO observed_check_runs (pr_url, run_id, name, head_sha, conclusion, observed_at) "
            "VALUES (?, ?, 'ci', 'aaa', 'failure', ?)",
            (pr, run_id, observed_at),
        )
    conn.commit()
    kinds = dry_run(capsys)
    # The old runs of the moved, merged, and closed PRs go; one at its PR's head, one of a PR read with no head, one of
    # a PR no read recorded, and the recent ones stay.
    assert (kinds["check runs"]["count"], kinds["check runs"]["removable"]) == (8, 3)


@pytest.mark.parametrize("env", [conversation.TICK_ID_ENV, conversation.RUN_ID_ENV])
@pytest.mark.parametrize("flag", ["--dry-run", "--vacuum", "--git", "--caches"])
def test_an_agent_cannot_run_gc(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    env: str,
    flag: str,
) -> None:
    with mock.patch.dict(os.environ, {env: "3"}):
        assert main(["gc", flag]) == 1
    assert "gc refused (inside_run)" in capsys.readouterr().err


@pytest.mark.parametrize("flags", [[], ["--dry-run", "--vacuum"], ["--vacuum", "--git"], ["--git", "--caches"]])
def test_gc_takes_one_of_dry_run_vacuum_git_and_caches(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
) -> None:
    assert main(["gc", *flags]) == 2
    assert "give one of `--dry-run`, `--vacuum`, `--git`, and `--caches`" in capsys.readouterr().err


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
