"""The web UI's ticks (DESIGN §6, §22, ROADMAP M24). Reads only.

What `canopy decisions` prints, a tick's page, and each ticket's decisions across ticks.
"""

import re
from datetime import UTC, datetime, timedelta

import pytest

from canopy.core import db, runtime_sessions
from canopy.core import spend as spending
from canopy.core.context import Context
from canopy.core.vocab import RunKind
from canopy.loop import attention
from canopy.runtime.report import SessionPage, SessionSpend
from canopy.serve import tick_views
from canopy.serve.backend import Backend
from canopy.serve.mock import T0, history
from tests.canopy.helpers import present, worker_ran
from tests.canopy.web_helpers import client, signed_in_client


def test_the_ticks_list_is_the_latest_newest_first_with_how_many_decisions_each(backend: Backend) -> None:
    c = client(None, backend)
    latest, first = c.get("/api/ticks").json()
    assert (latest["id"], latest["status"], latest["dry_run"], latest["decisions"]) == (2, "ok", False, 5)
    assert (latest["session_id"], latest["cost_usd"], latest["summary"]) == ("ses_tick2", 0.31, "mock tick")
    assert latest["canopy_version"] == "0.3.1"
    # Tick 1 also records the history's `done` decisions, which no older tick can.
    assert (first["id"], first["decisions"], first["summary"]) == (
        1,
        5 + len(history.TICKETS),
        "dispatched 2, waiting on 1:\n- ABC-099 implement\n- ABC-103 implement",
    )
    # The header's tick carries the count too, so the stream sends it again as a running tick records decisions.
    assert c.get("/api/tick").json()["tick"]["decisions"] == 5


def test_a_tick_page_is_what_canopy_decisions_prints(backend: Backend) -> None:
    c = client(None, backend)
    page = c.get("/api/ticks/2").json()
    assert page["tick"]["id"] == 2
    # Where the overseer's output is, from the workspace root; tick 1 kept none. Its session is the transcript's.
    assert page["output_path"] == ".canopy/ticks/2.log"
    assert c.get("/api/ticks/1").json()["output_path"] is None
    shown = [(d["subject"], d["action"]) for d in page["decisions"]]
    assert shown == [
        ("ABC-102", "wait"),
        ("ABC-104", "refused:running"),
        ("ABC-101", "wait"),
        ("ABC-099 (web)", "attention:needs_reviewer"),
        ("pr:https://github.com/acme/api/pull/12", "wait"),
    ]
    # The overseer's text with its line breaks, for the UI to lay out; its markup is characters to show as text.
    assert page["decisions"][2]["rationale"] == (
        "run 41 is implementing it.\n  The ticket says <b>keep</b> the old route: left for the worker."
    )
    assert page["decisions"][3]["pr"] == "https://github.com/acme/web/pull/88"

    # Each subject is the CLI's, with a unit's repository after its ticket.
    with backend.open() as ctx:
        rows = db.decisions_for_tick(ctx.conn, 2)
    for row, shown_row in zip(rows, page["decisions"], strict=True):
        assert shown_row["subject"].startswith(attention.decided_about(row))

    first = c.get("/api/ticks/1").json()["decisions"]
    assert [d["subject"] for d in first[:5]] == ["ABC-102", "ABC-100 (web)", "ABC-099 (web)", "chore:deps", "api"]
    assert [d["action"] for d in first[5:]] == ["done"] * len(history.TICKETS)


def test_a_tick_page_names_the_ticks_either_side_dry_runs_included_and_steps_over_a_gap(ctx: Context) -> None:
    first, dry, gone, last = (db.start_tick(ctx.conn, dry_run=n == 1) for n in range(4))
    ctx.conn.execute("DELETE FROM ticks WHERE id = ?", (gone,))

    def neighbours(tick_id: int) -> tuple[int | None, int | None]:
        detail = present(tick_views.tick_detail(ctx, tick_id))
        return detail.previous_id, detail.next_id

    assert neighbours(first) == (None, dry)
    assert neighbours(dry) == (first, last)
    assert neighbours(last) == (dry, None)
    # The newest names the next tick once it starts, which the stream's tick invalidation reads again.
    after = db.start_tick(ctx.conn, dry_run=False)
    assert neighbours(last) == (dry, after)


def test_a_tick_page_names_the_models_that_served_its_overseer(backend: Backend) -> None:
    models = client(None, backend).get("/api/ticks/2").json()["models"]
    assert models == {
        "status": "found",
        "models": [{"model": "anthropic/claude-sonnet-4-5", "replies": 13, "cost_usd": 0.31}],
        "error": None,
    }


def test_a_tick_page_names_the_model_its_overseer_asked_for(backend: Backend) -> None:
    c = client(None, backend)
    assert c.get("/api/ticks/2").json()["model"] is None  # it asked for none, so the runtime's default served it
    with backend.open() as ctx:
        db.set_tick_model(ctx.conn, 2, "anthropic/claude-sonnet-4-5@high")
    assert c.get("/api/ticks/2").json()["model"] == "anthropic/claude-sonnet-4-5@high"


def test_no_such_tick_is_a_404_and_a_tick_id_is_a_positive_integer(backend: Backend) -> None:
    c = client(None, backend)
    missing = c.get("/api/ticks/99")
    assert (missing.status_code, missing.json()["detail"]) == (404, "no tick 99")
    assert c.get("/api/ticks/0").status_code == 422
    assert c.get("/api/ticks/two").status_code == 422


def test_a_ticket_page_lists_the_latest_decisions_about_it_across_ticks(backend: Backend) -> None:
    c = client(None, backend)
    decisions = c.get("/api/tickets/ABC-102").json()["decisions"]
    assert [(d["tick_id"], d["action"], d["rationale"]) for d in decisions] == [
        (2, "wait", "awaiting the operator's answer to message 5"),
        (1, "dispatch:implement", "started privately; implement the export button"),
    ]
    # A unit's decisions are the ticket's too.
    unit = c.get("/api/tickets/ABC-099").json()["decisions"]
    assert [(d["tick_id"], d["subject"]) for d in unit] == [(2, "ABC-099 (web)"), (1, "ABC-099 (web)")]
    assert c.get("/api/tickets/ABC-103").json()["decisions"] == []


def test_the_spend_breakdown_reads_the_last_24_hours_by_the_hour(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/spend/breakdown", params={"hours": 24}).json()
    by_days = c.get("/api/spend/breakdown", params={"days": 2}).json()
    assert (found["days"], found["hours"], len(found["per_day"])) == (None, 24, 24)
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}", d["day"]) for d in found["per_day"])
    # Every run in the mock journal started within the day, so the 24 hours hold what its two days do.
    assert found["totals"] == by_days["totals"]
    assert sum(d["costs"]["total"] or 0 for d in found["per_day"]) == pytest.approx(found["totals"]["total"])
    assert by_days["hours"] is None
    assert c.get("/api/spend/breakdown", params={"hours": 24, "days": 7}).status_code == 422
    assert c.get("/api/spend/breakdown", params={"hours": spending.MAX_HOURS + 1}).status_code == 422


def test_the_spend_breakdown_carries_the_window_before_its_own_in_days_or_hours(ctx: Context) -> None:
    """A run in the week, two in the week before, and one before both; the hours' window compares the same way."""
    conn, now = ctx.conn, datetime.now(UTC)
    start, _ = spending.window(now, 7)
    worker_ran(conn, RunKind.IMPLEMENT, db.format_time(start + timedelta(days=1)), cost=1.0)
    worker_ran(conn, RunKind.IMPLEMENT, db.format_time(start - timedelta(days=2)), cost=0.5)
    worker_ran(conn, RunKind.RESUME, db.format_time(start - timedelta(days=6)), cost=0.25)
    worker_ran(conn, RunKind.IMPLEMENT, db.format_time(start - timedelta(days=10)), cost=9.0)
    c, _ = signed_in_client(ctx)
    week = c.get("/api/spend/breakdown", params={"days": 7}).json()
    assert week["totals"]["workers"] == 1.0
    previous = week["previous"]
    assert (previous["until"], previous["totals"]["workers"], previous["totals"]["total"]) == (
        week["since"],
        0.75,
        0.75,
    )
    assert (previous["done"], previous["per_done"]) == (0, None)
    hours = c.get("/api/spend/breakdown", params={"hours": 24}).json()
    assert hours["previous"]["until"] == hours["since"]
    assert db.parse_time(hours["since"]) - db.parse_time(hours["previous"]["since"]) == timedelta(hours=24)


def test_the_spend_breakdown_carries_the_month_against_its_budget_whatever_the_window(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/spend/breakdown", params={"hours": 24}).json()["month"]
    # The mock's budget is $40, and every run in its journal that started in October started on its day, so the
    # month holds the day's runs alone.
    assert (found["month"], found["budget_usd"], found["since"]) == ("2026-10", 40, "2026-10-01T00:00:00Z")
    assert found["spent_usd"] == pytest.approx(c.get("/api/spend").json()["day"]["cost_usd"])
    assert found["projected_usd"] == pytest.approx(found["spent_usd"] / found["elapsed"])
    assert c.get("/api/spend/breakdown", params={"days": 30}).json()["month"] == found
    # The header's read carries the same month.
    assert c.get("/api/spend").json()["budget"] == found


def test_the_spend_counters_add_the_sessions_outside_canopy_and_say_when_they_were_read(backend: Backend) -> None:
    c = client(None, backend)
    before = c.get("/api/spend").json()
    assert before["sessions_read_at"] is None
    ms = int(T0.timestamp() * 1000)
    mine = SessionSpend("ses_mine", None, "/home/me/notes", ms, ms, 1.5, 1, 1, 0, 0, 0)
    with backend.open() as ctx:
        runtime_sessions.record(
            ctx.conn,
            SessionPage("found", (mine,), cursor=(ms, "ses_mine")),
            now=db.format_time(T0),
        )
    after = c.get("/api/spend").json()
    assert [after[w]["cost_usd"] - before[w]["cost_usd"] for w in ("day", "month")] == [pytest.approx(1.5)] * 2
    assert after["total_usd"] - before["total_usd"] == pytest.approx(1.5)
    assert after["sessions_read_at"] == "2026-10-08T12:00:00Z"
    found = c.get("/api/spend/breakdown", params={"days": 1}).json()
    assert found["totals"]["outside"] == 1.5
    assert found["sessions"]["outside"] == {"sessions": 1, "cost_usd": 1.5}
    assert found["sessions"]["directories"] == [{"directory": "/home/me/notes", "sessions": 1, "cost_usd": 1.5}]
    assert (found["sessions"]["read_at"], found["sessions"]["status"]) == ("2026-10-08T12:00:00Z", "found")
    month = found["month"]
    assert (month["outside_usd"], month["sessions_read_at"]) == (1.5, "2026-10-08T12:00:00Z")
    assert month["spent_usd"] == pytest.approx(month["runs_usd"] + 1.5)


def test_the_spend_breakdown_is_what_canopy_spend_prints_over_the_mock_journal(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/spend/breakdown", params={"days": 2}).json()
    assert (found["since"], found["days"]) == ("2026-10-07T00:00:00Z", 2)
    assert [d["day"] for d in found["per_day"]] == ["2026-10-07", "2026-10-08"]
    assert [d["start"] for d in found["per_day"]] == ["2026-10-07T00:00:00Z", "2026-10-08T00:00:00Z"]
    assert found["per_day"][0]["costs"]["total"] is None  # nothing the day before
    today = found["per_day"][1]["costs"]
    # Both ticks the loop ran, the second idle; the rest is the mock's runs, chore runs, and reviews.
    assert (today["overseer"], today["idle"], today["dry_run"]) == (pytest.approx(0.59), 0.31, None)
    assert today == found["totals"]
    with backend.open() as ctx:
        # Everything the mock journal holds but its months before T0.
        before = sum(r.cost_usd for t in history.TICKETS for r in t.runs)
        assert today["total"] + before == pytest.approx(db.spent_ever(ctx.conn))
    groups = {g["group"]: (g["ticks"], g["cost_usd"]) for g in found["ticks"]}
    assert (groups["idle"], groups["busy"], groups["hand_run"]) == ((1, 0.31), (1, 0.28), (0, None))
    assert found["idle_share"] == pytest.approx(0.31 / 0.59)
    assert sorted((w["by"], w["ticks"]) for w in found["woken"]) == [("start", 1), ("timer", 1)]
    # What idle spend bought, each opening its tick's page, with what the loop said of it, as every tick carries.
    assert [(t["id"], t["decisions"], t["idle"], t["woken_by"]) for t in found["idle_ticks"]] == [(2, 5, True, "timer")]
    assert [(t["id"], t["idle"], t["woken_by"]) for t in c.get("/api/ticks").json()] == [
        (2, True, "timer"),
        (1, False, "start"),
    ]
    # The ticks page's idle filter: the loop's idle ticks alone, as the spend page's Ticks panel links them.
    assert [t["id"] for t in c.get("/api/ticks", params={"idle": True}).json()] == [2]
    assert [u["kind"] for u in found["unpriced"]] == ["overseer", "workers", "plans", "chores", "reviews", "tasks"]
    # The mock's plan runs are a kind of their own, not workers'.
    assert today["plans"] == pytest.approx(1.28)
    # What each ticket's and PR's own runs cost, the costliest first; the mock marked no ticket done.
    assert [(t["key"], t["runs"], t["reviews"], t["cost_usd"]) for t in found["tickets"]][:2] == [
        # ABC-099's two feedback plan runs among its four, which recorded no cost.
        ("ABC-099", 4, 2, pytest.approx(3.5)),
        ("ABC-103", 1, 1, pytest.approx(1.86)),
    ]
    assert (found["done"], found["per_done"], found["tickets"][0]["done"]) == (0, None, None)
    assert [(p["url"], p["ticket_key"], p["phase"]) for p in found["pull_requests"]] == [
        ("https://github.com/acme/web/pull/88", "ABC-099", "review_pending"),
        ("https://github.com/acme/web/pull/91", "ABC-103", "review_pending"),
        ("https://github.com/acme/web/pull/86", "ABC-100", None),
        ("https://github.com/acme/api/pull/12", None, None),  # only reviewed
        ("https://github.com/acme/api/pull/14", None, None),  # only reviewed, at no cost reported
    ]
    # Which tools put the most into context: the overseer's PR reads, then the workers' shell calls.
    assert [(t["kind"], t["tool"], t["runs"], t["calls"], t["result_chars"]) for t in found["tools"]][:2] == [
        ("overseer", "github_pull_request_read", 2, 25, 325_000),
        ("workers", "bash", 4, 119, 279_000),
    ]
    assert found["tools"][0]["est_tokens"] == 325_000 // 4
    # What each kind spent on each model, the most costly first, its runs no session named a model for last: those
    # canopy has yet to read, then those read that named none.
    assert [(m["kind"], m["model"], m["unread"], m["runs"], m["replies"]) for m in found["models"]][1:5] == [
        ("workers", "anthropic/claude-sonnet-4-5", False, 3, 186),
        ("workers", "anthropic/claude-opus-4-1", False, 1, 23),
        ("workers", None, True, 5, 0),
        ("workers", None, False, 2, 0),  # ABC-099's feedback plan runs, which reported no session
    ]
    assert found["models"][2]["cost_usd"] == pytest.approx(1.65)

    assert c.get("/api/spend/breakdown").json()["days"] == 7  # canopy spend's default
    assert c.get("/api/spend/breakdown", params={"days": 0}).status_code == 422
    assert c.get("/api/spend/breakdown", params={"days": 367}).status_code == 422


def test_a_tickets_spend_by_model_is_its_own_runs_beside_the_workspaces(backend: Backend) -> None:
    """Spend's By model narrowed to a ticket, and the ticket page's worker models, are one read."""
    c = client(None, backend)
    workspace = c.get("/api/spend/breakdown", params={"days": 30}).json()
    found = c.get("/api/spend/breakdown", params={"days": 30, "ticket": "ABC-099"}).json()
    # Its workers' and reviews' runs alone, each beside the workspace's runs of its kind on its model.
    assert [(m["kind"], m["model"], m["unread"], m["runs"], m["workspace_runs"]) for m in found["models"]] == [
        ("workers", "anthropic/claude-opus-4-1", False, 1, 1),
        ("workers", "anthropic/claude-sonnet-4-5", False, 1, 10),
        ("workers", None, True, 1, 5),
        ("workers", None, False, 2, 10),
        ("reviews", "openai/gpt-5", False, 2, 4),
    ]
    assert (found["models"][1]["cost_usd"], found["models"][1]["workspace_cost_usd"]) == (0.66, pytest.approx(15.39))
    # Every other figure is the workspace's still, and the workspace's own rows have nothing beside them.
    assert (found["totals"], found["tickets"]) == (workspace["totals"], workspace["tickets"])
    assert {m["workspace_runs"] for m in workspace["models"]} == {None}
    # The ticket's page carries its workers' rows, as By model shows them for it at 30 days.
    workers = [m for m in found["models"] if m["kind"] == "workers"]
    assert c.get("/api/tickets/ABC-099").json()["worker_models"] == workers
    assert c.get("/api/spend/breakdown", params={"ticket": "NOPE-1"}).json()["models"] == []
    assert c.get("/api/spend/breakdown", params={"ticket": ""}).status_code == 422


def test_the_spend_breakdown_carries_each_kinds_first_calls_by_week_with_what_changed(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/spend/breakdown", params={"days": 30}).json()["first_call_weeks"]
    # The workers' own series runs back into the history's September, where a prompt change made a snapshot whose week
    # read little from the cache, and the runtime was upgraded the week after; the fixtures' week changed neither.
    workers = [w for w in found if (w["kind"], w["by"]) == ("workers", "kind")]
    assert [(w["week"], w["runs"], w["new_runtime_versions"], w["new_digests"]) for w in workers] == [
        ("2026-W37", 1, [], []),
        ("2026-W38", 2, [], []),
        ("2026-W39", 1, [], [history.SNAPSHOT]),
        ("2026-W40", 3, [history.RUNTIME], []),
        ("2026-W41", 6, [], []),
    ]
    assert [w["hit_rate"] for w in workers][2:4] == [pytest.approx(0.57, abs=0.001), pytest.approx(0.79, abs=0.001)]
    assert workers[2]["first_call"] == 22_400
    # Each kind's own series first, then its chores' and its models', the runs no single model served last.
    chores = [(w["by"], w["name"]) for w in found if w["kind"] == "chores"]
    assert chores == [
        ("kind", None),
        ("chore", "build-health"),
        ("chore", "deps"),
        ("model", "anthropic/claude-haiku-4-5"),
        ("model", None),
    ]
    assert list(dict.fromkeys(w["kind"] for w in found)) == list(spending.KINDS)
    # The week holds the fixtures' alone: a series' first week names no change, having none before it.
    week = c.get("/api/spend/breakdown").json()["first_call_weeks"]
    assert {w["week"] for w in week} == {"2026-W41"}
    assert not any(w["new_runtime_versions"] or w["new_digests"] for w in week)
