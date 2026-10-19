"""How the loop's runs ended, and what its guards refused (DESIGN §11): `canopy health` over a journal by hand."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import health
from tests.canopy.helpers import earlier
from tests.conftest import CanopyEnv, Journals

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def tick(
    conn: sqlite3.Connection,
    started: str,
    status: str,
    *,
    summary: str = "",
    cost: float | None = None,
    dry: bool = False,
) -> int:
    cursor = conn.execute(
        "INSERT INTO ticks (started_at, ended_at, dry_run, status, summary, cost_usd) VALUES (?, ?, ?, ?, ?, ?)",
        (started, started, int(dry), status, summary, cost),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def journal_of_failures(conn: sqlite3.Connection, now: datetime) -> None:
    """A week of ticks and runs, some failed, one of each before the window, and refusals."""
    before = tick(conn, earlier(now, 9), "overseer_failed", summary="before the window")
    tick(conn, earlier(now, 2), "ok", cost=1.0)
    tick(conn, earlier(now, 2, 1), "ok", cost=0.5)
    failed = tick(conn, earlier(now, 1), "overseer_failed", summary="overseer exited 1:\n no done line", cost=0.25)
    tick(conn, earlier(now, 1, 1), "ok", dry=True, cost=0.1)
    tick(conn, earlier(now, 0), "running")
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at) VALUES ('PROJ-1', 'ws', ?, ?)",
        (earlier(now, 9),) * 2,
    )
    for started, kind, status, result, cost in (
        (earlier(now, 9), "implement", "crashed", None, 9.0),  # before the window
        (earlier(now, 2), "implement", "done", '{"status": "done", "summary": "did it"}', 2.0),
        (earlier(now, 1), "implement", "timeout", None, 3.0),
        (
            earlier(now, 0, 1),
            "fix-ci",
            "unpushed",
            '{"status": "done", "summary": "s", "harness": "nothing pushed"}',
            1.0,
        ),
        (earlier(now, 0, 2), "implement", "blocked", '{"status": "blocked", "summary": "asked"}', 0.5),
        (earlier(now, 0), "resume", "running", None, None),
    ):
        conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, status, result_json, log_path, cost_usd) "
            "VALUES (?, 'PROJ-1', ?, 'agent/PROJ-1', ?, ?, ?, 'l', ?)",
            (before, kind, started, status, result, cost),
        )
    for started, status, result in (
        (earlier(now, 1, 2), "ok", '{"status": "ok"}'),
        (earlier(now, 0, 3), "failed", "x" * 5),
    ):
        conn.execute(
            "INSERT INTO chore_runs (tick_id, chore, started_at, status, result_json, log_path) "
            "VALUES (NULL, 'deps', ?, ?, ?, 'l')",
            (started, status, result),
        )
    conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, started_at, status, result_json, log_path) "
        "VALUES (?, 'https://e.test/pr/7', 'abc', ?, 'crashed', ?, 'l')",
        (before, earlier(now, 0, 4), json.dumps({"summary": "y " * 400})),
    )
    for tick_id, action, created in (
        (failed, "refused:capacity", earlier(now, 1)),
        (failed, "refused:capacity", earlier(now, 1)),
        (failed + 1, "refused:capacity", earlier(now, 1, 1)),
        (failed, "refused:cooldown", earlier(now, 1)),
        (before, "refused:cooldown", earlier(now, 9)),  # before the window
        (failed, "dispatch:implement", earlier(now, 1)),
    ):
        conn.execute(
            "INSERT INTO decisions (tick_id, ticket_key, action, rationale, created_at) "
            "VALUES (?, 'PROJ-1', ?, 'r', ?)",
            (tick_id, action, created),
        )


def test_runs_are_by_kind_sort_and_status_with_their_cost(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_failures(conn, NOW)
    found = health.report(conn, NOW, 7)
    assert (found.since, found.until, found.days) == ("2026-10-02T00:00:00.000Z", "2026-10-09T00:00:00.000Z", 7)
    # Nothing before the window, and nothing still running.
    assert found.outcomes == (
        health.Outcome("overseer", "dry run", "ok", failed=False, runs=1, cost_usd=0.1),
        health.Outcome("overseer", "live", "ok", failed=False, runs=2, cost_usd=1.5),
        health.Outcome("overseer", "live", "overseer_failed", failed=True, runs=1, cost_usd=0.25),
        health.Outcome("workers", "fix-ci", "unpushed", failed=True, runs=1, cost_usd=1.0),
        # A worker that asked a question did what it was started for.
        health.Outcome("workers", "implement", "blocked", failed=False, runs=1, cost_usd=0.5),
        health.Outcome("workers", "implement", "done", failed=False, runs=1, cost_usd=2.0),
        health.Outcome("workers", "implement", "timeout", failed=True, runs=1, cost_usd=3.0),
        health.Outcome("chores", "deps", "failed", failed=True, runs=1, cost_usd=None),
        health.Outcome("chores", "deps", "ok", failed=False, runs=1, cost_usd=None),
        health.Outcome("reviews", "review", "crashed", failed=True, runs=1, cost_usd=None),
    )


def test_failures_are_the_newest_first_with_a_note_on_one_line(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_failures(conn, NOW)
    found = health.report(conn, NOW, 7)
    assert [(f.kind, f.what, f.status, f.subject) for f in found.failures] == [
        ("workers", "fix-ci", "unpushed", "PROJ-1"),
        ("chores", "deps", "failed", None),
        ("reviews", "review", "crashed", "https://e.test/pr/7"),
        ("workers", "implement", "timeout", "PROJ-1"),
        ("overseer", "live", "overseer_failed", None),
    ]
    notes = [f.note for f in found.failures]
    # The harness's note over the agent's summary; a result that is not JSON has none; a tick's summary on one line.
    assert notes[0] == "nothing pushed"
    assert notes[1] == ""
    assert len(notes[2]) == health.NOTE_LIMIT
    assert notes[2].endswith("y...")
    assert notes[4] == "overseer exited 1: no done line"


def test_failures_are_at_most_the_newest_few(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    for n in range(health.FAILURES + 5):
        tick(conn, earlier(NOW, 0, n / 10), "abandoned")
    found = health.report(conn, NOW, 1)
    assert len(found.failures) == health.FAILURES
    assert found.failures[0].started_at == earlier(NOW, 0)


def test_refusals_are_by_guard_the_most_first(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_failures(conn, NOW)
    found = health.report(conn, NOW, 7)
    first = found.failures[-1].id
    assert found.refusals == (
        health.Refusal("capacity", decisions=3, ticks=2, last_tick=first + 1),
        health.Refusal("cooldown", decisions=1, ticks=1, last_tick=first),
    )


def test_an_empty_window_has_nothing(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_failures(conn, NOW)
    found = health.report(conn, NOW - timedelta(days=30), 1)
    assert (found.outcomes, found.failures, found.refusals) == ((), (), ())


def test_canopy_health_prints_the_report(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    journal_of_failures(canopy_env.journal(), datetime.now(UTC))
    assert main(["health"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Runs over 7 days, since ")
    words = [line.split() for line in out]
    assert ["kind", "what", "status", "runs", "spent"] in words
    assert ["workers", "implement", "timeout", "!", "1", "$3.00"] in words
    assert ["chores", "deps", "ok", "1", "-"] in words
    assert "Newest failures (! above):" in out
    assert any("run:" in line and "fix-ci of PROJ-1  unpushed" in line for line in out)
    assert "    nothing pushed" in out
    assert any("chore:deps run " in line for line in out)
    assert any("review " in line and "of https://e.test/pr/7  crashed" in line for line in out)
    assert out[-3] == "Refused by a guard:"
    assert out[-2].startswith("  capacity: 3 times in 2 ticks, last in tick ")


def test_canopy_health_on_an_empty_journal(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["health", "--days", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1:] == ["", "No tick or run ended."]


def test_canopy_health_json_is_the_report(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    journal_of_failures(canopy_env.journal(), datetime.now(UTC))
    assert main(["health", "--json", "--days", "3"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["days"] == 3
    timeout = {"kind": "workers", "what": "implement", "status": "timeout", "failed": True, "runs": 1, "cost_usd": 3.0}
    assert timeout in data["outcomes"]
    assert data["failures"][0]["note"] == "nothing pushed"
    assert {k: v for k, v in data["refusals"][0].items() if k != "last_tick"} == {
        "guard": "capacity",
        "decisions": 3,
        "ticks": 2,
    }


def test_canopy_health_reads_at_most_a_year(canopy_env: CanopyEnv) -> None:
    assert main(["health", "--days", "0"]) == 2
    assert main(["health", "--days", "367"]) == 2
