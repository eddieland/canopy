"""Which models served each agent run (DESIGN §13): which runs' sessions are due to be read, and what a read records."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canopy.core import db, run_models
from canopy.core.run_models import MAX_ATTEMPTS, RETRY_AFTER, Due
from canopy.core.vocab import ModelsRead
from canopy.infra import resources
from canopy.runtime.report import ModelUse
from tests.conftest import Journals

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path, journals: Journals) -> sqlite3.Connection:
    conn = journals.open(tmp_path / db.DB_FILE_NAME)
    db.migrate(conn, resources.migrations_dir())
    conn.execute("INSERT INTO tickets (key, repo, first_seen_at, last_seen_at) VALUES ('PROJ-1', 'ws', 'x', 'x')")
    return conn


def at(hours: float) -> str:
    """`hours` before NOW, as the journal writes it."""
    return db.format_time(NOW - timedelta(hours=hours))


def tick(conn: sqlite3.Connection, started: str, session: str | None, *, ended: bool = True) -> int:
    cursor = conn.execute(
        "INSERT INTO ticks (started_at, ended_at, dry_run, status, session_id) VALUES (?, ?, 0, ?, ?)",
        (started, started if ended else None, "ok" if ended else "running", session),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def worker(conn: sqlite3.Connection, tick_id: int, started: str, session: str | None, *, ended: bool = True) -> int:
    cursor = conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, status, log_path, session_id) "
        "VALUES (?, 'PROJ-1', 'implement', 'b', ?, ?, ?, 'l', ?)",
        (tick_id, started, started if ended else None, "done" if ended else "running", session),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def chore(conn: sqlite3.Connection, started: str, session: str) -> int:
    cursor = conn.execute(
        "INSERT INTO chore_runs (chore, started_at, ended_at, status, log_path, session_id) "
        "VALUES ('deps', ?, ?, 'ok', 'l', ?)",
        (started, started, session),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def review(conn: sqlite3.Connection, tick_id: int, started: str, session: str) -> int:
    cursor = conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, started_at, ended_at, status, log_path, session_id) "
        "VALUES (?, 'https://e.test/pr/7', 'abc', ?, ?, 'done', 'l', ?)",
        (tick_id, started, started, session),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def due(conn: sqlite3.Connection, limit: int = 10, now: datetime = NOW) -> list[tuple[str, int, str, int]]:
    return [(d.run_table, d.run_id, d.session_id, d.attempts) for d in run_models.due(conn, limit=limit, now=now)]


def test_every_kind_of_run_that_ended_with_a_session_is_due_the_newest_first(conn: sqlite3.Connection) -> None:
    first = tick(conn, at(50), "ses_t1")
    tick(conn, at(1), None)  # printed no session: nothing to read
    tick(conn, at(0), "ses_t2", ended=False)  # still running
    w = worker(conn, first, at(40), "ses_w")
    worker(conn, first, at(0.5), "ses_wr", ended=False)
    c = chore(conn, at(30), "ses_c")
    r = review(conn, first, at(20), "ses_r")
    assert due(conn) == [
        ("review_runs", r, "ses_r", 0),
        ("chore_runs", c, "ses_c", 0),
        ("runs", w, "ses_w", 0),
        ("ticks", first, "ses_t1", 0),
    ]
    assert due(conn, limit=2) == due(conn)[:2]


def test_a_found_or_missing_run_is_read_once(conn: sqlite3.Connection) -> None:
    first = tick(conn, at(5), "ses_t")
    w = worker(conn, first, at(4), "ses_w")
    [run, overseer] = run_models.due(conn, limit=10, now=NOW)
    run_models.record(conn, run, ModelsRead.FOUND, [ModelUse("anthropic/claude-x", 3, 0.5)])
    run_models.record(conn, overseer, ModelsRead.MISSING)
    assert due(conn) == []
    assert [(m.model, m.replies, m.cost_usd) for m in run_models.of_run(conn, "runs", w)] == [
        ("anthropic/claude-x", 3, 0.5),
    ]
    assert run_models.of_run(conn, "ticks", first) == []


def test_a_failed_read_is_due_again_a_day_later_after_runs_never_read(conn: sqlite3.Connection) -> None:
    first = tick(conn, at(5), "ses_t")
    [overseer] = run_models.due(conn, limit=10, now=NOW)
    run_models.record(conn, overseer, ModelsRead.FAILED, error="opencode is not on PATH")
    assert due(conn) == []  # read just now, by the clock the journal stamps
    later = datetime.now(UTC) + RETRY_AFTER + timedelta(minutes=1)
    w = worker(conn, first, at(10), "ses_w")
    # Never read goes first, however old.
    assert due(conn, now=later) == [("runs", w, "ses_w", 0), ("ticks", first, "ses_t", 1)]


def test_a_run_whose_reads_keep_failing_stops_being_read(conn: sqlite3.Connection) -> None:
    tick(conn, at(5), "ses_t")
    later = datetime.now(UTC)
    for _ in range(MAX_ATTEMPTS):
        later += RETRY_AFTER + timedelta(minutes=1)
        [overseer] = run_models.due(conn, limit=10, now=later)
        run_models.record(conn, overseer, ModelsRead.FAILED, error="timed out")
    assert due(conn, now=later + RETRY_AFTER * 2) == []
    [(attempts, error)] = conn.execute("SELECT attempts, error FROM run_model_reads").fetchall()
    assert (attempts, error) == (MAX_ATTEMPTS, "timed out")


def test_a_read_replaces_the_models_of_one_before(conn: sqlite3.Connection) -> None:
    w = worker(conn, tick(conn, at(5), None), at(4), "ses_w")
    run = Due("runs", w, "ses_w", 0)
    run_models.record(conn, run, ModelsRead.FOUND, [ModelUse("a/x", 1, 0.1), ModelUse("a/y", 1, 0.2)])
    run_models.record(conn, Due("runs", w, "ses_w", 1), ModelsRead.FOUND, [ModelUse("a/z", 2, 0.3)])
    assert [m.model for m in run_models.of_run(conn, "runs", w)] == ["a/z"]
    [(status, error, attempts)] = conn.execute("SELECT status, error, attempts FROM run_model_reads").fetchall()
    assert (status, error, attempts) == ("found", None, 2)
