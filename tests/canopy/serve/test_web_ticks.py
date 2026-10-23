"""The web UI's ticks (DESIGN §6, §22, ROADMAP M24). Reads only.

What `canopy decisions` prints, a tick's page, and each ticket's decisions across ticks.
"""

import re

import pytest

from canopy.core import db
from canopy.core import spend as spending
from canopy.core.context import Context
from canopy.loop import attention
from canopy.serve import tick_views
from canopy.serve.backend import Backend
from tests.canopy.helpers import present
from tests.canopy.web_helpers import client


def test_the_ticks_list_is_the_latest_newest_first_with_how_many_decisions_each(backend: Backend) -> None:
    c = client(None, backend)
    latest, first = c.get("/api/ticks").json()
    assert (latest["id"], latest["status"], latest["dry_run"], latest["decisions"]) == (2, "ok", False, 5)
    assert (latest["session_id"], latest["cost_usd"], latest["summary"]) == ("ses_tick2", 0.31, "mock tick")
    assert latest["canopy_version"] == "0.3.1"
    assert (first["id"], first["decisions"], first["summary"]) == (
        1,
        5,
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
    assert [d["subject"] for d in first] == ["ABC-102", "ABC-100 (web)", "ABC-099 (web)", "chore:deps", "api"]


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
        assert today["total"] == pytest.approx(db.spent_ever(ctx.conn))  # everything the mock journal holds
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
    assert [u["kind"] for u in found["unpriced"]] == ["overseer", "workers", "plans", "chores", "reviews", "tasks"]
    # The mock's plan runs are a kind of their own, not workers'.
    assert today["plans"] == pytest.approx(1.28)
    # What each ticket's and PR's own runs cost, the costliest first; the mock marked no ticket done.
    assert [(t["key"], t["runs"], t["reviews"], t["cost_usd"]) for t in found["tickets"]][:2] == [
        # ABC-099's feedback plan run among its three, which recorded no cost.
        ("ABC-099", 3, 2, pytest.approx(3.5)),
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
    # What each kind spent on each model, the most costly first, its runs no session named a model for last.
    assert [(m["kind"], m["model"], m["runs"], m["replies"]) for m in found["models"]][1:4] == [
        ("workers", "anthropic/claude-sonnet-4-5", 3, 186),
        ("workers", "anthropic/claude-opus-4-1", 1, 23),
        ("workers", None, 6, 0),  # ABC-099's feedback plan run among them
    ]
    assert found["models"][2]["cost_usd"] == pytest.approx(1.65)

    assert c.get("/api/spend/breakdown").json()["days"] == 7  # canopy spend's default
    assert c.get("/api/spend/breakdown", params={"days": 0}).status_code == 422
    assert c.get("/api/spend/breakdown", params={"days": 367}).status_code == 422
