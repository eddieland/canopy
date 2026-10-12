"""The web UI's ticks (DESIGN §6, §22, ROADMAP M24): what `canopy decisions` prints, a tick's page, and each ticket's
decisions across ticks. Reads only."""

from pathlib import Path

import pytest

from canopy.core import db
from canopy.loop import attention
from canopy.serve import mock
from canopy.serve.backend import Backend
from tests.canopy.test_serve import client


@pytest.fixture
def backend(tmp_path: Path) -> Backend:
    return mock.seed(tmp_path / "mock")


def test_the_ticks_list_is_the_latest_newest_first_with_how_many_decisions_each(backend: Backend) -> None:
    c = client(None, backend)
    latest, first = c.get("/api/ticks").json()
    assert (latest["id"], latest["status"], latest["dry_run"], latest["decisions"]) == (2, "ok", False, 5)
    assert (latest["session_id"], latest["cost_usd"], latest["summary"]) == ("ses_tick2", 0.31, "mock tick")
    assert (first["id"], first["decisions"], first["summary"]) == (1, 5, "dispatched 2, waiting on 1")
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
    # The overseer's text on one line, as the CLI prints it; its markup is characters for the UI to show as text.
    assert page["decisions"][2]["rationale"] == (
        "run 41 is implementing it. The ticket says <b>keep</b> the old route: left for the worker."
    )
    assert page["decisions"][3]["pr"] == "https://github.com/acme/web/pull/88"

    # Each subject is the CLI's, with a unit's repository after its ticket.
    with backend.open() as ctx:
        rows = db.decisions_for_tick(ctx.conn, 2)
    for row, shown_row in zip(rows, page["decisions"], strict=True):
        assert shown_row["subject"].startswith(attention.decided_about(row))

    first = c.get("/api/ticks/1").json()["decisions"]
    assert [d["subject"] for d in first] == ["ABC-102", "ABC-100 (web)", "ABC-099 (web)", "chore:deps", "api"]


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
