"""The web UI's reports (DESIGN §11): what each local month cost and got done. Reads only."""

import pytest

from canopy.core import db, monthly, runtime_sessions
from canopy.runtime.report import SessionPage, SessionSpend
from canopy.serve.backend import Backend
from canopy.serve.mock import T0, history
from tests.canopy.web_helpers import client


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
