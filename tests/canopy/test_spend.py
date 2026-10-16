"""What agent runs cost, by what they bought (DESIGN §11, ROADMAP M33): `canopy spend` over a journal by hand."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db, spend
from canopy.core.agent_output import ToolUse, Usage
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


def ticket(conn: sqlite3.Connection, key: str, *, title: str | None = None, done: bool = False) -> None:
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, title, done) VALUES (?, 'ws', ?, ?, ?, ?)",
        (key, at(NOW, 30), at(NOW, 30), title, int(done)),
    )


def run(
    conn: sqlite3.Connection, tick_id: int, key: str, started: str, cost: float | None, prs: dict[str, str] | None
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

    assert (found.since, found.until, found.days) == ("2026-10-02T00:00:00.000Z", "2026-10-09T00:00:00.000Z", 7)
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
    week = spend.breakdown(conn, NOW, 7)
    rows = spend.idle_ticks(conn, week.since, week.until)
    assert [(r["started_at"], r["cost_usd"]) for r in rows] == [
        (at(NOW, 1, 2), None),
        (at(NOW, 1), 0.25),
        (at(NOW, 2, 1), 0.25),
    ]
    today = spend.breakdown(conn, NOW, 1)
    assert spend.idle_ticks(conn, today.since, today.until) == []  # today's one idle tick is dry


def test_canopy_spend_prints_the_breakdown(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    now = noon_today()
    journal_of_a_week(canopy_env.journal(), now)
    assert main(["spend", "--days", "3"]) == 0
    out = capsys.readouterr().out.splitlines()
    start = spend.window_start(now, 3).strftime("%Y-%m-%d")
    assert out[0] == f"Spend over 3 days, since {start} UTC, as the runtime reported it."
    assert out[2].split() == ["day", "overseer", "idle", "workers", "chores", "reviews", "dry", "run", "total"]
    days = [(spend.window_start(now, 3) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
    assert [line.split()[0] for line in out[3:6]] == days  # a line per day, oldest first
    assert out[6].split() == ["all", "$2.50", "$0.50", "$2.00", "$0.75", "$1.50", "$0.30", "$7.05"]
    words = [line.split() for line in out]
    assert ["idle", "3", "$0.50"] in words
    assert ["not", "idle", "2", "$1.50"] in words
    assert "Idle ticks were 20% of the live overseer's spend." in out
    assert ["timer", "3", "$0.50"] in words
    # A kind whose every run reported a cost is left out.
    assert out[-1] == "No cost reported: 1 of 8 overseer runs, 1 of 2 worker and split runs, 1 of 2 chore runs."


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


def test_a_running_dry_run_is_never_the_live_overseers(tmp_path: Path, journals: Journals) -> None:
    """A tick records its overseer's cost before it closes, so a dry run still acting is already priced."""
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, at(NOW, 0, 1), 0.5, status="running", dry_run=True)
    tick(conn, at(NOW, 0, 2), 0.25, status="running")
    found = spend.breakdown(conn, NOW, 1)
    assert (found.totals.dry_run, found.totals.overseer) == (0.5, 0.25)
    assert [g.ticks for g in found.ticks] == [0] * len(spend.GROUPS)  # neither has ended
    assert found.unpriced[0] == spend.Unpriced(kind="overseer", runs=0, unpriced=0)


def test_canopy_spend_says_when_every_run_reported_a_cost(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    tick(canopy_env.journal(), at(noon_today(), 0), 0.25, idle=True, woken_by="timer")
    assert main(["spend", "--days", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Spend over 1 day, since ")
    assert out[-1] == "Every run that ended reported a cost."


def test_a_row_after_the_window_is_in_no_figure(tmp_path: Path, journals: Journals) -> None:
    """A clock behind the journal's puts a row after today: it is in no day, no total, and no count."""
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, db.format_time(NOW + timedelta(days=1)), 9.0, idle=True, woken_by="timer")
    tick(conn, at(NOW, 0), 1.0, idle=False, woken_by="start")
    found = spend.breakdown(conn, NOW, 1)
    assert (found.totals.overseer, found.totals.idle) == (1.0, None)
    assert [(g.group, g.ticks) for g in found.ticks if g.ticks] == [("busy", 1)]
    assert [w.by for w in found.woken] == ["start"]
    assert found.unpriced[0].runs == 1
    assert spend.idle_ticks(conn, found.since, found.until) == []


def test_idle_share_is_of_the_live_ticks_that_ended(tmp_path: Path, journals: Journals) -> None:
    """A running tick has reported its cost and is in no group yet, so it is in neither part of the share."""
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, at(NOW, 0, 2), 0.25, idle=True, woken_by="timer")
    tick(conn, at(NOW, 0, 1), 0.75, idle=False, woken_by="message")
    tick(conn, at(NOW, 0), 2.0, status="running")
    found = spend.breakdown(conn, NOW, 1)
    assert found.totals.overseer == 3.0  # the running tick's cost counts, as the rail's counters count it
    assert found.idle_share == 0.25


def test_what_each_ticket_and_pr_cost_and_what_the_window_got_done(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    t = tick(conn, at(NOW, 1), 4.0, idle=False, woken_by="start")
    web, api, other = "https://e.test/web/pull/1", "https://e.test/api/pull/2", "https://e.test/x/pull/9"
    ticket(conn, "A-1", title="Merged", done=True)
    ticket(conn, "A-2", title="Closed in the tracker", done=True)
    ticket(conn, "A-3")  # still open
    ticket(conn, "A-4", done=True)  # done the week before, its last run in the window
    ticket(conn, "A-5", done=True)  # done in the window, no run in it
    conn.execute(
        "INSERT INTO ticket_units (ticket_key, repo, pr_url, phase) VALUES ('A-1', 'web', ?, 'merged')", (web,)
    )
    run(conn, t, "A-1", at(NOW, 2), 3.0, {"web": web, "api": api})  # a joint run: on each PR, once on its ticket
    run(conn, t, "A-1", at(NOW, 9), 50.0, {"web": web})  # before the window
    run(conn, t, "A-2", at(NOW, 1), 1.0, None)
    run(conn, t, "A-3", at(NOW, 0), 0.5, {"web": "not a url"})
    run(conn, t, "A-4", at(NOW, 3), None, None)
    review(conn, t, web, "A-1", at(NOW, 1), 0.25)
    review(conn, t, other, None, at(NOW, 0), 0.75)
    decide(conn, t, "A-1", at(NOW, 1), "done", "every PR merged")
    decide(conn, t, "A-2", at(NOW, 3), "done", "every PR merged")
    decide(conn, t, "A-2", at(NOW, 1), "done", db.CLOSED_RATIONALE)  # the newest says how
    decide(conn, t, "A-4", at(NOW, 8), "done", "every PR merged")
    decide(conn, t, "A-5", at(NOW, 0), "done", "every PR merged")
    found = spend.breakdown(conn, NOW, 7)

    assert found.done == 3
    assert [d.done for d in found.per_day] == [0, 0, 0, 0, 0, 2, 1]
    assert found.totals.total == pytest.approx(9.5)
    assert found.per_done == pytest.approx(9.5 / 3)  # the window's whole spend, the overseer's included
    assert found.tickets == [
        spend.TicketSpend("A-1", "Merged", 1, 1, 3.25, "merged", at(NOW, 1)),
        spend.TicketSpend("A-2", "Closed in the tracker", 1, 0, 1.0, "closed", at(NOW, 1)),
        spend.TicketSpend("A-3", None, 1, 0, 0.5),
        spend.TicketSpend("A-4", None, 1, 0, None),  # done before the window: not done in it
        spend.TicketSpend("A-5", None, 0, 0, None, "merged", at(NOW, 0)),
    ]
    assert found.pull_requests == [
        spend.PullRequestSpend(web, "A-1", "merged", runs=1, reviews=1, cost_usd=3.25),
        spend.PullRequestSpend(api, "A-1", None, runs=1, reviews=0, cost_usd=3.0),
        spend.PullRequestSpend(other, None, None, runs=0, reviews=1, cost_usd=0.75),
    ]


def test_a_ticket_forgotten_or_reopened_since_it_was_done_is_not_done(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    t = tick(conn, at(NOW, 1), 1.0)
    ticket(conn, "A-1", done=True)
    ticket(conn, "A-2")  # reopened: no longer done
    decide(conn, t, "A-1", at(NOW, 1), "done", "every PR merged")
    decide(conn, t, "A-2", at(NOW, 1), "done", "every PR merged")
    conn.execute("UPDATE tickets SET forgotten_at = ? WHERE key = 'A-1'", (at(NOW, 0),))
    found = spend.breakdown(conn, NOW, 7)
    assert (found.done, found.per_done, found.tickets) == (0, None, [])


def test_canopy_spend_prints_the_tickets_done_and_the_costliest(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    now = noon_today()
    conn = canopy_env.journal()
    t = tick(conn, at(now, 0), 1.0)
    for n in range(12):
        ticket(conn, f"A-{n}", done=n == 11)
        run(conn, t, f"A-{n}", at(now, 0), n + 1.0, None)
    decide(conn, t, "A-11", at(now, 0), "done", "every PR merged")
    assert main(["spend", "--days", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "1 ticket marked done, $79.00 of all spend for each." in out
    words = [line.split() for line in out]
    first = words.index(["ticket", "runs", "spent", "done"]) + 1
    assert words[first] == ["A-11", "1", "$12.00", at(now, 0)[:10], "merged"]
    assert [w[0] for w in words[first : first + 10]] == [f"A-{n}" for n in range(11, 1, -1)]  # the costliest ten
    assert words[first + 10] == ["and", "2", "more;", "--json", "lists", "every", "one"]


def first_call(sent: int, written: int) -> Usage:
    """What a run reported whose first model call was sent `sent` tokens and wrote `written` of them to the cache."""
    return Usage(0.1, 0, 0, 0, sent - written, written, peak_context=sent, first_call=sent, first_cache_write=written)


def test_first_calls_are_by_kind_and_snapshot_with_their_median_and_cold_share(
    tmp_path: Path, journals: Journals
) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    calls = [(5, 50_000, 49_000, "old"), (4, 52_000, 3_000, "old"), (3, 51_000, 2_000, "old")]
    calls += [(2, 60_000, 58_000, "new"), (1, 62_000, 5_000, "new")]
    for hours, sent, written, digest in calls:
        db.set_tick_report(conn, tick(conn, at(NOW, 0, hours), 0.1), "s", first_call(sent, written), digest=digest)
    dry = tick(conn, at(NOW, 0, 0.5), 0.1, dry_run=True)  # its first call is a live tick's
    db.set_tick_report(conn, dry, "s", first_call(61_000, 4_000), digest="new")
    before = tick(conn, at(NOW, 1), 0.1)  # before the window
    db.set_tick_report(conn, before, "s", first_call(10, 10), digest="new")
    tick(conn, at(NOW, 0, 0.25), 0.1)  # recorded before canopy kept the first call
    ticket(conn, "PROJ-1")
    run(conn, dry, "PROJ-1", at(NOW, 0, 1), 0.1, None)
    run_id = conn.execute("SELECT max(id) FROM runs").fetchone()[0]
    db.set_run_report(conn, "runs", run_id, "s", first_call(30_000, 1_000), digest="new")

    found = spend.breakdown(conn, NOW, 1)
    assert found.first_calls == [
        spend.FirstCalls("overseer", "old", 3, 51_000, 1 / 3, at(NOW, 0, 5), at(NOW, 0, 3)),
        spend.FirstCalls("overseer", "new", 3, 61_000, 1 / 3, at(NOW, 0, 2), at(NOW, 0, 0.5)),
        spend.FirstCalls("workers", "new", 1, 30_000, 0.0, at(NOW, 0, 1), at(NOW, 0, 1)),
    ]


def test_canopy_spend_json_has_the_first_calls(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    conn = canopy_env.journal()
    now = noon_today()
    db.set_tick_report(conn, tick(conn, at(now, 0), 0.1), "s", first_call(50_000, 49_000), digest="abc")
    assert main(["spend", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["first_calls"] == [
        {
            "kind": "overseer",
            "digest": "abc",
            "runs": 1,
            "first_call": 50_000,
            "cold_share": 1.0,
            "first_started": at(now, 0),
            "last_started": at(now, 0),
        }
    ]


def tools_journal(conn: sqlite3.Connection, now: datetime) -> None:
    """Tool calls of each kind of run in the window, a dry tick's among them, and of a tick before it."""
    usage = Usage(0.1, 0, 0, 0, 0, 0)
    reads = [ToolUse("github_pull_request_read", 3, 0, 40_000), ToolUse("bash", 2, 1, 900)]
    db.set_tick_report(conn, tick(conn, at(now, 0, 1), 0.1), "s", usage, tools=reads)
    db.set_tick_report(conn, tick(conn, at(now, 0, 2), 0.1, dry_run=True), "s", usage, tools=reads[:1])
    db.set_tick_report(conn, tick(conn, at(now, 9), 0.1), "s", usage, tools=[ToolUse("bash", 50, 0, 10**6)])
    ticket(conn, "PROJ-1")
    first = int(conn.execute("SELECT min(id) FROM ticks").fetchone()[0])
    run(conn, first, "PROJ-1", at(now, 0, 3), 0.1, None)
    run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
    db.set_run_report(conn, "runs", run_id, "s", usage, tools=[ToolUse("bash", 30, 4, 20_000)])
    conn.execute(
        "INSERT INTO chore_runs (chore, started_at, status, log_path) VALUES ('deps', ?, 'ok', 'l')", (at(now, 0),)
    )
    chore_id = int(conn.execute("SELECT max(id) FROM chore_runs").fetchone()[0])
    db.set_run_report(conn, "chore_runs", chore_id, "s", usage, tools=[ToolUse("read", 1, 0, 10)])
    review(conn, first, "https://e.test/pr/1", None, at(now, 0), 0.1)
    review_id = int(conn.execute("SELECT max(id) FROM review_runs").fetchone()[0])
    db.set_run_report(conn, "review_runs", review_id, "s", usage, tools=[ToolUse("bash", 1, 0, 900)])


def test_tools_are_by_kind_and_tool_the_most_returned_first(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    tools_journal(conn, NOW)
    found = spend.breakdown(conn, NOW, 1)
    assert found.tools == [
        # Both ticks' reads, the dry run's among them; not the tick before the window.
        spend.ToolSpend("overseer", "github_pull_request_read", 2, 6, 0, 80_000, 20_000),
        spend.ToolSpend("workers", "bash", 1, 30, 4, 20_000, 5_000),
        spend.ToolSpend("overseer", "bash", 1, 2, 1, 900, 225),  # a tie goes to the kinds' order
        spend.ToolSpend("reviews", "bash", 1, 1, 0, 900, 225),
        spend.ToolSpend("chores", "read", 1, 1, 0, 10, 2),
    ]
    assert spend.breakdown(conn, NOW - timedelta(days=30), 1).tools == []


def test_canopy_spend_prints_the_tools_that_returned_the_most(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = canopy_env.journal()
    now = noon_today()
    assert main(["spend"]) == 0
    assert "No tool call recorded." in capsys.readouterr().out.splitlines()

    tools_journal(conn, now)
    many = [ToolUse(f"mcp_{n}", 1, 0, n) for n in range(1, 11)]
    db.set_tick_report(conn, tick(conn, at(now, 0, 4), 0.1), "s", Usage(0.1, 0, 0, 0, 0, 0), tools=many)
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


@pytest.mark.parametrize("table", ["ticks", "runs", "chore_runs", "review_runs"])
def test_tools_read_only_the_windows_runs(tmp_path: Path, journals: Journals, table: str) -> None:
    """The run table leads, by its `started_at` index, so the window's cost is its own runs', not the whole history's.

    A journal in a test is too small for a slow plan to show in its time, so the plan is what is held.
    """
    conn = journals.open(tmp_path / "canopy.db")
    sql = spend._TOOLS_SQL.format(table=table)  # noqa: SLF001 (the query the plan is of)
    plan = [str(row[3]) for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", (table, at(NOW, 7), at(NOW, 0)))]
    assert plan[0].startswith(f"SEARCH r USING COVERING INDEX {table}_spent (started_at>? AND started_at<?)"), plan
    assert plan[1].startswith("SEARCH t USING PRIMARY KEY (run_table=? AND run_id=?)"), plan
