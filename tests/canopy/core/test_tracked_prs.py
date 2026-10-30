"""The PRs canopy tracked in a window (DESIGN §11): each PR a run's result named, and the ticket that owns it."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from canopy.core import db, records, tracked_prs
from canopy.core.vocab import Phase, RunKind, RunStatus
from tests.canopy.helpers import earlier
from tests.conftest import Journals

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
PR_1 = "https://github.com/acme/web/pull/1"
PR_2 = "https://github.com/acme/api/pull/2"
PR_3 = "https://github.com/acme/web/pull/3"


def ran(conn: sqlite3.Connection, key: str, started: str, result: dict[str, object] | None) -> None:
    """A worker run on `key` that started at `started` and stored `result`."""
    db.touch_ticket(conn, key, "/ws")
    tick = records.insert(records.Tick, started_at=started, dry_run=0).run(conn).lastrowid
    assert tick is not None
    records.insert(
        records.Run,
        tick_id=tick,
        ticket_key=key,
        kind=RunKind.IMPLEMENT,
        branch=f"agent/{key}",
        started_at=started,
        status=RunStatus.DONE,
        result_json=None if result is None else json.dumps(result),
        log_path="l",
    ).run(conn)


def test_a_pr_is_tracked_from_the_first_run_that_named_it(tmp_path: Path, journals: Journals) -> None:
    """A window's PRs are those its runs named, each dated by the first run ever to name it, and owned by its unit."""
    conn = journals.open(tmp_path / "canopy.db")
    since, until = earlier(NOW, 7), earlier(NOW, -1)
    # Named before the window and again in it: tracked, from the first.
    ran(conn, "PROJ-1", earlier(NOW, 10), {"prs": {"web": PR_1}})
    ran(conn, "PROJ-1", earlier(NOW, 2), {"prs": {"web": PR_1, "api": PR_2}})
    # Named only before the window, only after it, by no URL, or by no result: none of them.
    ran(conn, "PROJ-2", earlier(NOW, 9), {"pr": PR_3})
    ran(conn, "PROJ-2", earlier(NOW, -2), {"pr": PR_3})
    ran(conn, "PROJ-3", earlier(NOW, 1), {"pr": "not a url"})
    ran(conn, "PROJ-3", earlier(NOW, 1), None)
    # PR 2's unit belongs to another ticket, which owns it, at its phase.
    db.touch_ticket(conn, "PROJ-9", "/ws")
    records.insert(records.TicketUnit, ticket_key="PROJ-9", repo="api", pr_url=PR_2, phase=Phase.CI_RED).run(conn)
    found = tracked_prs.tracked(conn, since, until)
    assert list(found.values()) == [
        tracked_prs.TrackedPr(url=PR_1, first_named=earlier(NOW, 10), ticket="PROJ-1", phase=None),
        tracked_prs.TrackedPr(url=PR_2, first_named=earlier(NOW, 2), ticket="PROJ-9", phase=Phase.CI_RED),
    ]


def test_an_empty_window_tracks_no_pr(tmp_path: Path, journals: Journals) -> None:
    """A window no run started in tracks nothing."""
    conn = journals.open(tmp_path / "canopy.db")
    assert tracked_prs.tracked(conn, earlier(NOW, 7), earlier(NOW, -1)) == {}
