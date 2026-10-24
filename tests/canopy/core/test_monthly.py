"""What each local month cost and got done (DESIGN §11): the reports page's months, over a journal by hand."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canopy.core import db, monthly, spend
from tests.canopy.helpers import in_zone
from tests.conftest import Journals

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
PR = "https://github.com/acme/api/pull/7"


def at(month: int, day: int, hour: int = 12) -> str:
    """A time in 2026, as the journal writes it."""
    return db.format_time(datetime(2026, month, day, hour, tzinfo=UTC))


def tick(conn: sqlite3.Connection, started: str, cost: float | None, *, tokens: int = 0) -> int:
    cursor = conn.execute(
        "INSERT INTO ticks (started_at, ended_at, status, cost_usd, tokens_input, tokens_output, tokens_cache_read) "
        "VALUES (?, ?, 'ok', ?, ?, ?, ?)",
        (started, started, cost, tokens, tokens // 10, tokens * 3),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def ticket(conn: sqlite3.Connection, key: str, *, done: bool = True) -> None:
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, title, done) VALUES (?, 'ws', ?, ?, ?, ?)",
        (key, at(8, 1), at(8, 1), f"Title of {key}", int(done)),
    )


def run(
    conn: sqlite3.Connection,
    tick_id: int,
    key: str,
    started: str,
    *,
    kind: str = "implement",
    status: str = "done",
    ended: str | None = None,
    cost: float | None = 1.0,
    pr: str | None = None,
) -> int:
    result = None if pr is None else json.dumps({"status": status, "prs": {"api": pr}})
    cursor = conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, status, result_json, log_path, "
        "cost_usd, tokens_input, tokens_output) VALUES (?, ?, ?, 'b', ?, ?, ?, ?, 'l', ?, 100, 20)",
        (tick_id, key, kind, started, ended or started, status, result, cost),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def decide(conn: sqlite3.Connection, tick_id: int, key: str, created: str, rationale: str = "merged") -> None:
    conn.execute(
        "INSERT INTO decisions (tick_id, ticket_key, action, rationale, created_at) VALUES (?, ?, 'done', ?, ?)",
        (tick_id, key, rationale, created),
    )


def said(
    conn: sqlite3.Connection,
    number: int,
    author: str,
    created: str,
    *,
    state: str | None,
    bot: bool = False,
) -> None:
    """A comment, or a review when `state` is given, on `PR`."""
    item = "comment" if state is None else "review"
    conn.execute(
        "INSERT INTO observed_reviews (pr_url, item, id, author, bot, state, created_at, body, thread_id, "
        "observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'b', ?, ?)",
        (PR, item, number, author, int(bot), state, created, None if state else f"t{number}", at(10, 8)),
    )


def test_the_months_are_local_calendar_months_the_oldest_first(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    tick(conn, at(9, 30, 23), 2.0)  # Sep 30 in UTC, Oct 1 in Tokyo
    tick(conn, at(10, 1, 12), 1.0)
    found = monthly.months(conn, NOW, 3)
    assert [m.month for m in found] == ["2026-08", "2026-09", "2026-10"]
    assert [m.cost_usd for m in found] == [None, 2.0, 1.0]
    assert found[0].since == at(8, 1, 0)
    assert found[-1].until == at(11, 1, 0)
    with in_zone("Asia/Tokyo"):
        tokyo = monthly.months(conn, NOW, 3)
    assert [m.cost_usd for m in tokyo] == [None, None, 3.0]
    # A year turns over between months.
    january = monthly.months(conn, datetime(2026, 1, 15, tzinfo=UTC), 3)
    assert [m.month for m in january] == ["2025-11", "2025-12", "2026-01"]


def test_a_months_kinds_carry_their_runs_cost_and_tokens(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    first = tick(conn, at(10, 2), 0.5, tokens=1000)
    tick(conn, at(9, 2), 0.25, tokens=1000)
    ticket(conn, "PROJ-1", done=False)
    run(conn, first, "PROJ-1", at(10, 3), cost=2.0)
    run(conn, first, "PROJ-1", at(10, 4), kind="plan", cost=None)
    conn.execute(
        "INSERT INTO chore_runs (chore, started_at, status, log_path, cost_usd, tokens_cache_write) "
        "VALUES ('deps', ?, 'ok', 'l', 0.75, 500)",
        (at(10, 5),),
    )
    conn.execute(
        "INSERT INTO run_models (run_table, run_id, model, replies, cost_usd) VALUES ('ticks', ?, 'opus', 3, 0.5)",
        (first,),
    )
    september, october = monthly.months(conn, NOW, 2)
    by_kind = {k.kind: k for k in october.kinds}
    assert [k.kind for k in october.kinds] == list(spend.KINDS)
    assert by_kind["overseer"].runs == 1
    assert by_kind["overseer"].tokens.cache_read == 3000
    assert by_kind["workers"].cost_usd == 2.0
    assert by_kind["plans"].runs == 1
    assert by_kind["plans"].cost_usd is None
    assert by_kind["chores"].tokens.cache_write == 500
    assert by_kind["reviews"].runs == 0
    assert october.cost_usd == pytest.approx(3.25)
    assert october.runs == 4
    assert october.tokens.input == 1000 + 100 + 100
    # Read from the cache over everything sent: 3000 of 1200 + 3000 + 500.
    assert october.tokens.cache_hit == pytest.approx(3000 / 4700)
    assert [(m.model, m.runs, m.cost_usd) for m in october.models] == [("opus", 1, 0.5), (None, 3, 2.75)]
    assert september.cost_usd == 0.25
    assert monthly.Tokens().cache_hit is None


def test_a_landed_ticket_counts_its_iterations_reviews_and_waits(tmp_path: Path, journals: Journals) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    t = tick(conn, at(9, 28), 1.0)
    ticket(conn, "PROJ-1")
    ticket(conn, "PROJ-2")
    ticket(conn, "PROJ-3")
    run(conn, t, "PROJ-1", at(9, 28, 9), kind="plan")
    run(conn, t, "PROJ-1", at(9, 28, 10), status="failed")
    run(conn, t, "PROJ-1", at(9, 29, 10), ended=at(9, 29, 11), pr=PR)
    run(conn, t, "PROJ-1", at(10, 2, 10), kind="resume", pr=PR)
    run(conn, t, "PROJ-1", at(10, 9, 10), kind="resume")  # after it landed: not counted
    conn.execute(
        "INSERT INTO observed_prs (url, repository, number, state, draft, author, observed_at) "
        "VALUES (?, 'acme/api', 7, 'merged', 0, 'operator', ?)",
        (PR, at(10, 8)),
    )
    said(conn, 1, "dana", at(9, 29, 9), state="commented")  # before the PR was ready
    said(conn, 2, "dana", at(9, 29, 15), state="changes_requested")
    said(conn, 3, "dana", at(9, 29, 15), state=None)
    said(conn, 4, "gina", at(10, 3), state="approved")
    said(conn, 5, "operator", at(9, 30), state=None)  # the author's, canopy's replies among them
    said(conn, 6, "ci-bot", at(9, 30), state=None, bot=True)
    decide(conn, t, "PROJ-1", at(10, 4, 11))
    decide(conn, t, "PROJ-2", at(10, 5), rationale=db.CLOSED_RATIONALE)
    decide(conn, t, "PROJ-3", at(9, 30))
    september, october = monthly.months(conn, NOW, 2)
    [landed] = october.landed
    assert landed.key == "PROJ-1"
    assert landed.title == "Title of PROJ-1"
    assert landed.iterations == 3
    assert landed.started_at == at(9, 28, 10)
    assert landed.to_land == timedelta(days=6, hours=1)
    assert landed.pr_comments == 1
    assert (landed.reviews, landed.changes_requested) == (3, 1)
    assert landed.review_wait == timedelta(hours=4)
    assert landed.cost_usd == 4.0  # the plan and three worker runs
    assert october.closed == 1
    assert october.pull_requests == 0  # first named in September
    assert september.pull_requests == 1
    # A ticket marked done with no worker run of its own.
    [bare] = september.landed
    assert (bare.key, bare.iterations, bare.to_land, bare.review_wait) == ("PROJ-3", 0, None, None)
    assert october.per_landed == pytest.approx(october.cost_usd)
    assert monthly.median([None, 3, 1, None]) == 2
    assert monthly.median([None]) is None
