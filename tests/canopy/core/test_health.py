"""How the loop's runs ended, and what its guards refused (DESIGN §11): `canopy health` over a journal by hand."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db, health
from canopy.core.vocab import RunKind
from canopy.infra import resources
from tests.canopy.helpers import context, earlier, in_zone
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
    for tick_id, action, kind, created in (
        (failed, "refused:capacity", "implement", earlier(now, 1)),
        (failed, "refused:capacity", "implement", earlier(now, 1)),
        (failed + 1, "refused:capacity", "resume", earlier(now, 1, 1)),
        (failed, "refused:cooldown", None, earlier(now, 1)),
        (before, "refused:cooldown", None, earlier(now, 9)),  # before the window
        (failed, "dispatch:implement", None, earlier(now, 1)),
    ):
        conn.execute(
            "INSERT INTO decisions (tick_id, ticket_key, action, rationale, kind, created_at) "
            "VALUES (?, 'PROJ-1', ?, 'r', ?, ?)",
            (tick_id, action, kind, created),
        )


def test_runs_are_by_kind_sort_and_status_with_their_cost(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_failures(conn, NOW)
    found = health.report(conn, NOW, 7)
    assert (found.since, found.until, found.days) == ("2026-10-02T00:00:00.000Z", "2026-10-09T00:00:00.000Z", 7)
    # Nothing before the window, and nothing still running.
    assert found.outcomes == [
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
    ]


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


def test_plan_runs_are_a_kind_of_their_own_with_old_triages_among_them(tmp_path: Path, journals: Journals) -> None:
    """A plan run (DESIGN §25) is a row of `runs`, but no worker's, nor is an old triage before a plan (M55)."""
    conn = journals.open(tmp_path / "canopy.db")
    t = tick(conn, earlier(NOW, 1), "ok")
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at) VALUES ('PROJ-1', 'ws', ?, ?)",
        (earlier(NOW, 1),) * 2,
    )
    for kind, status, cost in (("implement", "done", 2.0), ("needs-plan", "done", 0.05), ("plan", "timeout", 0.5)):
        conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, status, log_path, cost_usd) "
            "VALUES (?, 'PROJ-1', ?, '', ?, ?, 'l', ?)",
            (t, kind, earlier(NOW, 1), status, cost),
        )
    found = health.report(conn, NOW, 7)
    assert [(o.kind, o.what, o.status, o.failed, o.cost_usd) for o in found.outcomes if o.kind != "overseer"] == [
        ("workers", "implement", "done", False, 2.0),
        ("plans", "needs-plan", "done", False, 0.05),
        ("plans", "plan", "timeout", True, 0.5),
    ]
    assert [(f.kind, f.what, f.subject) for f in found.failures] == [("plans", "plan", "PROJ-1")]


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
    # Each with what it refused: by the ticket, chore, or PR named and the kind asked for, the most often first.
    implement = health.Ask("PROJ-1", None, None, RunKind.IMPLEMENT, decisions=2, last_tick=first)
    resume = health.Ask("PROJ-1", None, None, RunKind.RESUME, decisions=1, last_tick=first + 1)
    assert found.refusals == [
        health.Refusal("capacity", decisions=3, ticks=2, last_tick=first + 1, asks=[implement, resume]),
        health.Refusal(
            "cooldown",
            decisions=1,
            ticks=1,
            last_tick=first,
            asks=[health.Ask("PROJ-1", None, None, None, decisions=1, last_tick=first)],
        ),
    ]


def test_a_refusals_asks_are_the_few_most_often_refused_the_latest_first_among_ties(
    tmp_path: Path,
    journals: Journals,
) -> None:
    """A chore, a ticket, and a PR are each an ask of their own; past `ASKS`, the least refused are left out."""
    conn = journals.open(tmp_path / "canopy.db")
    named = [("PROJ-1", None, None)] * 3 + [(None, "deps", None)] * 2 + [(None, None, "https://e.test/pr/7")]
    named += [(f"PROJ-{n}", None, None) for n in range(2, 2 + health.ASKS)]
    for key, chore, pr in named:
        conn.execute(
            "INSERT INTO decisions (tick_id, ticket_key, chore, pr, action, rationale, created_at) "
            "VALUES (?, ?, ?, ?, 'refused:capacity', 'r', ?)",
            (tick(conn, earlier(NOW, 1), "ok"), key, chore, pr, earlier(NOW, 1)),
        )
    [refusal] = health.report(conn, NOW, 7).refusals
    assert refusal.decisions == len(named)
    asks = [(a.ticket, a.chore, a.pr, a.decisions) for a in refusal.asks]
    # Of those refused once, the latest first: the PR and the first tickets, asked before the last three, are left out.
    assert asks == [
        ("PROJ-1", None, None, 3),
        (None, "deps", None, 2),
        (f"PROJ-{1 + health.ASKS}", None, None, 1),
        (f"PROJ-{health.ASKS}", None, None, 1),
        (f"PROJ-{health.ASKS - 1}", None, None, 1),
    ]


def test_failures_are_grouped_by_the_harness_note_and_the_agents_words_as_other(
    tmp_path: Path,
    journals: Journals,
) -> None:
    """The harness's notes repeat, so they group, the most first; what an agent wrote never does, so it is `other`."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_failures(conn, NOW)
    found = health.report(conn, NOW, 7)
    # The tick's summary is canopy's; the timeout has no note, the chore's is not JSON, the review's is the agent's.
    assert [(c.note, c.runs, list(c.kinds), c.latest.kind, c.latest.what) for c in found.causes] == [
        ("nothing pushed", 1, ["workers"], "workers", "fix-ci"),
        ("overseer exited 1: no done line", 1, ["overseer"], "overseer", "live"),
        (None, 3, ["workers", "chores", "reviews"], "chores", "deps"),
    ]
    # Every failure of the window has a cause, past the newest few the report lists.
    assert sum(c.runs for c in found.causes) == len(found.failures)


def test_causes_count_every_failure_of_the_window_the_most_first(tmp_path: Path, journals: Journals) -> None:
    """More failures than the report lists are all counted, by note, the newest first among causes of as many runs."""
    conn = journals.open(tmp_path / "canopy.db")
    for n in range(health.FAILURES + 5):
        tick(conn, earlier(NOW, 0, n / 10), "abandoned", summary="the tick was abandoned")
    tick(conn, earlier(NOW, 0, 4), "error", summary="ValueError: x")
    tick(conn, earlier(NOW, 0, 5), "error", summary="KeyError: y")
    found = health.report(conn, NOW, 1)
    assert len(found.failures) == health.FAILURES
    assert [(c.note, c.runs) for c in found.causes] == [
        ("the tick was abandoned", health.FAILURES + 5),
        ("ValueError: x", 1),
        ("KeyError: y", 1),
    ]
    assert found.causes[0].latest == found.failures[0]


def test_an_empty_window_has_nothing(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_failures(conn, NOW)
    found = health.report(conn, NOW - timedelta(days=30), 1)
    assert (found.outcomes, found.failures, found.refusals, found.causes) == ([], [], [], [])


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
    causes = out.index("Failures by cause:")
    assert out[causes + 1].split() == ["1", "nothing", "pushed"]
    assert out[causes + 2].startswith("    workers; latest run:")
    assert out[causes + 5].split() == ["3", "other:", "an", "agent's", "summary,", "or", "no", "note"]
    assert out[causes + 6].startswith("    workers, chores, reviews; latest chore:deps run ")
    assert out[-3] == "Refused by a guard:"
    assert out[-2].startswith("  capacity: 3 times in 2 ticks, last in tick ")


def test_canopy_health_on_an_empty_journal(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["health", "--days", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1:] == ["", "No tick or run ended."]


def test_canopy_health_json_is_the_report(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    journal_of_failures(canopy_env.journal(), datetime.now(UTC))
    assert main(["health", "--json", "--days", "3"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    # A value to a line, so an agent's file tools, which cut a long line, read all of a report too long to print whole.
    assert all(line.count('": ') <= 1 for line in out.splitlines())
    assert data["days"] == 3
    timeout = {"kind": "workers", "what": "implement", "status": "timeout", "failed": True, "runs": 1, "cost_usd": 3.0}
    assert timeout in data["outcomes"]
    assert data["failures"][0]["note"] == "nothing pushed"
    assert {k: v for k, v in data["refusals"][0].items() if k not in {"last_tick", "asks"}} == {
        "guard": "capacity",
        "decisions": 3,
        "ticks": 2,
    }
    assert [(a["kind"], a["decisions"]) for a in data["refusals"][0]["asks"]] == [("implement", 2), ("resume", 1)]
    assert [(c["note"], c["runs"]) for c in data["causes"]][-1] == (None, 3)


def test_canopy_health_reads_at_most_a_year(canopy_env: CanopyEnv) -> None:
    assert main(["health", "--days", "0"]) == 2
    assert main(["health", "--days", "367"]) == 2


def test_by_day_counts_each_kinds_ended_and_failed_runs_on_its_local_day(tmp_path: Path, journals: Journals) -> None:
    """Each day of the window counts the runs that started on it and ended, and the failed among them, by kind."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_failures(conn, NOW)
    found = health.by_day(conn, NOW, 7)
    assert [d.day for d in found] == [f"2026-10-0{n}" for n in range(2, 9)]
    assert found[0].start == "2026-10-02T00:00:00.000Z"
    ended = {d.day: {k: n for k, n in d.ended.items() if n} for d in found}
    failed = {d.day: {k: n for k, n in d.failed.items() if n} for d in found}
    # Nothing before the window, nothing still running; a worker that asked a question ended but did not fail.
    assert ended == {
        "2026-10-02": {},
        "2026-10-03": {},
        "2026-10-04": {},
        "2026-10-05": {},
        "2026-10-06": {"overseer": 2, "workers": 1},
        "2026-10-07": {"overseer": 2, "workers": 1, "chores": 1},
        "2026-10-08": {"workers": 2, "chores": 1, "reviews": 1},
    }
    assert failed == {
        "2026-10-02": {},
        "2026-10-03": {},
        "2026-10-04": {},
        "2026-10-05": {},
        "2026-10-06": {},
        "2026-10-07": {"overseer": 1, "workers": 1},
        "2026-10-08": {"workers": 1, "chores": 1, "reviews": 1},
    }
    # Every kind is counted on every day, 0 for none, and the days add up to the outcomes.
    assert all(set(d.ended) == set(d.failed) == set(health.spend.KINDS) for d in found)
    outcomes = health.report(conn, NOW, 7).outcomes
    assert sum(sum(d.ended.values()) for d in found) == sum(o.runs for o in outcomes)
    assert sum(sum(d.failed.values()) for d in found) == sum(o.runs for o in outcomes if o.failed)


def test_by_day_of_an_empty_window_lists_each_day_at_nothing(tmp_path: Path, journals: Journals) -> None:
    """A window with no runs still lists its days, each at 0."""
    conn = journals.open(tmp_path / "canopy.db")
    found = health.by_day(conn, NOW, 3)
    assert [d.day for d in found] == ["2026-10-06", "2026-10-07", "2026-10-08"]
    assert all(not any(d.ended.values()) and not any(d.failed.values()) for d in found)


def test_by_day_counts_a_run_on_the_local_day_it_started(tmp_path: Path, journals: Journals) -> None:
    """A run at 02:00 UTC is the evening before in New York, and counts on that day."""
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, "2026-10-08T02:00:00.000Z", "overseer_failed")
    with in_zone("America/New_York"):
        found = health.by_day(conn, NOW, 2)
    assert [(d.day, d.failed["overseer"]) for d in found] == [("2026-10-07", 1), ("2026-10-08", 0)]


def journal_of_lengths(conn: sqlite3.Connection, now: datetime) -> None:
    """A tick, worker runs near their limit and past it, and chores with a timeout of their own and without one."""
    t = tick(conn, earlier(now, 1), "ok")
    conn.execute("UPDATE ticks SET ended_at = ? WHERE id = ?", (later(earlier(now, 1), 3), t))
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at) VALUES ('PROJ-1', 'ws', ?, ?)",
        (earlier(now, 9),) * 2,
    )
    for started, kind, status, minutes in (
        (earlier(now, 9), "implement", "done", 1.0),  # before the window
        (earlier(now, 2), "implement", "done", 10.0),
        (earlier(now, 2, 1), "implement", "done", 40.0),
        (earlier(now, 1, 1), "implement", "timeout", 46.0),
        (earlier(now, 1, 2), "resume", "done", 5.0),
        (earlier(now, 0), "resume", "running", None),
    ):
        conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, status, log_path) "
            "VALUES (?, 'PROJ-1', ?, 'agent/PROJ-1', ?, ?, ?, 'l')",
            (t, kind, started, None if minutes is None else later(started, minutes), status),
        )
    for chore, minutes in (("deps", 9.0), ("gone", 2.0)):
        started = earlier(now, 1, 3)
        conn.execute(
            "INSERT INTO chore_runs (tick_id, chore, started_at, ended_at, status, log_path) "
            "VALUES (NULL, ?, ?, ?, 'ok', 'l')",
            (chore, started, later(started, minutes)),
        )


def later(at: str, minutes: float) -> str:
    """The journal time `minutes` after `at`."""
    return db.format_time(db.parse_time(at) + timedelta(minutes=minutes))


def test_durations_are_by_kind_and_sort_against_each_timeout(canopy_env: CanopyEnv) -> None:
    """A worker near its limit, one past it, a tick, and a chore held to its own timeout, or none once it is gone."""
    canopy_env.append_user('\n[chores.deps]\nprompt = "~/deps.md"\nevery_minutes = 60\ntimeout_minutes = 10\n')
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    journal_of_lengths(ctx.conn, NOW)
    found = health.durations(ctx.conn, NOW, 7, ctx.config)
    rows = [
        (d.kind, d.what, d.runs, round(d.median_minutes, 3), round(d.p90_minutes, 3), round(d.longest_minutes, 3))
        for d in found
    ]
    # Nothing before the window, and nothing still running.
    assert rows == [
        ("overseer", "live", 1, 3.0, 3.0, 3.0),
        ("workers", "implement", 3, 40.0, 46.0, 46.0),
        ("workers", "resume", 1, 5.0, 5.0, 5.0),
        ("chores", "deps", 1, 9.0, 9.0, 9.0),
        ("chores", "gone", 1, 2.0, 2.0, 2.0),
    ]
    limits = {d.what: (d.timeouts, d.limit_minutes, d.bins) for d in found}
    assert limits == {
        # The overseer's, the worker's, and the chore's own defaults and settings.
        "live": (0, 15, health.Bins(under_quarter=1)),
        # 10 of 45 minutes, 40 of them, and past them.
        "implement": (1, 45, health.Bins(under_quarter=1, under_limit=1, over_limit=1)),
        "resume": (0, 45, health.Bins(under_quarter=1)),
        "deps": (0, 10, health.Bins(under_limit=1)),
        # A chore no longer configured has no limit to hold it to.
        "gone": (0, None, None),
    }


def test_durations_of_an_empty_window_are_none(canopy_env: CanopyEnv) -> None:
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    journal_of_lengths(ctx.conn, NOW)
    assert health.durations(ctx.conn, NOW - timedelta(days=30), 1, ctx.config) == []


def test_canopy_health_prints_the_durations(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    """Each sort's lengths and its limit, a median past three quarters of it flagged."""
    journal_of_lengths(canopy_env.journal(), datetime.now(UTC))
    assert main(["health"]) == 0
    out = capsys.readouterr().out.splitlines()
    lengths = out.index("How long they took, in minutes (! a median past three quarters of the timeout):")
    words = [line.split() for line in out[lengths + 1 : lengths + 7]]
    assert words == [
        ["kind", "what", "median", "p90", "longest", "timeouts", "limit"],
        ["overseer", "live", "3.0", "3.0", "3.0", "0", "15"],
        ["workers", "implement", "40.0", "!", "46.0", "46.0", "1", "45"],
        ["workers", "resume", "5.0", "5.0", "5.0", "0", "45"],
        ["chores", "deps", "9.0", "9.0", "9.0", "0", "-"],
        ["chores", "gone", "2.0", "2.0", "2.0", "0", "-"],
    ]
    assert main(["health", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [(d["what"], d["timeouts"], d["limit_minutes"]) for d in data["durations"]][1] == ("implement", 1, 45)
