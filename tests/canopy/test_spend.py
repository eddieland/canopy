"""What agent runs cost, by what they bought (DESIGN §11, ROADMAP M33): `canopy spend` over a journal by hand."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db, spend
from tests.conftest import CanopyEnv, Journals

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def noon_today() -> datetime:
    """Today at noon UTC, so a journal written around it has the same UTC days whenever the test runs."""
    return datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)


def at(now: datetime, days: float, hours: float = 0) -> str:
    return db.format_time(now - timedelta(days=days, hours=hours))


def tick(
    conn: sqlite3.Connection,
    started: str,
    cost: float | None,
    *,
    status: str = "ok",
    dry_run: bool = False,
    idle: bool | None = None,
    woken_by: str | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO ticks (started_at, ended_at, dry_run, status, idle, woken_by, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (started, started, int(dry_run), status, None if idle is None else int(idle), woken_by, cost),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def journal_of_a_week(conn: sqlite3.Connection, now: datetime) -> None:
    """Three days of ticks and runs, one before the window, and one run of each kind that reported no cost."""
    first = tick(conn, at(now, 9), 5.0, idle=False, woken_by="start")  # before a week
    tick(conn, at(now, 2), 1.0, idle=False, woken_by="start")
    tick(conn, at(now, 2, 1), 0.25, idle=True, woken_by="timer")
    tick(conn, at(now, 1), 0.25, idle=True, woken_by="timer")
    tick(conn, at(now, 1, 1), 0.5, idle=False, woken_by="message")
    tick(conn, at(now, 1, 2), None, idle=True, woken_by="timer")  # reported nothing
    tick(conn, at(now, 1, 3), 0.1, status="overseer_failed", woken_by="gate")
    tick(conn, at(now, 0, 1), 0.4)  # by hand: the loop did not run it
    tick(conn, at(now, 0, 2), 0.3, dry_run=True, idle=True, woken_by="timer")  # a dry loop's
    tick(conn, at(now, 0), None, status="running", woken_by="timer")
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at) VALUES ('PROJ-1', 'ws', ?, ?)",
        (at(now, 9), at(now, 9)),
    )
    for started, cost, status in ((at(now, 9), 7.0, "done"), (at(now, 2), 2.0, "done"), (at(now, 1), None, "failed")):
        conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, status, log_path, cost_usd) "
            "VALUES (?, 'PROJ-1', 'implement', 'agent/PROJ-1', ?, ?, 'l', ?)",
            (first, started, status, cost),
        )
    conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, status, log_path) "
        "VALUES (?, 'PROJ-1', 'fix-ci', 'agent/PROJ-1', ?, 'running', 'l')",
        (first, at(now, 0)),
    )
    for started, cost in ((at(now, 1), 0.75), (at(now, 0), None)):
        conn.execute(
            "INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path, cost_usd) "
            "VALUES (NULL, 'deps', ?, 'ok', 'l', ?)",
            (started, cost),
        )
    conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, started_at, status, log_path, cost_usd) "
        "VALUES (?, 'https://e.test/pr/7', 'abc', ?, 'done', 'l', 1.5)",
        (first, at(now, 0)),
    )


def test_the_window_is_whole_utc_days_ending_today() -> None:
    assert spend.window_start(NOW, 1) == datetime(2026, 10, 8, tzinfo=UTC)
    assert spend.window_start(NOW, 7) == datetime(2026, 10, 2, tzinfo=UTC)
    # A moment in another zone is read in UTC.
    late = datetime(2026, 10, 8, 23, 30, tzinfo=UTC).astimezone()
    assert spend.window_start(late, 1) == datetime(2026, 10, 8, tzinfo=UTC)


def test_a_week_is_split_by_day_by_kind_and_by_what_its_ticks_bought(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_a_week(conn, NOW)
    found = spend.breakdown(conn, NOW, 7)

    assert (found.since, found.days) == ("2026-10-02T00:00:00.000Z", 7)
    assert [d.day for d in found.per_day] == [f"2026-10-0{n}" for n in range(2, 9)]
    by_day = {d.day: d.costs for d in found.per_day}
    assert by_day["2026-10-02"] == spend.Costs()  # nothing that day: every cost None
    assert by_day["2026-10-02"].total is None
    two_days_ago = by_day["2026-10-06"]
    assert (two_days_ago.overseer, two_days_ago.idle, two_days_ago.workers) == (1.25, 0.25, 2.0)
    yesterday = by_day["2026-10-07"]
    # The failed tick's overseer counts; the tick that reported nothing adds nothing.
    assert (yesterday.overseer, yesterday.idle, yesterday.chores) == (pytest.approx(0.85), 0.25, 0.75)
    assert yesterday.workers is None  # its one run reported no cost
    today = by_day["2026-10-08"]
    assert (today.overseer, today.idle, today.dry_run, today.reviews) == (0.4, None, 0.3, 1.5)
    assert today.total == pytest.approx(2.2)  # a dry run's overseer counts in the total, as the web UI's counters do

    totals = found.totals
    assert (totals.overseer, totals.idle, totals.dry_run) == (pytest.approx(2.5), 0.5, 0.3)
    assert (totals.workers, totals.chores, totals.reviews) == (2.0, 0.75, 1.5)
    assert totals.total == pytest.approx(7.05)  # nothing from before the window

    groups = {g.group: (g.ticks, g.cost_usd) for g in found.ticks}
    assert [g.group for g in found.ticks] == list(spend.GROUPS)
    assert groups == {
        "idle": (3, 0.5),
        "busy": (2, 1.5),
        "hand_run": (1, 0.4),
        "not_ok": (1, 0.1),
        "dry_run": (1, 0.3),  # dry first, whatever the loop said of it
    }
    assert found.idle_share == pytest.approx(0.5 / 2.5)
    # The live ticks the loop ran, the running one not yet in any count.
    assert [(w.by, w.ticks, w.cost_usd) for w in found.woken] == [
        ("timer", 3, 0.5),
        ("gate", 1, 0.1),
        ("message", 1, 0.5),
        ("start", 1, 1.0),
    ]
    assert [(u.kind, u.runs, u.unpriced) for u in found.unpriced] == [
        ("overseer", 8, 1),
        ("workers", 2, 1),  # the running fix-ci is not counted yet
        ("chores", 2, 1),
        ("reviews", 1, 0),
    ]


def test_an_empty_journal_lists_each_day_with_nothing_spent(canopy_env: CanopyEnv) -> None:
    found = spend.breakdown(canopy_env.journal(), NOW, 3)
    assert [d.day for d in found.per_day] == ["2026-10-06", "2026-10-07", "2026-10-08"]
    assert found.totals == spend.Costs()
    assert found.idle_share is None
    assert [g.ticks for g in found.ticks] == [0] * len(spend.GROUPS)
    assert found.woken == []


def test_idle_ticks_are_the_newest_live_idle_ones_in_the_window(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    journal_of_a_week(conn, NOW)
    rows = spend.idle_ticks(conn, db.format_time(spend.window_start(NOW, 7)))
    assert [(r["started_at"], r["cost_usd"]) for r in rows] == [
        (at(NOW, 1, 2), None),
        (at(NOW, 1), 0.25),
        (at(NOW, 2, 1), 0.25),
    ]
    assert spend.idle_ticks(conn, db.format_time(spend.window_start(NOW, 1))) == []  # today's one idle tick is dry


def test_canopy_spend_prints_the_breakdown(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    now = noon_today()
    journal_of_a_week(canopy_env.journal(), now)
    assert main(["spend", "--days", "3"]) == 0
    out = capsys.readouterr().out.splitlines()
    start = spend.window_start(now, 3).strftime("%Y-%m-%d")
    assert out[0] == f"Spend over 3 days, since {start} UTC, as the runtime reported it."
    assert out[2].split() == ["day", "overseer", "idle", "workers", "chores", "reviews", "dry", "run", "total"]
    assert len([line for line in out if line[:4] == start[:4]]) == 3  # a line per day
    assert out[6].split() == ["all", "$2.50", "$0.50", "$2.00", "$0.75", "$1.50", "$0.30", "$7.05"]
    words = [line.split() for line in out]
    assert ["idle", "3", "$0.50"] in words
    assert ["not", "idle", "2", "$1.50"] in words
    assert "Idle ticks were 20% of the live overseer's spend." in out
    assert ["timer", "3", "$0.50"] in words
    assert out[-1] == (
        "No cost reported: 1 of 8 overseer runs, 1 of 2 worker and split runs, 1 of 2 chore runs, 0 of 1 review runs."
    )


def test_canopy_spend_json_is_the_breakdown_with_each_total(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_of_a_week(canopy_env.journal(), noon_today())
    assert main(["spend", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["days"] == spend.DEFAULT_DAYS
    assert len(data["per_day"]) == spend.DEFAULT_DAYS
    assert data["totals"]["total"] == pytest.approx(7.05)
    assert data["per_day"][0]["costs"]["total"] is None
    assert data["idle_share"] == pytest.approx(0.2)
    assert data["ticks"][0] == {"group": "idle", "ticks": 3, "cost_usd": 0.5}


def test_canopy_spend_reads_at_most_a_year(canopy_env: CanopyEnv) -> None:
    assert main(["spend", "--days", "0"]) == 2
    assert main(["spend", "--days", str(spend.MAX_DAYS + 1)]) == 2
    assert main(["spend", "--days", str(spend.MAX_DAYS)]) == 0
