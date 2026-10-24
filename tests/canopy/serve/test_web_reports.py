"""The web UI's reports (DESIGN §11): what each local month cost and got done. Reads only."""

import pytest

from canopy.core import monthly
from canopy.serve.backend import Backend
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
    assert found[0]["runs"] == 0
    assert found[0]["cost_usd"] is None
    assert len(c.get("/api/reports/monthly").json()["months"]) == monthly.DEFAULT_MONTHS
    assert c.get("/api/reports/monthly", params={"months": monthly.MAX_MONTHS + 1}).status_code == 422
    assert c.get("/api/reports/monthly", params={"months": 0}).status_code == 422
