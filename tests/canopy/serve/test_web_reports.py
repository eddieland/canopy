"""The web UI's reports (DESIGN §11, §42): what each local month cost and got done, the checklist, and health.

Reads only.
"""

from datetime import UTC, datetime

import pytest

from canopy.core import db, health, runtime_sessions, spend
from canopy.core.context import Context
from canopy.runtime.report import SessionPage, SessionSpend
from canopy.serve import monthly
from canopy.serve.backend import Backend
from canopy.serve.mock import T0, history
from tests.canopy.helpers import journal_of_answers
from tests.canopy.web_helpers import client, signed_in_client


def test_the_monthly_report_reads_local_months_oldest_first(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/reports/monthly", params={"months": 3}).json()["months"]
    assert [m["month"] for m in found] == ["2026-08", "2026-09", "2026-10"]
    assert found[0]["since"] == "2026-08-01T00:00:00Z"
    # October holds what the spend's month against its budget does, dry runs included, kind by kind.
    october = found[-1]
    spent = c.get("/api/spend/breakdown", params={"days": 30}).json()["month"]["spent_usd"]
    assert october["cost_usd"] == pytest.approx(spent)
    assert [k["kind"] for k in october["kinds"]] == ["overseer", "workers", "plans", "chores", "reviews", "tasks"]
    assert sum(k["cost_usd"] or 0 for k in october["kinds"]) == pytest.approx(october["cost_usd"])
    assert october["tokens"]["cache_read"] == sum(k["tokens"]["cache_read"] for k in october["kinds"])
    assert 0 < october["tokens"]["cache_hit"] < 1
    assert october["models"]
    # The months before hold the history's worker runs and the tickets they landed, the latest first.
    august = found[0]
    assert [k["kind"] for k in august["kinds"] if k["runs"]] == ["workers"]
    landed = [t for t in history.TICKETS if t.done_at.month == 8 and not t.closed]
    assert [t["key"] for t in august["landed"]] == [t.key for t in reversed(landed)]
    # The mock's reader kept none of GitHub's times, so each figure is its proxy's.
    assert {(t["merged_at"], t["awaiting_review_at"]) for t in august["landed"]} == {(None, None)}
    year = c.get("/api/reports/monthly").json()["months"]
    assert len(year) == monthly.DEFAULT_MONTHS
    # The workspace took canopy up in April: nothing before.
    assert (year[0]["month"], year[0]["runs"], year[0]["cost_usd"]) == ("2025-11", 0, None)
    assert c.get("/api/reports/monthly", params={"months": monthly.MAX_MONTHS + 1}).status_code == 422
    assert c.get("/api/reports/monthly", params={"months": 0}).status_code == 422


def test_each_month_counts_the_sessions_outside_canopy_as_the_budget_does(backend: Backend) -> None:
    c = client(None, backend)
    before = c.get("/api/reports/monthly", params={"months": 1}).json()
    assert before["sessions_read_at"] is None
    assert before["months"][0]["outside"]["sessions"] == 0
    ms = int(T0.timestamp() * 1000)
    mine = SessionSpend("ses_mine", None, "/home/me/notes", ms, ms, 1.5, 100, 20, 5, 300, 40)
    with backend.open() as ctx:
        runtime_sessions.record(
            ctx.conn,
            SessionPage("found", (mine,), cursor=(ms, "ses_mine")),
            now=db.format_time(T0),
        )
    after = c.get("/api/reports/monthly", params={"months": 1}).json()
    [october] = after["months"]
    assert (october["outside"]["sessions"], october["outside"]["cost_usd"]) == (1, 1.5)
    assert october["cost_usd"] - before["months"][0]["cost_usd"] == pytest.approx(1.5)
    assert october["tokens"]["input"] - before["months"][0]["tokens"]["input"] == 100
    assert october["per_landed_usd"] == before["months"][0]["per_landed_usd"]
    assert after["sessions_read_at"] == "2026-10-08T12:00:00Z"
    spent = c.get("/api/spend/breakdown", params={"days": 30}).json()["month"]["spent_usd"]
    assert october["cost_usd"] == pytest.approx(spent)


def test_the_checklist_counts_each_repositorys_items_as_the_cli_does(ctx: Context) -> None:
    """Per repository and item over the last local days, `repo` narrowing it; a held item's reason is never sent."""
    journal_of_answers(ctx.conn, datetime.now(UTC))
    c, _ = signed_in_client(ctx)
    found = c.get("/api/reports/checklist").json()
    assert (found["days"], found["repo"]) == (spend.DEFAULT_DAYS, None)
    assert found["since"] < found["until"]
    columns = ("repo", "item", "reminded", "passed", "fixed", "held", "not_applicable", "unanswered")
    assert [tuple(row[k] for k in columns) for row in found["items"]] == [
        ("api", "general-types", 3, 2, 1, 0, 0, 0),
        ("api", "newspaper", 3, 0, 1, 1, 1, 0),
        ("api", "doc-comments", 3, 1, 0, 0, 0, 2),
        ("web", "no-any", 1, 0, 0, 1, 0, 0),
    ]
    assert "Its reason." not in c.get("/api/reports/checklist", params={"days": 30}).text
    today = c.get("/api/reports/checklist", params={"days": 1}).json()
    assert [(row["item"], row["reminded"]) for row in today["items"]] == [
        ("general-types", 1),
        ("newspaper", 1),
        ("doc-comments", 1),
        ("no-any", 1),
    ]
    web = c.get("/api/reports/checklist", params={"repo": "web"}).json()
    assert (web["repo"], [row["item"] for row in web["items"]]) == ("web", ["no-any"])
    assert c.get("/api/reports/checklist", params={"repo": "docs"}).json()["items"] == []
    for bad in ({"days": 0}, {"days": spend.MAX_DAYS + 1}, {"repo": "Not a repo"}):
        assert c.get("/api/reports/checklist", params=bad).status_code == 422


def test_the_mock_counts_its_two_lists(backend: Backend) -> None:
    """`api`'s list in its order, answered by ABC-102's run, then `web`'s, by T0's four ended worker runs in it."""
    found = client(None, backend).get("/api/reports/checklist").json()
    assert [(row["repo"], row["item"], row["reminded"]) for row in found["items"]] == [
        ("api", "general-types", 1),
        ("api", "newspaper-order", 1),
        ("api", "doc-comments", 1),
        ("api", "migration-companion", 1),
        ("web", "no-fixed-sleeps", 4),
        ("web", "query-keys", 4),
        ("web", "no-any", 4),
        ("web", "i18n-strings", 4),
    ]


def test_the_health_report_is_canopy_healths_with_each_days_failures(backend: Backend) -> None:
    """The health report holds what `canopy health` reads, with every day's ended and failed runs beside it."""
    c = client(None, backend)
    found = c.get("/api/reports/health").json()
    assert found["days"] == 7
    assert found["since"] == "2026-10-02T00:00:00Z"
    assert found["until"] == "2026-10-09T00:00:00Z"
    with backend.open() as ctx:
        expected = health.report(ctx.conn, backend.clock(), 7)
    assert [(o["kind"], o["what"], o["status"], o["runs"]) for o in found["outcomes"]] == [
        (o.kind, o.what, o.status, o.runs) for o in expected.outcomes
    ]
    assert [(f["kind"], f["id"]) for f in found["failures"]] == [(f.kind, f.id) for f in expected.failures]
    assert [r["guard"] for r in found["refusals"]] == [r.guard for r in expected.refusals]
    # Every day of the window, and the days add up to the outcomes.
    assert [d["day"] for d in found["per_day"]] == [f"2026-10-0{n}" for n in range(2, 9)]
    ended = sum(sum(d["ended"].values()) for d in found["per_day"])
    failed = sum(sum(d["failed"].values()) for d in found["per_day"])
    assert ended == sum(o.runs for o in expected.outcomes)
    assert failed == sum(o.runs for o in expected.outcomes if o.failed)
    assert failed > 0
    assert [u["kind"] for u in found["unpriced"]] == ["overseer", "workers", "plans", "chores", "reviews", "tasks"]
    assert c.get("/api/reports/health", params={"days": 30}).json()["days"] == 30
    assert c.get("/api/reports/health", params={"days": 0}).status_code == 422
    assert c.get("/api/reports/health", params={"days": spend.MAX_DAYS + 1}).status_code == 422


def test_a_health_failure_names_what_it_was_about_by_its_kind(backend: Backend) -> None:
    """A failure carries its ticket, PR, chore, or task apart, rather than one subject to parse."""
    c = client(None, backend)
    failures = c.get("/api/reports/health", params={"days": 30}).json()["failures"]
    assert failures
    for f in failures:
        named = {k for k in ("ticket", "pr_url", "chore", "task_id") if f[k] is not None}
        assert (
            named
            == {
                "overseer": set(),
                "workers": {"ticket"},
                "plans": {"ticket"},
                "chores": {"chore"},
                "reviews": {"pr_url"},
                "tasks": {"task_id"},
            }[f["kind"]]
        )
