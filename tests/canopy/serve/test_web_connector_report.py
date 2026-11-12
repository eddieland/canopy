"""The web UI's Connectors report (DESIGN §11, §30): each source's runs by how they ended, and each source now.

Reads only.
"""

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from canopy.core import connector_runs, db, records, spend
from canopy.core.vocab import ConnectorRunStatus, SourceKind
from canopy.infra import resources
from canopy.serve.backend import Backend
from tests.canopy.helpers import context
from tests.canopy.web_helpers import client, signed_in_client
from tests.conftest import TRACKER_SOURCE, CanopyEnv

#: The source no longer configured, whose runs the journal keeps.
GONE = "linear"


def ran(
    conn: sqlite3.Connection,
    source: str,
    started: datetime,
    status: ConnectorRunStatus,
    *,
    minutes: float = 0.5,
    tick_id: int | None = None,
    kind: SourceKind = SourceKind.TRACKER,
    request: Mapping[str, object] | None = None,
    recorded: Mapping[str, int] | None = None,
    refused: Mapping[str, int] | None = None,
    stderr: str = "",
) -> int:
    """A run of `source` that started at `started` and took `minutes`, a tick's or a poll's; its id."""
    run = records.insert(
        records.ConnectorRun,
        tick_id=tick_id,
        source=source,
        kind=kind,
        started_at=db.format_time(started),
        ended_at=db.format_time(started + timedelta(minutes=minutes)),
        status=status,
        request=json.dumps(request or {"tickets": []}),
        recorded=json.dumps(recorded or {}),
        refused=json.dumps(refused or {}),
        missed=None if status is ConnectorRunStatus.OK else f"{source} read less",
        stderr=stderr,
    ).run(conn)
    assert run.lastrowid is not None
    return run.lastrowid


def test_the_connectors_report_counts_each_sources_runs_ticks_and_polls_alike(canopy_env: CanopyEnv) -> None:
    """A week of a tracker's, the vcs source's, and a source no longer configured's runs, each status among them."""
    canopy_env.configure(canopy_env.user_file, {"connect": {"sources": {TRACKER_SOURCE: {"timeout_minutes": 4}}}})
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    conn, now = ctx.conn, datetime.now(UTC)
    start, _ = spend.window(now, spend.DEFAULT_DAYS)

    # A time `days` local days into the window and `hours` past that midnight: two hours or more keep a run on its day
    # through a clock change in the week.
    def at(days: float, hours: float = 0) -> datetime:
        return start + timedelta(days=days, hours=hours)

    ok, partial, failed = ConnectorRunStatus.OK, ConnectorRunStatus.PARTIAL, ConnectorRunStatus.FAILED
    early, late = db.start_tick(conn, dry_run=False), db.start_tick(conn, dry_run=False)
    # Before both windows, then the week before: a partial that had a ticket line refused.
    ran(conn, TRACKER_SOURCE, at(-20), ok)
    ran(conn, TRACKER_SOURCE, at(-3), partial, refused={"ticket": 1})
    ran(conn, TRACKER_SOURCE, at(-2), ok)
    # The week: a source since removed failed, then the tracker's two ticks' runs and two polls, and the reader's poll.
    ran(conn, GONE, at(3, 2), failed, minutes=0)
    ran(conn, TRACKER_SOURCE, at(4, 2), ok, tick_id=early, recorded={"ticket": 3, "comment": 1})
    ran(conn, TRACKER_SOURCE, at(5, 2), ok, minutes=1.5, recorded={"ticket": 3})
    short = ran(
        conn,
        TRACKER_SOURCE,
        at(5, 3),
        partial,
        minutes=1,
        recorded={"ticket": 2},
        refused={"comment": 2},
        stderr="PROJ-1: the tracker answered 503",
    )
    ran(conn, "github", at(5, 4), ok, minutes=0.25, kind=SourceKind.VCS, request={"prs": []}, recorded={"pr": 1})
    stopped = ran(
        conn,
        TRACKER_SOURCE,
        at(6, 2),
        failed,
        minutes=4,
        tick_id=late,
        request={"tickets": [{"key": "PROJ-1"}]},
    )
    c, _ = signed_in_client(ctx)

    found = c.get("/api/reports/connectors").json()
    assert (found["days"], found["max_age_minutes"], found["journal_days"]) == (7, 30, 90)
    # Each source configured, in the order a tick runs them, then the one no longer configured.
    by = {r["source"]: r for r in found["runs"]}
    assert list(by) == [TRACKER_SOURCE, "github", GONE]
    tracker = by[TRACKER_SOURCE]
    assert {k: tracker[k] for k in ("runs", "ticks", "polls", "ok", "partial", "failed", "limit_minutes")} == {
        "runs": 4,
        "ticks": 2,
        "polls": 2,
        "ok": 2,
        "partial": 1,
        "failed": 1,
        "limit_minutes": 4,
    }
    assert (tracker["median_minutes"], tracker["p90_minutes"], tracker["longest_minutes"]) == (
        pytest.approx(1.25),
        pytest.approx(4),
        pytest.approx(4),
    )
    assert (tracker["recorded"], tracker["refused"]) == ({"comment": 1, "ticket": 8}, {"comment": 2})
    assert (by["github"]["kind"], by["github"]["limit_minutes"], by["github"]["recorded"]) == ("vcs", 2, {"pr": 1})
    assert (by[GONE]["failed"], by[GONE]["limit_minutes"]) == (1, None)
    # Each day, a count per source in the runs' order: the removed source's failure, the partial, and the tick's.
    assert [d["short"] for d in found["per_day"]] == [
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 1],
        [0, 0, 0],
        [1, 0, 0],
        [1, 0, 0],
    ]
    newest = [(r["id"], r["source"], r["status"], r["tick_id"]) for r in found["newest"]]
    assert newest[:2] == [(stopped, TRACKER_SOURCE, "failed", late), (short, TRACKER_SOURCE, "partial", None)]
    assert [r["source"] for r in found["newest"]] == [TRACKER_SOURCE, TRACKER_SOURCE, GONE]
    assert found["newest"][1]["stderr"] == "PROJ-1: the tracker answered 503"
    assert found["newest"][0]["minutes"] == pytest.approx(4)
    [refused] = found["refusals"]
    assert {k: refused[k] for k in ("source", "line", "lines", "runs")} == {
        "source": TRACKER_SOURCE,
        "line": "comment",
        "lines": 2,
        "runs": 1,
    }
    previous = found["previous"]
    assert previous["until"] == found["since"]
    assert (previous["runs"], previous["short"], previous["refused"]) == (2, 1, 1)
    # Each source now, as `canopy status` names it: the tracker's latest run asked about a ticket never observed.
    now_ = {s["name"]: s for s in found["sources"]}
    assert list(now_) == [TRACKER_SOURCE, "github"]
    assert {k: now_[TRACKER_SOURCE][k] for k in ("run_id", "tick_id", "status", "never", "stale")} == {
        "run_id": stopped,
        "tick_id": late,
        "status": "failed",
        "never": 1,
        "stale": True,
    }
    assert (now_["github"]["status"], now_["github"]["stale"], now_["github"]["tick_id"]) == ("ok", False, None)


def test_the_connectors_report_counts_the_mocks_four_days_of_runs(backend: Backend) -> None:
    """The mock's week: two sources' polls and ticks' runs, four of them short, and `jira` stale."""
    c = client(None, backend)
    found = c.get("/api/reports/connectors").json()
    assert (found["days"], found["since"], found["until"]) == (7, "2026-10-02T00:00:00Z", "2026-10-09T00:00:00Z")
    with backend.open() as ctx:
        expected = connector_runs.report(ctx.conn, ctx.config, backend.clock(), 7)
    assert [(r["source"], r["runs"], r["partial"], r["failed"]) for r in found["runs"]] == [
        (s.source, s.runs, s.partial, s.failed) for s in expected.sources
    ]
    assert [(r["source"], r["runs"], r["partial"], r["failed"]) for r in found["runs"]] == [
        ("jira", 194, 2, 0),
        ("github", 194, 1, 1),
    ]
    assert [r["id"] for r in found["newest"]] == [r.id for r in expected.newest]
    assert [d["short"] for d in found["per_day"]][-4:] == [[1, 0], [0, 1], [1, 0], [0, 1]]
    assert [(s["name"], s["stale"]) for s in found["sources"]] == [("jira", True), ("github", False)]
    assert c.get("/api/reports/connectors", params={"days": 30}).json()["days"] == 30
    assert c.get("/api/reports/connectors", params={"days": 0}).status_code == 422
    assert c.get("/api/reports/connectors", params={"days": spend.MAX_DAYS + 1}).status_code == 422
