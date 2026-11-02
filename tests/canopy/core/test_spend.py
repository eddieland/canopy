"""What agent runs cost, by what they bought (DESIGN §11, ROADMAP M33): `canopy spend` over a journal by hand."""

import dataclasses
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from canopy.cli.main import main
from canopy.core import db, run_models, runtime_sessions, spend, sql
from canopy.core.run_models import Due, RunTable
from canopy.core.vocab import ModelsRead
from canopy.runtime.report import ModelUse, SessionPage, SessionSpend, ToolUse, Usage
from tests.canopy.helpers import earlier, in_zone
from tests.conftest import CanopyEnv, Journals

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
#: A workspace state directory no session in these journals ran in.
STATE_DIR = Path("/work/.canopy")


def noon_today() -> datetime:
    """Today at noon UTC, so a journal written around it has the same days whenever the test runs: local time is UTC."""
    return datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)


def tick(
    conn: sqlite3.Connection,
    started: str,
    cost: float | None,
    *,
    status: str = "ok",
    dry_run: bool = False,
    idle: bool | None = None,
    woken_by: str | None = None,
    overseer_ran: bool | None = None,
) -> int:
    ran = None if overseer_ran is None else int(overseer_ran)
    cursor = conn.execute(
        "INSERT INTO ticks (started_at, ended_at, dry_run, status, idle, woken_by, cost_usd, overseer_ran) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (started, started, int(dry_run), status, None if idle is None else int(idle), woken_by, cost, ran),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def journal_of_a_week(conn: sqlite3.Connection, now: datetime) -> None:
    """Three days of ticks and runs, one before the window, and one run of each kind that reported no cost."""
    first = tick(conn, earlier(now, 9), 5.0, idle=False, woken_by="start")  # before a week
    tick(conn, earlier(now, 2), 1.0, idle=False, woken_by="start")
    tick(conn, earlier(now, 2, 1), 0.25, idle=True, woken_by="timer")
    tick(conn, earlier(now, 1), 0.25, idle=True, woken_by="timer")
    tick(conn, earlier(now, 1, 1), 0.5, idle=False, woken_by="message")
    tick(conn, earlier(now, 1, 2), None, idle=True, woken_by="timer")  # reported nothing
    tick(conn, earlier(now, 1, 3), 0.1, status="overseer_failed", woken_by="gate")
    tick(conn, earlier(now, 0, 1), 0.4)  # by hand: the loop did not run it
    tick(conn, earlier(now, 0, 2), 0.3, dry_run=True, idle=True, woken_by="timer")  # a dry loop's
    tick(conn, earlier(now, 0), None, status="running", woken_by="timer")
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at) VALUES ('PROJ-1', 'ws', ?, ?)",
        (earlier(now, 9), earlier(now, 9)),
    )
    for started, cost, status in (
        (earlier(now, 9), 7.0, "done"),
        (earlier(now, 2), 2.0, "done"),
        (earlier(now, 1), None, "failed"),
    ):
        conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, status, log_path, cost_usd) "
            "VALUES (?, 'PROJ-1', 'implement', 'agent/PROJ-1', ?, ?, 'l', ?)",
            (first, started, status, cost),
        )
    conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, status, log_path) "
        "VALUES (?, 'PROJ-1', 'fix-ci', 'agent/PROJ-1', ?, 'running', 'l')",
        (first, earlier(now, 0)),
    )
    for started, cost in ((earlier(now, 1), 0.75), (earlier(now, 0), None)):
        conn.execute(
            "INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path, cost_usd) "
            "VALUES (NULL, 'deps', ?, 'ok', 'l', ?)",
            (started, cost),
        )
    conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, started_at, status, log_path, cost_usd) "
        "VALUES (?, 'https://e.test/pr/7', 'abc', ?, 'done', 'l', 1.5)",
        (first, earlier(now, 0)),
    )


def ticket(conn: sqlite3.Connection, key: str, *, title: str | None = None, done: bool = False) -> None:
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, title, done) VALUES (?, 'ws', ?, ?, ?, ?)",
        (key, earlier(NOW, 30), earlier(NOW, 30), title, int(done)),
    )


def run(
    conn: sqlite3.Connection,
    tick_id: int,
    key: str,
    started: str,
    cost: float | None,
    prs: dict[str, str] | None,
) -> None:
    conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, status, result_json, log_path, cost_usd) "
        "VALUES (?, ?, 'implement', 'b', ?, 'done', ?, 'l', ?)",
        (tick_id, key, started, None if prs is None else json.dumps({"status": "done", "prs": prs}), cost),
    )


def review(conn: sqlite3.Connection, tick_id: int, url: str, key: str | None, started: str, cost: float) -> None:
    conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, ticket_key, started_at, status, log_path, cost_usd) "
        "VALUES (?, ?, 'abc', ?, ?, 'done', 'l', ?)",
        (tick_id, url, key, started, cost),
    )


def decide(conn: sqlite3.Connection, tick_id: int, key: str, created: str, action: str, rationale: str) -> None:
    conn.execute(
        "INSERT INTO decisions (tick_id, ticket_key, action, rationale, created_at) VALUES (?, ?, ?, ?, ?)",
        (tick_id, key, action, rationale, created),
    )


def test_the_window_is_whole_local_days_ending_today() -> None:
    assert spend.window(NOW, 1) == (datetime(2026, 10, 8, tzinfo=UTC), datetime(2026, 10, 9, tzinfo=UTC))
    assert spend.window(NOW, 7)[0] == datetime(2026, 10, 2, tzinfo=UTC)
    # A moment in another zone is read in local time.
    late = datetime(2026, 10, 8, 23, 30, tzinfo=UTC).astimezone(ZoneInfo("Asia/Tokyo"))
    assert spend.window(late, 1)[0] == datetime(2026, 10, 8, tzinfo=UTC)
    with in_zone("Asia/Tokyo"):
        assert spend.window(NOW, 1) == (datetime(2026, 10, 7, 15, tzinfo=UTC), datetime(2026, 10, 8, 15, tzinfo=UTC))


def test_a_day_a_clock_change_lengthens_is_still_one_day() -> None:
    with in_zone("America/Los_Angeles"):
        start, until = spend.window(datetime(2026, 11, 1, 20, tzinfo=UTC), 1)
    # Clocks went back at 02:00 on 2026-11-01: from midnight PDT to midnight PST is 25 hours.
    assert (start, until) == (datetime(2026, 11, 1, 7, tzinfo=UTC), datetime(2026, 11, 2, 8, tzinfo=UTC))


def test_a_run_counts_on_the_local_day_it_started(tmp_path: Path, journals: Journals) -> None:
    """An evening's runs in Los Angeles, past midnight UTC, are today's there, not tomorrow's."""
    conn = journals.open(tmp_path / "canopy.db")
    evening = datetime(2026, 10, 9, 3, tzinfo=UTC)  # 20:00 PDT on 2026-10-08
    morning = datetime(2026, 10, 8, 16, tzinfo=UTC)  # 09:00 PDT on 2026-10-08
    for at in (evening, morning):
        tick(conn, db.format_time(at), 1.0, idle=False, woken_by="start")
        conn.execute(
            "INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path, cost_usd) "
            "VALUES (NULL, 'deps', ?, 'ok', 'l', 0.5)",
            (db.format_time(at),),
        )
    with in_zone("America/Los_Angeles"):
        found = spend.breakdown(conn, evening, 2, state_dir=STATE_DIR)
    assert [(d.day, d.costs.overseer, d.costs.chores) for d in found.per_day] == [
        ("2026-10-07", None, None),
        ("2026-10-08", 2.0, 1.0),
    ]
    assert (found.since, found.until) == ("2026-10-07T07:00:00.000Z", "2026-10-09T07:00:00.000Z")


def test_a_window_in_hours_is_whole_clock_hours_ending_with_this_one(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    now = datetime(2026, 10, 8, 12, 30, tzinfo=UTC)
    tick(conn, earlier(now, 1), 5.0, idle=False, woken_by="start")  # 12:30 yesterday: before the first hour
    tick(conn, earlier(now, 0, 23), 1.0, idle=False, woken_by="start")  # 13:30 yesterday, in the first hour
    tick(conn, earlier(now, 0, 0.25), 0.5, idle=True, woken_by="timer")  # 12:15, this hour so far
    conn.execute(
        "INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path, cost_usd) "
        "VALUES (NULL, 'deps', ?, 'ok', 'l', 0.75)",
        (earlier(now, 0, 2),),
    )
    found = spend.breakdown_hours(conn, now, 24, state_dir=STATE_DIR)

    assert (found.since, found.until) == ("2026-10-07T13:00:00.000Z", "2026-10-08T13:00:00.000Z")
    assert (found.days, found.hours) == (None, 24)
    assert len(found.per_day) == 24
    assert (found.per_day[0].day, found.per_day[-1].day) == ("2026-10-07T13", "2026-10-08T12")
    assert (found.per_day[0].start, found.per_day[-1].start) == (found.since, "2026-10-08T12:00:00.000Z")
    by_hour = {d.day: d.costs for d in found.per_day}
    assert by_hour["2026-10-07T13"].overseer == 1.0
    assert (by_hour["2026-10-08T12"].overseer, by_hour["2026-10-08T12"].idle) == (0.5, 0.5)
    assert by_hour["2026-10-08T10"].chores == 0.75
    assert by_hour["2026-10-08T11"] == spend.Costs()
    assert found.totals.total == pytest.approx(2.25)
    assert [(w.by, w.ticks) for w in found.woken] == [("start", 1), ("timer", 1)]


def test_a_window_in_hours_is_whole_local_hours_in_a_zone_a_half_hour_off_utc(
    tmp_path: Path,
    journals: Journals,
) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    now = datetime(2026, 10, 8, 12, 15, tzinfo=UTC)  # 17:45 in Kolkata, UTC+5:30
    # 18:15 there yesterday, in the first hour; 18:10 there the day before, outside the window.
    tick(conn, db.format_time(datetime(2026, 10, 7, 12, 45, tzinfo=UTC)), 1.0, idle=False, woken_by="start")
    tick(conn, db.format_time(datetime(2026, 10, 6, 12, 40, tzinfo=UTC)), 5.0, idle=False, woken_by="start")
    with in_zone("Asia/Kolkata"):
        found = spend.breakdown_hours(conn, now, 24, state_dir=STATE_DIR)
    assert (found.since, found.until) == ("2026-10-07T12:30:00.000Z", "2026-10-08T12:30:00.000Z")
    assert (found.per_day[0].day, found.per_day[-1].day) == ("2026-10-07T18", "2026-10-08T17")
    assert found.per_day[0].start == "2026-10-07T12:30:00.000Z"
    assert found.per_day[0].costs.overseer == 1.0
    assert found.totals.total == 1.0


def test_an_hour_the_clock_goes_back_over_is_listed_once(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    # Clocks went back at 02:00 PDT on 2026-11-01: 08:30 UTC and 09:30 UTC are both 01:30 there.
    for at in (datetime(2026, 11, 1, 8, 30, tzinfo=UTC), datetime(2026, 11, 1, 9, 30, tzinfo=UTC)):
        tick(conn, db.format_time(at), 1.0, idle=False, woken_by="start")
    with in_zone("America/Los_Angeles"):
        found = spend.breakdown_hours(conn, datetime(2026, 11, 1, 20, tzinfo=UTC), 24, state_dir=STATE_DIR)
    names = [d.day for d in found.per_day]
    assert len(names) == 23
    assert len(set(names)) == len(names)
    assert {d.day: d.costs.overseer for d in found.per_day}["2026-11-01T01"] == 2.0
    # The hour starts the first time the clock reads 01:00, in daylight time.
    assert {d.day: d.start for d in found.per_day}["2026-11-01T01"] == "2026-11-01T08:00:00.000Z"


def test_a_week_is_split_by_day_by_kind_and_by_what_its_ticks_bought(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_a_week(conn, NOW)
    found = spend.breakdown(conn, NOW, 7, state_dir=STATE_DIR)

    assert (found.since, found.until, found.days) == ("2026-10-02T00:00:00.000Z", "2026-10-09T00:00:00.000Z", 7)
    assert [d.day for d in found.per_day] == [f"2026-10-0{n}" for n in range(2, 9)]
    assert [d.start for d in found.per_day] == [f"2026-10-0{n}T00:00:00.000Z" for n in range(2, 9)]
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
        ("plans", 0, 0),
        ("chores", 2, 1),
        ("reviews", 1, 0),
        ("tasks", 0, 0),
    ]


def test_an_empty_journal_lists_each_day_with_nothing_spent(canopy_env: CanopyEnv) -> None:
    found = spend.breakdown(canopy_env.journal(), NOW, 3, state_dir=STATE_DIR)
    assert [d.day for d in found.per_day] == ["2026-10-06", "2026-10-07", "2026-10-08"]
    assert found.totals == spend.Costs()
    assert found.idle_share is None
    assert [g.ticks for g in found.ticks] == [0] * len(spend.GROUPS)
    assert found.woken == []


def test_idle_ticks_are_the_newest_live_idle_ones_in_the_window(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    journal_of_a_week(conn, NOW)
    week = spend.breakdown(conn, NOW, 7, state_dir=STATE_DIR)
    rows = spend.idle_ticks(conn, week.since, week.until)
    assert [(r.started_at, r.cost_usd) for r, _ in rows] == [
        (earlier(NOW, 1, 2), None),
        (earlier(NOW, 1), 0.25),
        (earlier(NOW, 2, 1), 0.25),
    ]
    today = spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR)
    assert spend.idle_ticks(conn, today.since, today.until) == []  # today's one idle tick is dry


def test_canopy_spend_prints_the_breakdown(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    now = noon_today()
    journal_of_a_week(canopy_env.journal(), now)
    assert main(["spend", "--days", "3"]) == 0
    out = capsys.readouterr().out.splitlines()
    start = spend.window(now, 3)[0]
    assert out[0] == f"Spend over 3 days, since {start:%Y-%m-%d} UTC, as the runtime reported it."
    header = [
        "day",
        "overseer",
        "idle",
        "workers",
        "plans",
        "chores",
        "reviews",
        "tasks",
        "dry",
        "run",
        "outside",
        "total",
    ]
    assert out[2].split() == header
    days = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
    assert [line.split()[0] for line in out[3:6]] == days  # a line per day, oldest first
    assert out[6].split() == ["all", "$2.50", "$0.50", "$2.00", "-", "$0.75", "$1.50", "-", "$0.30", "-", "$7.05"]
    words = [line.split() for line in out]
    assert ["ticks", "count", "spent", "no", "overseer"] in words
    assert ["idle", "3", "$0.50", "0"] in words
    assert ["not", "idle", "2", "$1.50", "0"] in words
    assert "Idle ticks were 20% of the live overseer's spend." in out
    assert ["woken", "by", "count", "spent", "no", "overseer"] in words
    assert ["timer", "3", "$0.50", "0"] in words
    # A kind whose every run reported a cost is left out.
    assert out[-1] == "No cost reported: 1 of 8 overseer runs, 1 of 2 worker runs, 1 of 2 chore runs."


def test_canopy_spend_json_is_the_breakdown_with_each_total(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    journal_of_a_week(canopy_env.journal(), noon_today())
    assert main(["spend", "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    # A value to a line, so an agent's file tools, which cut a long line, read all of a report too long to print whole.
    assert all(line.count('": ') <= 1 for line in out.splitlines())
    assert data["days"] == spend.DEFAULT_DAYS
    assert len(data["per_day"]) == spend.DEFAULT_DAYS
    assert data["totals"]["total"] == pytest.approx(7.05)
    assert data["per_day"][0]["costs"]["total"] is None
    assert data["idle_share"] == pytest.approx(0.2)
    assert data["ticks"][0] == {"group": "idle", "ticks": 3, "cost_usd": 0.5, "without_overseer": 0}


def test_a_tick_that_ran_no_overseer_counts_at_nothing_and_is_split_from_those_that_did(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Two idle ticks the timer woke: one ran the overseer for a quarter, one the harness left it nothing (DESIGN §39).
    conn = canopy_env.journal()
    now = noon_today()
    tick(conn, earlier(now, 0, 2), 0.25, idle=True, woken_by="timer", overseer_ran=True)
    tick(conn, earlier(now, 0, 1), None, idle=True, woken_by="timer", overseer_ran=False)
    tick(conn, earlier(now, 0, 3), None, idle=True, woken_by="run", overseer_ran=False)
    found = spend.breakdown(conn, now, 1, state_dir=STATE_DIR)
    [idle] = [g for g in found.ticks if g.group == "idle"]
    assert (idle.ticks, idle.cost_usd, idle.without_overseer) == (3, 0.25, 2)
    assert [(w.by, w.ticks, w.cost_usd, w.without_overseer) for w in found.woken] == [
        ("timer", 2, 0.25, 1),
        ("run", 1, 0.0, 1),
    ]
    # Never among the runs that reported no cost.
    [overseer] = [u for u in found.unpriced if u.kind == "overseer"]
    assert (overseer.runs, overseer.unpriced) == (3, 0)
    assert main(["spend", "--days", "1", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["woken"][1] == {"by": "run", "ticks": 1, "cost_usd": 0.0, "without_overseer": 1}
    assert data["unpriced"][0] == {"kind": "overseer", "runs": 3, "unpriced": 0}


def test_canopy_spend_reads_at_most_a_year(canopy_env: CanopyEnv) -> None:
    assert main(["spend", "--days", "0"]) == 2
    assert main(["spend", "--days", str(spend.MAX_DAYS + 1)]) == 2
    assert main(["spend", "--days", str(spend.MAX_DAYS)]) == 0


def test_a_running_dry_run_is_never_the_live_overseers(tmp_path: Path, journals: Journals) -> None:
    """A tick records its overseer's cost before it closes, so a dry run still acting is already priced."""
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, earlier(NOW, 0, 1), 0.5, status="running", dry_run=True)
    tick(conn, earlier(NOW, 0, 2), 0.25, status="running")
    found = spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR)
    assert (found.totals.dry_run, found.totals.overseer) == (0.5, 0.25)
    assert [g.ticks for g in found.ticks] == [0] * len(spend.GROUPS)  # neither has ended
    assert found.unpriced[0] == spend.Unpriced(kind="overseer", runs=0, unpriced=0)


def test_canopy_spend_says_when_every_run_reported_a_cost(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tick(canopy_env.journal(), earlier(noon_today(), 0), 0.25, idle=True, woken_by="timer")
    assert main(["spend", "--days", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Spend over 1 day, since ")
    assert out[-1] == "Every run that ended reported a cost."


def test_a_row_after_the_window_is_in_no_figure(tmp_path: Path, journals: Journals) -> None:
    """A clock behind the journal's puts a row after today: it is in no day, no total, and no count."""
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, db.format_time(NOW + timedelta(days=1)), 9.0, idle=True, woken_by="timer")
    tick(conn, earlier(NOW, 0), 1.0, idle=False, woken_by="start")
    found = spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR)
    assert (found.totals.overseer, found.totals.idle) == (1.0, None)
    assert [(g.group, g.ticks) for g in found.ticks if g.ticks] == [("busy", 1)]
    assert [w.by for w in found.woken] == ["start"]
    assert found.unpriced[0].runs == 1
    assert spend.idle_ticks(conn, found.since, found.until) == []


def test_costs_sum_each_kind_that_started_in_any_span(tmp_path: Path, journals: Journals) -> None:
    """A digest's span is from its last one to now, whole days or not: a row on either side of it is in no figure."""
    conn = journals.open(tmp_path / "canopy.db")
    since, until = db.format_time(NOW - timedelta(hours=1)), db.format_time(NOW)
    tick(conn, db.format_time(NOW - timedelta(hours=2)), 8.0)
    tick(conn, db.format_time(NOW + timedelta(minutes=1)), 8.0)
    ticket(conn, "A-1")
    tick_id = tick(conn, earlier(NOW, 0, 0.5), 1.0, idle=False)
    tick(conn, earlier(NOW, 0, 0.25), 0.25, idle=True)
    tick(conn, earlier(NOW, 0, 0.1), 0.5, dry_run=True)
    run(conn, tick_id, "A-1", earlier(NOW, 0, 0.5), 2.0, None)
    review(conn, tick_id, "https://example.test/pr/1", "A-1", earlier(NOW, 0, 0.5), 0.75)
    found = spend.costs(conn, since, until, state_dir=STATE_DIR)
    assert found == spend.Costs(overseer=1.25, idle=0.25, dry_run=0.5, workers=2.0, reviews=0.75)
    assert found.total == 4.5
    assert spend.costs(conn, until, db.format_time(NOW + timedelta(seconds=1)), state_dir=STATE_DIR) == spend.Costs()


def test_idle_share_is_of_the_live_ticks_that_ended(tmp_path: Path, journals: Journals) -> None:
    """A running tick has reported its cost and is in no group yet, so it is in neither part of the share."""
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, earlier(NOW, 0, 2), 0.25, idle=True, woken_by="timer")
    tick(conn, earlier(NOW, 0, 1), 0.75, idle=False, woken_by="message")
    tick(conn, earlier(NOW, 0), 2.0, status="running")
    found = spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR)
    assert found.totals.overseer == 3.0  # the running tick's cost counts, as the rail's counters count it
    assert found.idle_share == 0.25


def test_what_each_ticket_and_pr_cost_and_what_the_window_got_done(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    t = tick(conn, earlier(NOW, 1), 4.0, idle=False, woken_by="start")
    web, api, other = "https://e.test/web/pull/1", "https://e.test/api/pull/2", "https://e.test/x/pull/9"
    ticket(conn, "A-1", title="Merged", done=True)
    ticket(conn, "A-2", title="Closed in the tracker", done=True)
    ticket(conn, "A-3")  # still open
    ticket(conn, "A-4", done=True)  # done the week before, its last run in the window
    ticket(conn, "A-5", done=True)  # done in the window, no run in it
    conn.execute(
        "INSERT INTO ticket_units (ticket_key, repo, pr_url, phase) VALUES ('A-1', 'web', ?, 'merged')",
        (web,),
    )
    run(conn, t, "A-1", earlier(NOW, 2), 3.0, {"web": web, "api": api})  # a joint run: on each PR, once on its ticket
    run(conn, t, "A-1", earlier(NOW, 9), 50.0, {"web": web})  # before the window
    run(conn, t, "A-2", earlier(NOW, 1), 1.0, None)
    run(conn, t, "A-3", earlier(NOW, 0), 0.5, {"web": "not a url"})
    run(conn, t, "A-4", earlier(NOW, 3), None, None)
    review(conn, t, web, "A-1", earlier(NOW, 1), 0.25)
    review(conn, t, other, None, earlier(NOW, 0), 0.75)
    decide(conn, t, "A-1", earlier(NOW, 1), "done", "every PR merged")
    decide(conn, t, "A-2", earlier(NOW, 3), "done", "every PR merged")
    decide(conn, t, "A-2", earlier(NOW, 1), "done", db.CLOSED_RATIONALE)  # the newest says how
    decide(conn, t, "A-4", earlier(NOW, 8), "done", "every PR merged")
    decide(conn, t, "A-5", earlier(NOW, 0), "done", "every PR merged")
    found = spend.breakdown(conn, NOW, 7, state_dir=STATE_DIR)

    assert found.done == 3
    assert [d.done for d in found.per_day] == [0, 0, 0, 0, 0, 2, 1]
    assert found.totals.total == pytest.approx(9.5)
    assert found.per_done == pytest.approx(9.5 / 3)  # the window's whole spend, the overseer's included
    assert found.tickets == [
        spend.TicketSpend("A-1", "Merged", 1, 1, 3.25, "merged", earlier(NOW, 1)),
        spend.TicketSpend("A-2", "Closed in the tracker", 1, 0, 1.0, "closed", earlier(NOW, 1)),
        spend.TicketSpend("A-3", None, 1, 0, 0.5),
        spend.TicketSpend("A-4", None, 1, 0, None),  # done before the window: not done in it
        spend.TicketSpend("A-5", None, 0, 0, None, "merged", earlier(NOW, 0)),
    ]
    assert found.pull_requests == [
        spend.PullRequestSpend(web, "A-1", "merged", runs=1, reviews=1, cost_usd=3.25),
        spend.PullRequestSpend(api, "A-1", None, runs=1, reviews=0, cost_usd=3.0),
        spend.PullRequestSpend(other, None, None, runs=0, reviews=1, cost_usd=0.75),
    ]


def test_a_ticket_forgotten_or_reopened_since_it_was_done_is_not_done(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    t = tick(conn, earlier(NOW, 1), 1.0)
    ticket(conn, "A-1", done=True)
    ticket(conn, "A-2")  # reopened: no longer done
    decide(conn, t, "A-1", earlier(NOW, 1), "done", "every PR merged")
    decide(conn, t, "A-2", earlier(NOW, 1), "done", "every PR merged")
    conn.execute("UPDATE tickets SET forgotten_at = ? WHERE key = 'A-1'", (earlier(NOW, 0),))
    found = spend.breakdown(conn, NOW, 7, state_dir=STATE_DIR)
    assert (found.done, found.per_done, found.tickets) == (0, None, [])


def test_canopy_spend_prints_the_tickets_done_and_the_costliest(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = noon_today()
    conn = canopy_env.journal()
    t = tick(conn, earlier(now, 0), 1.0)
    for n in range(12):
        ticket(conn, f"A-{n}", done=n == 11)
        run(conn, t, f"A-{n}", earlier(now, 0), n + 1.0, None)
    decide(conn, t, "A-11", earlier(now, 0), "done", "every PR merged")
    assert main(["spend", "--days", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "1 ticket marked done, $79.00 of all spend for each." in out
    words = [line.split() for line in out]
    first = words.index(["ticket", "runs", "spent", "done"]) + 1
    assert words[first] == ["A-11", "1", "$12.00", earlier(now, 0)[:10], "merged"]
    assert [w[0] for w in words[first : first + 10]] == [f"A-{n}" for n in range(11, 1, -1)]  # the costliest ten
    assert words[first + 10] == ["and", "2", "more;", "--json", "lists", "every", "one"]


def triage(
    conn: sqlite3.Connection,
    tick_id: int,
    key: str,
    started: str,
    cost: float | None,
    status: str = "done",
) -> int:
    """An old triage before a plan (M55): a `runs` row of kind `needs-plan`, with no branch."""
    return branchless(conn, "needs-plan", tick_id, key, started, cost, status)


def plan_run(conn: sqlite3.Connection, tick_id: int, key: str, started: str, cost: float | None) -> int:
    """A plan run (DESIGN §25): a `runs` row of kind `plan`, with no branch."""
    return branchless(conn, "plan", tick_id, key, started, cost, "done")


def branchless(
    conn: sqlite3.Connection,
    kind: str,
    tick_id: int,
    key: str,
    started: str,
    cost: float | None,
    status: str,
) -> int:
    """A `runs` row of a kind that works on no branch."""
    cursor = conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, status, log_path, cost_usd) "
        "VALUES (?, ?, ?, '', ?, ?, 'l', ?)",
        (tick_id, key, kind, started, status, cost),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def test_plan_runs_are_a_kind_of_their_own_with_old_triages_among_them(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A triage before a plan (M55) was removed: its old runs count as plan runs, and no worker's."""
    now = noon_today()
    conn = canopy_env.journal()
    t = tick(conn, earlier(now, 0), 1.0)
    for key in ("A-1", "A-2", "A-3"):
        ticket(conn, key)
    run(conn, t, "A-1", earlier(now, 0), 2.0, None)
    triage(conn, t, "A-1", earlier(now, 0, 1), 0.05)
    triage(conn, t, "A-2", earlier(now, 0, 1), 0.04)
    plan_run(conn, t, "A-2", earlier(now, 0, 1), 0.5)
    triage(conn, t, "A-3", earlier(now, 0, 1), None, status="failed")

    found = spend.breakdown(conn, now, 1, state_dir=STATE_DIR)
    assert (found.totals.workers, found.totals.plans) == (2.0, pytest.approx(0.59))
    assert found.totals.total == pytest.approx(3.59)  # each dollar once, in its own kind
    assert [(u.kind, u.runs, u.unpriced) for u in found.unpriced][1:3] == [("workers", 1, 0), ("plans", 4, 1)]
    # A ticket's own runs are all of them, its old triage and its plan included.
    assert [(s.key, s.runs, s.cost_usd) for s in found.tickets if s.key in {"A-1", "A-2"}] == [
        ("A-1", 2, pytest.approx(2.05)),
        ("A-2", 2, pytest.approx(0.54)),
    ]

    assert main(["spend", "--days", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[3].split()[3:5] == ["$2.00", "$0.59"]  # workers, then plans
    assert out[-1] == "No cost reported: 1 of 4 plan runs."


def first_call(sent: int, written: int, read: int | None = None) -> Usage:
    """What a run reported whose first model call was sent `sent` tokens and wrote `written` of them to the cache.

    It read the rest from the cache, or `read` when given; it read nothing canopy kept with `read` 0 and a write.
    """
    read = sent - written if read is None else read
    return Usage(
        0.1,
        sent - written - read,
        0,
        0,
        read,
        written,
        peak_context=sent,
        first_call=sent,
        first_cache_write=written,
        first_cache_read=read,
    )


def unread_first_call(sent: int, written: int) -> Usage:
    """A first call recorded before canopy kept what it read from the cache."""
    return dataclasses.replace(first_call(sent, written), first_cache_read=None)


def test_first_calls_are_by_kind_and_snapshot_with_their_median_and_cold_share(
    tmp_path: Path,
    journals: Journals,
) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    calls = [(5, 50_000, 49_000, "old"), (4, 52_000, 3_000, "old"), (3, 51_000, 2_000, "old")]
    calls += [(2, 60_000, 58_000, "new"), (1, 62_000, 5_000, "new")]
    for hours, sent, written, digest in calls:
        db.set_tick_report(conn, tick(conn, earlier(NOW, 0, hours), 0.1), "s", first_call(sent, written), digest=digest)
    dry = tick(conn, earlier(NOW, 0, 0.5), 0.1, dry_run=True)  # its first call is a live tick's
    db.set_tick_report(conn, dry, "s", first_call(61_000, 4_000), digest="new")
    before = tick(conn, earlier(NOW, 1), 0.1)  # before the window
    db.set_tick_report(conn, before, "s", first_call(10, 10), digest="new")
    tick(conn, earlier(NOW, 0, 0.25), 0.1)  # recorded before canopy kept the first call
    ticket(conn, "PROJ-1")
    run(conn, dry, "PROJ-1", earlier(NOW, 0, 1), 0.1, None)
    run_id = conn.execute("SELECT max(id) FROM runs").fetchone()[0]
    db.set_run_report(conn, "runs", run_id, "s", first_call(30_000, 1_000), digest="new")

    found = spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR)
    assert [dataclasses.replace(f, hit_rate=None) for f in found.first_calls] == [
        spend.FirstCalls("overseer", "old", 3, 51_000, 1 / 3, earlier(NOW, 0, 5), earlier(NOW, 0, 3)),
        spend.FirstCalls("overseer", "new", 3, 61_000, 1 / 3, earlier(NOW, 0, 2), earlier(NOW, 0, 0.5)),
        spend.FirstCalls("workers", "new", 1, 30_000, 0.0, earlier(NOW, 0, 1), earlier(NOW, 0, 1)),
    ]
    # What each read from the cache over what each was sent, summed: the rest of what each did not write.
    old = (1_000 + 49_000 + 49_000) / (50_000 + 52_000 + 51_000)
    assert [f.hit_rate for f in found.first_calls] == [pytest.approx(old), pytest.approx(1 - 67_000 / 183_000), 29 / 30]


def test_first_calls_name_the_runtime_versions_their_runs_ran_on_in_order(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    for hours, version in ((4, "1.19.3"), (3, None), (2, "1.20.0"), (1, "1.19.3")):
        t = tick(conn, earlier(NOW, 0, hours), 0.1)
        db.set_tick_report(conn, t, "s", first_call(50_000, 1_000), digest="d")
        if version is not None:
            run_models.record(conn, Due("ticks", t, "s", 0), ModelsRead.FOUND, runtime_version=version)
    [overseer] = spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR).first_calls
    assert (overseer.runs, overseer.runtime_versions) == (4, ("1.19.3", "1.20.0"))


def test_a_first_call_that_read_little_from_the_cache_is_cold_though_it_wrote_nothing(
    tmp_path: Path,
    journals: Journals,
) -> None:
    """A provider that reports no cache writes, as OpenAI's, says a call was cold only by what it read (#1526)."""
    conn = journals.open(tmp_path / "canopy.db")
    ticket(conn, "PROJ-1")
    t = tick(conn, earlier(NOW, 0, 3), 0.1)
    for hours, read in ((3, 0), (2, 20_000), (1, 30_000)):
        review(conn, t, "https://e.test/pr/1", None, earlier(NOW, 0, hours), 0.1)
        review_id = int(conn.execute("SELECT max(id) FROM review_runs").fetchone()[0])
        db.set_run_report(conn, "review_runs", review_id, "s", first_call(50_000, 0, read), digest="d")
    # Those recorded before canopy kept the read are judged by their write, as before: cold when it was most of it.
    for hours, written in ((0.5, 0), (0.25, 40_000)):
        review(conn, t, "https://e.test/pr/1", None, earlier(NOW, 0, hours), 0.1)
        review_id = int(conn.execute("SELECT max(id) FROM review_runs").fetchone()[0])
        db.set_run_report(conn, "review_runs", review_id, "s", unread_first_call(50_000, written), digest="d")

    [reviews] = [f for f in spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR).first_calls if f.kind == "reviews"]
    # The one that read nothing, the one that read under half, and the old one that wrote most of what it was sent.
    assert (reviews.runs, reviews.cold_share) == (5, 3 / 5)
    assert reviews.hit_rate == pytest.approx(50_000 / 150_000)  # the three that recorded a read


def test_canopy_spend_json_has_the_first_calls(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    conn = canopy_env.journal()
    now = noon_today()
    db.set_tick_report(conn, tick(conn, earlier(now, 0), 0.1), "s", first_call(50_000, 49_000), digest="abc")
    assert main(["spend", "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["first_calls"] == [
        {
            "kind": "overseer",
            "digest": "abc",
            "runs": 1,
            "first_call": 50_000,
            "cold_share": 1.0,
            "first_started": earlier(now, 0),
            "last_started": earlier(now, 0),
            "hit_rate": 1_000 / 50_000,
            "runtime_versions": [],
        },
    ]
    assert json.loads(out)["first_call_weeks"] == [
        {
            "kind": "overseer",
            "by": by,
            "name": None,
            "week": iso_week(now),
            "runs": 1,
            "first_call": 50_000,
            "hit_rate": 1_000 / 50_000,
            "new_runtime_versions": [],
            "new_digests": [],
        }
        for by in ("kind", "model")
    ]


def iso_week(at: datetime) -> str:
    """The ISO week `at` is in, as `canopy spend` names it: local time is UTC."""
    year, week, _ = at.date().isocalendar()
    return f"{year}-W{week:02d}"


def read_session(conn: sqlite3.Connection, table: RunTable, run_id: int, version: str, *models: str) -> None:
    """Record that run `run_id` of `table` was read, on runtime `version`, and that `models` wrote its replies."""
    used = [ModelUse(model, 1, 0.01) for model in models]
    run_models.record(conn, Due(table, run_id, "s", 0), ModelsRead.FOUND, used, runtime_version=version)


def chore_call(conn: sqlite3.Connection, chore: str, started: str, read: int, digest: str) -> int:
    """A run of `chore` whose first call was sent 40,000 tokens and read `read` of them from the cache."""
    cursor = conn.execute(
        "INSERT INTO chore_runs (chore, started_at, status, log_path) VALUES (?, ?, 'ok', 'l')",
        (chore, started),
    )
    assert cursor.lastrowid is not None
    db.set_run_report(conn, "chore_runs", cursor.lastrowid, "s", first_call(40_000, 0, read), digest=digest)
    return cursor.lastrowid


def journal_of_first_call_weeks(conn: sqlite3.Connection, now: datetime) -> None:
    """Two weeks of the overseer's and chores' first calls, the second's overseer on a new runtime and snapshot."""
    for days, sent, written, version, digest, models in (
        (7, 50_000, 5_000, "1.19.3", "d1", ("openai/gpt-x",)),
        (7.5, 50_000, 5_000, "1.19.3", "d1", ("openai/gpt-x",)),
        (0, 50_000, 40_000, "1.20.0", "d1", ("openai/gpt-x",)),
        (0.5, 60_000, 50_000, "1.20.0", "d2", ("openai/gpt-x", "provider/model-b")),
    ):
        t = tick(conn, earlier(now, days), 0.1)
        db.set_tick_report(conn, t, "s", first_call(sent, written), digest=digest)
        read_session(conn, "ticks", t, version, *models)
    for chore, days, read in (("deps", 7, 36_000), ("deps", 0, 38_000), ("docs", 0, 2_000)):
        read_session(conn, "chore_runs", chore_call(conn, chore, earlier(now, days), read, "c1"), "1.19.3")


def test_first_calls_by_week_are_by_kind_chore_and_model_and_name_what_changed(
    tmp_path: Path,
    journals: Journals,
) -> None:
    """A week's runs on a runtime or a snapshot its series' week before did not use name it (#1526)."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_first_call_weeks(conn, NOW)
    found = spend.breakdown(conn, NOW, 14, state_dir=STATE_DIR).first_call_weeks
    assert [(w.kind, w.by, w.name, w.week, w.runs, w.first_call) for w in found] == [
        ("overseer", "kind", None, "2026-W40", 2, 50_000),
        ("overseer", "kind", None, "2026-W41", 2, 50_000),
        ("overseer", "model", "openai/gpt-x", "2026-W40", 2, 50_000),
        ("overseer", "model", "openai/gpt-x", "2026-W41", 1, 50_000),
        # The tick two models served is no one model's.
        ("overseer", "model", None, "2026-W41", 1, 60_000),
        ("chores", "kind", None, "2026-W40", 1, 40_000),
        ("chores", "kind", None, "2026-W41", 2, 40_000),
        ("chores", "chore", "deps", "2026-W40", 1, 40_000),
        ("chores", "chore", "deps", "2026-W41", 1, 40_000),
        ("chores", "chore", "docs", "2026-W41", 1, 40_000),
        # No session named a model for the chores.
        ("chores", "model", None, "2026-W40", 1, 40_000),
        ("chores", "model", None, "2026-W41", 2, 40_000),
    ]
    by_week = {(w.kind, w.by, w.name, w.week): w for w in found}
    first, second = by_week["overseer", "kind", None, "2026-W40"], by_week["overseer", "kind", None, "2026-W41"]
    # Sent-weighted: what they all read over what they all were sent.
    assert (first.hit_rate, second.hit_rate) == (pytest.approx(0.9), pytest.approx(20_000 / 110_000))
    # A series' first week has none before it to differ from.
    assert (first.new_runtime_versions, first.new_digests) == ((), ())
    assert (second.new_runtime_versions, second.new_digests) == (("1.20.0",), ("d2",))
    assert by_week["overseer", "model", "openai/gpt-x", "2026-W41"].new_digests == ()
    # One chore's fall is its own, where the kind's is averaged with the other chores'.
    assert by_week["chores", "chore", "deps", "2026-W41"].hit_rate == pytest.approx(0.95)
    assert by_week["chores", "chore", "docs", "2026-W41"].hit_rate == pytest.approx(0.05)
    assert by_week["chores", "kind", None, "2026-W41"].hit_rate == pytest.approx(0.5)


def test_a_first_calls_snapshot_is_new_only_in_the_first_week_its_series_used_it(
    tmp_path: Path,
    journals: Journals,
) -> None:
    """A snapshot back after a week away is not new again, and a week's several new ones are each named once."""
    conn = journals.open(tmp_path / "canopy.db")
    for days, digest in ((21, "d1"), (21.5, "d2"), (14, "d1"), (7, "d2"), (7.5, "d3"), (0, "d1"), (0.5, "d4")):
        db.set_tick_report(conn, tick(conn, earlier(NOW, days), 0.1), "s", first_call(50_000, 1_000), digest=digest)
    found = spend.breakdown(conn, NOW, 28, state_dir=STATE_DIR).first_call_weeks
    weeks = [w.new_digests for w in found if (w.kind, w.by) == ("overseer", "kind")]
    assert weeks == [(), (), ("d3",), ("d4",)]


def test_a_first_calls_week_is_a_local_iso_week(tmp_path: Path, journals: Journals) -> None:
    """A Monday's first hour in local time is in that Monday's week, though UTC still has it on Sunday."""
    conn = journals.open(tmp_path / "canopy.db")
    monday = datetime(2026, 10, 5, 0, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    db.set_tick_report(conn, tick(conn, db.format_time(monday), 0.1), "s", first_call(50_000, 1_000), digest="d")
    with in_zone("Europe/Berlin"):
        found = spend.breakdown(conn, monday, 1, state_dir=STATE_DIR).first_call_weeks
    assert {w.week for w in found} == {"2026-W41"}


def test_canopy_spend_prints_each_kind_s_first_calls_by_week(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = noon_today()
    journal_of_first_call_weeks(canopy_env.journal(), now)
    assert main(["spend", "--days", "14"]) == 0
    out = capsys.readouterr().out.splitlines()
    start = out.index(next(line for line in out if line.startswith("week ")))
    before, this = iso_week(now - timedelta(days=7)), iso_week(now)
    assert [line.split() for line in out[start : start + 5]] == [
        ["week", "kind", "runs", "sent", "hit", "new"],
        [before, "overseer", "2", "50.0k", "90%"],
        [this, "overseer", "2", "50.0k", "18%", "runtime", "1.20.0", "snapshot", "d2"],
        [before, "chores", "1", "40.0k", "90%"],
        [this, "chores", "2", "40.0k", "50%"],
    ]
    assert out[start + 6] == "--json breaks each kind's weeks down by chore and by model."


def test_canopy_spend_counts_a_week_s_new_snapshots_when_there_are_several(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One change to canopy renders every prompt's snapshot anew: the line counts them, and `--json` names them."""
    now = noon_today()
    conn = canopy_env.journal()
    for days, digest in ((7, "d1"), (0, "d2"), (0.25, "d3"), (0.5, "d4")):
        db.set_tick_report(conn, tick(conn, earlier(now, days), 0.1), "s", first_call(50_000, 1_000), digest=digest)
    assert main(["spend", "--days", "14"]) == 0
    out = capsys.readouterr().out.splitlines()
    this = next(line for line in out if line.startswith(iso_week(now)))
    assert this.split()[-2:] == ["3", "snapshots"]


def test_canopy_spend_says_when_no_first_call_was_recorded(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.journal()
    assert main(["spend"]) == 0
    assert "No first model call recorded." in capsys.readouterr().out.splitlines()


def tools_journal(conn: sqlite3.Connection, now: datetime) -> None:
    """Tool calls of each kind of run in the window, a dry tick's among them, and of a tick before it."""
    usage = Usage(0.1, 0, 0, 0, 0, 0)
    reads = [ToolUse("github_pull_request_read", 3, 0, 40_000), ToolUse("bash", 2, 1, 900)]
    db.set_tick_report(conn, tick(conn, earlier(now, 0, 1), 0.1), "s", usage, tools=reads)
    db.set_tick_report(conn, tick(conn, earlier(now, 0, 2), 0.1, dry_run=True), "s", usage, tools=reads[:1])
    db.set_tick_report(conn, tick(conn, earlier(now, 9), 0.1), "s", usage, tools=[ToolUse("bash", 50, 0, 10**6)])
    ticket(conn, "PROJ-1")
    first = int(conn.execute("SELECT min(id) FROM ticks").fetchone()[0])
    run(conn, first, "PROJ-1", earlier(now, 0, 3), 0.1, None)
    run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
    db.set_run_report(conn, "runs", run_id, "s", usage, tools=[ToolUse("bash", 30, 4, 20_000)])
    conn.execute(
        "INSERT INTO chore_runs (chore, started_at, status, log_path) VALUES ('deps', ?, 'ok', 'l')",
        (earlier(now, 0),),
    )
    chore_id = int(conn.execute("SELECT max(id) FROM chore_runs").fetchone()[0])
    db.set_run_report(conn, "chore_runs", chore_id, "s", usage, tools=[ToolUse("read", 1, 0, 10)])
    review(conn, first, "https://e.test/pr/1", None, earlier(now, 0), 0.1)
    review_id = int(conn.execute("SELECT max(id) FROM review_runs").fetchone()[0])
    db.set_run_report(conn, "review_runs", review_id, "s", usage, tools=[ToolUse("bash", 1, 0, 900)])


def test_tools_are_by_kind_and_tool_the_most_returned_first(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    tools_journal(conn, NOW)
    found = spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR)
    assert found.tools == [
        # Both ticks' reads, the dry run's among them; not the tick before the window.
        spend.ToolSpend("overseer", "github_pull_request_read", 2, 6, 0, 80_000, 20_000),
        spend.ToolSpend("workers", "bash", 1, 30, 4, 20_000, 5_000),
        spend.ToolSpend("overseer", "bash", 1, 2, 1, 900, 225),  # a tie goes to the kinds' order
        spend.ToolSpend("reviews", "bash", 1, 1, 0, 900, 225),
        spend.ToolSpend("chores", "read", 1, 1, 0, 10, 2),
    ]
    assert spend.breakdown(conn, NOW - timedelta(days=30), 1, state_dir=STATE_DIR).tools == []


def test_canopy_spend_prints_the_tools_that_returned_the_most(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = canopy_env.journal()
    now = noon_today()
    assert main(["spend"]) == 0
    assert "No tool call recorded." in capsys.readouterr().out.splitlines()

    tools_journal(conn, now)
    many = [ToolUse(f"mcp_{n}", 1, 0, n) for n in range(1, 11)]
    db.set_tick_report(conn, tick(conn, earlier(now, 0, 4), 0.1), "s", Usage(0.1, 0, 0, 0, 0, 0), tools=many)
    assert main(["spend", "--days", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    first = out.index(next(line for line in out if line.startswith("tool ")))
    assert out[first].split() == ["tool", "kind", "calls", "errors", "returned", "~tokens"]
    assert out[first + 1].split() == ["github_pull_request_read", "overseer", "6", "0", "80.0k", "20.0k"]
    assert out[first + 2].split() == ["bash", "workers", "30", "4", "20.0k", "5.0k"]
    assert out[first + 11].split() == ["and", "5", "more;", "--json", "lists", "every", "one"]
    assert out[first + 12] == "Returned is in characters; ~tokens is that over 4, an estimate."

    assert main(["spend", "--json", "--days", "1"]) == 0
    tools = json.loads(capsys.readouterr().out)["tools"]
    assert len(tools) == 15
    assert tools[0] == {
        "kind": "overseer",
        "tool": "github_pull_request_read",
        "runs": 2,
        "calls": 6,
        "errors": 0,
        "result_chars": 80_000,
        "est_tokens": 20_000,
    }


@pytest.mark.parametrize("kind", spend.KINDS)
def test_tools_read_only_the_windows_runs(tmp_path: Path, journals: Journals, kind: spend.Kind) -> None:
    """The run table leads, by its `started_at` index, so the window's cost is its own runs', not the whole history's.

    A journal in a test is too small for a slow plan to show in its time, so the plan is what is held. Workers and
    plans share `runs`, told apart by kind, which the index does not cover: each run in the window is read for it.
    """
    conn = journals.open(tmp_path / "canopy.db")
    table, _ = spend.KIND_TABLES[kind]
    query = spend._tools_of(kind, earlier(NOW, 7), earlier(NOW, 0))  # noqa: SLF001
    plan = [str(row[3]) for row in sql.execute(conn, sql.frag("EXPLAIN QUERY PLAN {}", query))]
    assert re.match(rf"SEARCH r USING (COVERING )?INDEX {table}_spent \(started_at>\? AND started_at<\?\)", plan[0]), (
        plan
    )
    assert plan[1].startswith("SEARCH t USING PRIMARY KEY (run_table=? AND run_id=?)"), plan


def served(conn: sqlite3.Connection, table: str, run_id: int, *models: tuple[str, int, float]) -> None:
    """Record that run `run_id` of `table` was read, and which models its session named."""
    conn.execute(
        "INSERT INTO run_model_reads (run_table, run_id, status, attempts, read_at) VALUES (?, ?, 'found', 1, 'x')",
        (table, run_id),
    )
    conn.executemany(
        "INSERT INTO run_models (run_table, run_id, model, replies, cost_usd) VALUES (?, ?, ?, ?, ?)",
        [(table, run_id, *m) for m in models],
    )


def journal_of_models(conn: sqlite3.Connection, now: datetime) -> None:
    """A day of runs on two models, a run on both, a run not read yet, and one on a model before the window."""
    ticket(conn, "PROJ-1")
    old = tick(conn, earlier(now, 9), 5.0)
    served(conn, "ticks", old, ("anthropic/claude-old", 9, 5.0))
    first = tick(conn, earlier(now, 0, 3), 0.5)
    served(conn, "ticks", first, ("anthropic/claude-haiku", 4, 0.5))
    unread = tick(conn, earlier(now, 0, 2), 0.25)  # not read yet
    conn.execute("UPDATE ticks SET session_id = 'ses_unread' WHERE id = ?", (unread,))
    for started, cost in ((earlier(now, 0, 3), 2.0), (earlier(now, 0, 2), 3.0)):
        run(conn, first, "PROJ-1", started, cost, None)
    served(conn, "runs", 1, ("openai/gpt-x", 10, 2.0))
    served(conn, "runs", 2, ("openai/gpt-x", 5, 1.0), ("anthropic/claude-sonnet", 6, 2.0))


def test_each_kind_s_spend_is_split_by_the_models_its_sessions_name(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_models(conn, NOW)
    found = spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR).models
    assert [(m.kind, m.model, m.runs, m.replies, m.cost_usd) for m in found] == [
        ("overseer", "anthropic/claude-haiku", 1, 4, 0.5),
        # The tick not read yet, at what it reported.
        ("overseer", None, 1, 0, 0.25),
        # The run on both models counts under each.
        ("workers", "openai/gpt-x", 2, 15, 3.0),
        ("workers", "anthropic/claude-sonnet", 1, 6, 2.0),
    ]
    assert {(m.workspace_runs, m.workspace_cost_usd) for m in found} == {(None, None)}  # the workspace's own


def test_the_runs_no_session_named_a_model_for_are_unread_apart_from_none(tmp_path: Path, journals: Journals) -> None:
    """Unread is a session canopy has yet to read: running, never read, or a failed read; the rest were read to none."""
    conn = journals.open(tmp_path / "canopy.db")
    ticket(conn, "PROJ-1")
    first = tick(conn, earlier(NOW, 0, 3), None)
    # cost, session, ended, how the last read ended
    for cost, session, ended, status in (
        (1.0, "ses_1", False, None),  # running
        (2.0, "ses_2", True, None),  # not read yet
        (4.0, "ses_4", True, "failed"),  # tried again later
        (8.0, "ses_8", True, "missing"),  # the runtime no longer keeps it
        (16.0, None, True, None),  # it reported no session to read
        (32.0, "ses_32", True, "found"),  # it made no model call
    ):
        run(conn, first, "PROJ-1", earlier(NOW, 0, 2), cost, None)
        run_id = conn.execute("SELECT max(id) FROM runs").fetchone()[0]
        conn.execute(
            "UPDATE runs SET session_id = ?, ended_at = ? WHERE id = ?",
            (session, earlier(NOW, 0, 1) if ended else None, run_id),
        )
        if status is not None:
            conn.execute(
                "INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at) "
                "VALUES ('runs', ?, ?, ?, 1, 'x')",
                (run_id, status, "timed out" if status == "failed" else None),
            )
    run(conn, first, "PROJ-1", earlier(NOW, 0, 2), 64.0, None)
    served(conn, "runs", 7, ("openai/gpt-x", 3, 64.0))
    # A failed read again, of a run an earlier read named a model of, keeps the model.
    conn.execute("UPDATE run_model_reads SET status = 'failed', error = 'timed out' WHERE run_id = 7")
    found = spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR).models
    assert [(m.kind, m.model, m.unread, m.runs, m.cost_usd) for m in found if m.kind == "workers"] == [
        ("workers", "openai/gpt-x", False, 1, 64.0),
        ("workers", None, True, 3, 7.0),
        ("workers", None, False, 3, 56.0),
    ]
    # Narrowed to the ticket, each row of no model is beside the workspace's of the same why.
    narrowed = spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR, ticket="PROJ-1").models
    assert [(m.model, m.unread, m.runs, m.workspace_runs, m.workspace_cost_usd) for m in narrowed] == [
        ("openai/gpt-x", False, 1, 1, 64.0),
        (None, True, 3, 3, 7.0),
        (None, False, 3, 3, 56.0),
    ]
    assert run_models.unread_of_ticket(conn, "PROJ-1") == 7.0
    assert run_models.unread_of_ticket(conn, "PROJ-2") is None


def test_a_ticket_s_spend_by_model_is_its_runs_beside_the_workspace_s(tmp_path: Path, journals: Journals) -> None:
    """Narrowed to a ticket, a row counts its runs on a model, with the workspace's runs of its kind on it beside."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_models(conn, NOW)
    ticket(conn, "PROJ-2")
    later = tick(conn, earlier(NOW, 0, 1), 0.1)
    run(conn, later, "PROJ-2", earlier(NOW, 0, 1), 4.0, None)
    served(conn, "runs", 3, ("openai/gpt-x", 8, 4.0))
    review(conn, later, "https://github.com/acme/api/pull/1", "PROJ-2", earlier(NOW, 0, 1), 0.5)  # not read yet
    found = spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR, ticket="PROJ-2")
    # No overseer's row: a tick names no ticket. PROJ-1's runs are only among the workspace's.
    assert [(m.kind, m.model, m.runs, m.cost_usd, m.workspace_runs, m.workspace_cost_usd) for m in found.models] == [
        ("workers", "openai/gpt-x", 1, 4.0, 3, 7.0),
        ("reviews", None, 1, 0.5, 1, 0.5),
    ]
    # Every other figure is the workspace's.
    assert found.totals == spend.breakdown(conn, NOW, 1, state_dir=STATE_DIR).totals
    since, until = (db.format_time(t) for t in spend.window(NOW, 1))
    assert [m.kind for m in spend.models(conn, since, until, ticket="PROJ-2", kind="workers")] == ["workers"]
    # The later tick reported no session, so it is none, apart from the one not read yet.
    assert [(m.model, m.unread) for m in spend.models(conn, since, until, kind="overseer")] == [
        ("anthropic/claude-haiku", False),
        (None, True),
        (None, False),
    ]


def test_canopy_spend_prints_the_spend_by_model(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    journal_of_models(canopy_env.journal(), noon_today())
    assert main(["spend", "--days", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    start = out.index(next(line for line in out if line.startswith("model ")))
    assert [line.split() for line in out[start : start + 6]] == [
        ["model", "kind", "runs", "replies", "spent"],
        ["anthropic/claude-haiku", "overseer", "1", "4", "$0.50"],
        ["(unread)", "overseer", "1", "-", "$0.25"],
        ["openai/gpt-x", "workers", "2", "15", "$3.00"],
        ["anthropic/claude-sonnet", "workers", "1", "6", "$2.00"],
        ["A", "run", "on", "two", "models", "counts", "under", "each."],
    ]


def test_canopy_spend_says_when_no_run_s_models_were_read(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    journal_of_a_week(canopy_env.journal(), noon_today())
    assert main(["spend"]) == 0
    assert "No run's models read yet: canopy reads them from each run's session, a few runs each tick." in (
        capsys.readouterr().out.splitlines()
    )


@pytest.mark.parametrize("kind", spend.KINDS)
def test_models_read_only_the_windows_runs(tmp_path: Path, journals: Journals, kind: spend.Kind) -> None:
    """As `test_tools_read_only_the_windows_runs`: the run table leads, and `run_models` is read by its key."""
    conn = journals.open(tmp_path / "canopy.db")
    table, _ = spend.KIND_TABLES[kind]
    query = spend._named_models(kind, earlier(NOW, 7), earlier(NOW, 0))  # noqa: SLF001
    plan = [str(row[3]) for row in sql.execute(conn, sql.frag("EXPLAIN QUERY PLAN {}", query))]
    assert re.match(rf"SEARCH r USING (COVERING )?INDEX {table}_spent \(started_at>\? AND started_at<\?\)", plan[0]), (
        plan
    )
    assert plan[1].startswith("SEARCH m USING PRIMARY KEY (run_table=? AND run_id=?)"), plan


def test_the_month_is_the_local_calendar_month_against_its_budget(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, "2026-09-30T23:00:00.000Z", 9.0)  # September's, in UTC
    tick(conn, "2026-10-01T09:00:00.000Z", 1.0)
    tick(conn, "2026-10-08T09:00:00.000Z", 0.5, dry_run=True)  # a dry run costs what it costs
    conn.execute(
        "INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path, cost_usd) "
        "VALUES (NULL, 'deps', '2026-10-08T10:00:00.000Z', 'ok', 'l', 1.5)",
    )
    found = spend.month(conn, NOW, 10, state_dir=STATE_DIR)
    assert (found.month, found.since, found.until) == (
        "2026-10",
        "2026-10-01T00:00:00.000Z",
        "2026-11-01T00:00:00.000Z",
    )
    assert found.spent_usd == pytest.approx(3.0)
    assert found.elapsed == pytest.approx(7.5 / 31)
    assert found.projected_usd == pytest.approx(3.0 / (7.5 / 31))
    assert (found.share, found.over) == (pytest.approx(0.3), False)
    assert spend.month(conn, NOW, 3, state_dir=STATE_DIR).over
    # In Los Angeles, September's last evening is September's still, and October starts at its midnight.
    with in_zone("America/Los_Angeles"):
        there = spend.month(conn, NOW, 10, state_dir=STATE_DIR)
    assert there.since == "2026-10-01T07:00:00.000Z"
    assert there.spent_usd == pytest.approx(3.0)


def test_a_month_has_no_pace_in_its_first_day(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, "2026-10-01T01:00:00.000Z", 4.0)
    morning = spend.month(conn, datetime(2026, 10, 1, 9, tzinfo=UTC), 100, state_dir=STATE_DIR)
    assert (morning.spent_usd, morning.projected_usd) == (4.0, None)
    assert spend.month(
        conn,
        datetime(2026, 10, 2, 0, tzinfo=UTC),
        100,
        state_dir=STATE_DIR,
    ).projected_usd == pytest.approx(124.0)
    # Nothing reported a cost: nothing spent, and no pace to read.
    empty = spend.month(conn, datetime(2026, 12, 15, tzinfo=UTC), 100, state_dir=STATE_DIR)
    assert (empty.spent_usd, empty.projected_usd, empty.share) == (None, None, 0.0)


def test_canopy_spend_prints_the_month_against_its_budget(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime.now(UTC)
    tick(canopy_env.journal(), db.format_time(now), 2.0)
    canopy_env.append_user("[spend]\nmonthly_budget_usd = 5\n")
    assert main(["spend", "--days", "1"]) == 0
    line = capsys.readouterr().out.splitlines()[1]
    assert re.fullmatch(
        rf"This month, {now:%Y-%m}: \$2\.00 of a \$5 budget \(40%\)(, on pace for \$\d+\.\d\d)?\. Canopy's runs "
        r"\$2\.00; outside canopy is not counted until canopy loop reads the runtime's sessions\.",
        line,
    )
    assert main(["spend", "--json"]) == 0
    month = json.loads(capsys.readouterr().out)["month"]
    assert (month["month"], month["budget_usd"], month["spent_usd"], month["share"]) == (f"{now:%Y-%m}", 5, 2.0, 0.4)


def test_canopy_spend_says_when_the_month_is_over_its_budget(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = canopy_env.journal()
    tick(conn, db.format_time(datetime.now(UTC)), 4.99)
    canopy_env.append_user("[spend]\nmonthly_budget_usd = 5\n")
    assert main(["spend", "--days", "1"]) == 0
    short = capsys.readouterr().out.splitlines()[1]
    # Floored: a month a cent short of its budget is not all of it.
    assert "(99%)" in short
    assert not short.endswith("Over budget.")
    tick(conn, db.format_time(datetime.now(UTC)), 1.0)
    assert main(["spend", "--days", "1"]) == 0
    assert capsys.readouterr().out.splitlines()[1].endswith(". Over budget.")


def test_canopy_spend_names_no_month_without_a_budget(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["spend", "--days", "1"]) == 0
    assert capsys.readouterr().out.splitlines()[1] == ""
    assert main(["spend", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["month"] is None


def test_a_month_s_alerts_are_100_and_the_operator_s_and_it_names_the_highest_reached(
    tmp_path: Path,
    journals: Journals,
) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, "2026-10-02T09:00:00.000Z", 8.5)
    found = spend.month(conn, NOW, 10, (150, 50, 80), state_dir=STATE_DIR)
    assert (found.alerts, found.reached) == ((50, 80, 100, 150), 80)
    assert spend.month(conn, NOW, 10, state_dir=STATE_DIR).alerts == (100,)
    assert spend.month(conn, NOW, 10, state_dir=STATE_DIR).reached is None
    assert spend.month(conn, NOW, 5, (50,), state_dir=STATE_DIR).reached == 100
    assert spend.month(conn, NOW, 100, (50,), state_dir=STATE_DIR).reached is None


def test_a_month_s_percent_is_floored_in_whole_cents(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, "2026-10-02T09:00:00.000Z", 0.1)
    tick(conn, "2026-10-02T10:00:00.000Z", 0.19)
    # 0.1 + 0.19 is 0.29000000000000004, and 0.29 * 100 a hair under 29: in cents it is 29, of a $1 budget.
    assert spend.month(conn, NOW, 1, state_dir=STATE_DIR).percent == 29
    tick(conn, "2026-10-02T11:00:00.000Z", 0.7)
    assert (
        spend.month(conn, NOW, 1, state_dir=STATE_DIR).percent,
        spend.month(conn, NOW, 1, state_dir=STATE_DIR).over,
    ) == (99, False)
    tick(conn, "2026-10-02T12:00:00.000Z", 0.01)
    assert (
        spend.month(conn, NOW, 1, state_dir=STATE_DIR).percent,
        spend.month(conn, NOW, 1, state_dir=STATE_DIR).over,
    ) == (100, True)


def test_a_breakdown_counts_the_sessions_outside_canopy_by_day_but_not_per_ticket_done(
    tmp_path: Path,
    journals: Journals,
) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_sessions(conn, NOW)
    conn.execute("UPDATE ticks SET cost_usd = 1.0")
    [t] = [int(r[0]) for r in conn.execute("SELECT id FROM ticks")]
    ticket(conn, "A-1", done=True)
    decide(conn, t, "A-1", earlier(NOW, 0), "done", "every PR merged")
    found = spend.breakdown(conn, NOW, 2, state_dir=STATE_DIR)
    assert [(d.costs.outside, d.costs.runs, d.costs.total) for d in found.per_day] == [
        (None, None, None),
        (2.25, 1.0, 3.25),
    ]
    assert (found.totals.outside, found.totals.total) == (2.25, 3.25)
    assert found.per_done == 1.0  # canopy's runs alone: the operator's own sessions got nothing done
    hours = spend.breakdown_hours(conn, NOW, 2, state_dir=STATE_DIR)
    assert hours.totals.outside == 2.25
    assert spend.costs(conn, earlier(NOW, 1), db.format_time(NOW + timedelta(hours=1)), state_dir=STATE_DIR) == (
        spend.Costs(overseer=1.0, outside=2.25)
    )


def test_the_month_and_the_counters_add_the_sessions_outside_canopy_to_canopys_runs(
    tmp_path: Path,
    journals: Journals,
) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_sessions(conn, NOW)
    # The overseer's session is the tick's: its cost is counted once, as the tick's.
    conn.execute("UPDATE ticks SET cost_usd = 1.0")
    found = spend.month(conn, NOW, 10, state_dir=STATE_DIR)
    assert (found.runs_usd, found.outside_usd, found.sessions_read_at) == (1.0, 2.25, db.format_time(NOW))
    assert found.spent_usd == pytest.approx(3.25)
    assert spend.spent_since(conn, "", state_dir=STATE_DIR) == pytest.approx(3.25)
    assert spend.spent_since(conn, earlier(NOW, -1), state_dir=STATE_DIR) is None


def test_a_month_before_the_sessions_are_read_is_canopys_runs_alone(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, "2026-10-02T09:00:00.000Z", 1.0)
    found = spend.month(conn, NOW, 10, state_dir=STATE_DIR)
    assert (found.spent_usd, found.runs_usd, found.outside_usd, found.sessions_read_at) == (1.0, 1.0, 0.0, None)


def journal_of_sessions(conn: sqlite3.Connection, now: datetime) -> None:
    """A tick whose overseer ran in `ses_overseer`, and the runtime's record of it, its subagent's, and two others."""
    started = earlier(now, 0)
    conn.execute(
        "INSERT INTO ticks (started_at, ended_at, dry_run, status, session_id) VALUES (?, ?, 0, 'ok', 'ses_overseer')",
        (started, started),
    )
    ms = int(now.timestamp() * 1000)

    def session(session_id: str, cost: float, directory: str, parent: str | None = None) -> SessionSpend:
        return SessionSpend(session_id, parent, directory, ms, ms, cost, 1, 1, 0, 0, 0)

    runtime_sessions.record(
        conn,
        SessionPage(
            "found",
            (
                session("ses_overseer", 1.0, "/work/ws"),
                session("ses_sub", 0.5, "/work/ws", parent="ses_overseer"),
                session("ses_notes", 2.0, "/home/me/notes"),
                session("ses_web", 0.25, "/work/web"),
            ),
            cursor=(ms, "ses_web"),
        ),
        now=db.format_time(now),
    )


def test_canopy_spend_prints_every_runtime_session_canopys_apart(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = noon_today()
    journal_of_sessions(canopy_env.journal(), now)
    assert main(["spend", "--days", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    start = out.index(f"Every runtime session, as its record says (read {now:%Y-%m-%d}):")
    assert [line.split() for line in out[start + 1 : start + 6]] == [
        ["sessions", "count", "spent"],
        ["canopy's", "runs", "2", "$1.50"],
        ["outside", "canopy", "2", "$2.25"],
        ["1", "$2.00", "/home/me/notes"],
        ["1", "$0.25", "/work/web"],
    ]
    assert (
        out[start + 6]
        == "A subagent's session counts with the session it ran for; another workspace's runs are outside."
    )


def test_canopy_spend_s_month_names_canopys_runs_and_the_sessions_outside_canopy(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = noon_today()
    journal_of_sessions(canopy_env.journal(), now)
    canopy_env.append_user("[spend]\nmonthly_budget_usd = 5\n")
    assert main(["spend", "--days", "1"]) == 0
    line = capsys.readouterr().out.splitlines()[1]
    assert re.fullmatch(
        rf"This month, {now:%Y-%m}: \$2\.25 of a \$5 budget \(45%\)(, on pace for \$\d+\.\d\d)?\. Canopy's runs "
        r"\$0\.00, outside canopy \$2\.25\.",
        line,
    )
    assert main(["spend", "--json"]) == 0
    month = json.loads(capsys.readouterr().out)["month"]
    assert (month["spent_usd"], month["runs_usd"], month["outside_usd"]) == (2.25, None, 2.25)


def test_canopy_spend_json_has_every_runtime_session_canopys_apart(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    journal_of_sessions(canopy_env.journal(), noon_today())
    assert main(["spend", "--days", "1", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)["sessions"]
    assert found["canopy"] == {"sessions": 2, "cost_usd": 1.5}
    assert found["outside"] == {"sessions": 2, "cost_usd": 2.25}
    assert found["directories"][0] == {"directory": "/home/me/notes", "sessions": 1, "cost_usd": 2.0}
    assert found["status"] == "found"


def test_canopy_spend_says_when_the_runtimes_sessions_were_never_read(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    journal_of_a_week(canopy_env.journal(), noon_today())
    assert main(["spend"]) == 0
    assert "The runtime's sessions were never read: canopy loop reads them, canopy's and not, between ticks." in (
        capsys.readouterr().out.splitlines()
    )
