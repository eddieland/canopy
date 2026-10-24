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


def review(conn: sqlite3.Connection, tick_id: int, started: str, session: str, ticket: str | None = None) -> int:
    cursor = conn.execute(
        "INSERT INTO review_runs "
        "(tick_id, pr_url, sha, started_at, ended_at, status, log_path, session_id, ticket_key) "
        "VALUES (?, 'https://e.test/pr/7', 'abc', ?, ?, 'done', 'l', ?, ?)",
        (tick_id, started, started, session, ticket),
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


def test_a_run_read_again_keeps_its_models_till_a_read_finds_its_session(conn: sqlite3.Connection) -> None:
    w = worker(conn, tick(conn, at(5), None), at(4), "ses_w")
    run_models.record(conn, Due("runs", w, "ses_w", 0), ModelsRead.FOUND, [ModelUse("a/x", 1, 0.1)])
    # As 0069 leaves it: read again, for the variant its models served at.
    conn.execute("DELETE FROM run_model_reads")
    run_models.record(conn, Due("runs", w, "ses_w", 0), ModelsRead.FAILED, error="exited 1")
    assert [m.model for m in run_models.of_run(conn, "runs", w)] == ["a/x"]
    conn.execute("DELETE FROM run_model_reads")
    run_models.record(conn, Due("runs", w, "ses_w", 0), ModelsRead.MISSING)
    assert [m.model for m in run_models.of_run(conn, "runs", w)] == ["a/x"]
    [(status, attempts)] = conn.execute("SELECT status, attempts FROM run_model_reads").fetchall()
    assert (status, attempts) == ("found", 1)
    assert due(conn) == []


def test_a_tickets_cost_by_model_sums_its_runs_and_the_reviews_naming_it(conn: sqlite3.Connection) -> None:
    first = tick(conn, at(5), "ses_t")
    canary, switched = worker(conn, first, at(4), "ses_w1"), worker(conn, first, at(3), "ses_w2")
    reviewed, elsewhere = review(conn, first, at(2), "ses_r1", "PROJ-1"), review(conn, first, at(1), "ses_r2")
    run_models.record(conn, Due("runs", canary, "ses_w1", 0), ModelsRead.FOUND, [ModelUse("a/opus", 4, 1.5)])
    used = [ModelUse("a/opus", 1, 0.25), ModelUse("a/sonnet", 9, 0.5)]
    run_models.record(conn, Due("runs", switched, "ses_w2", 0), ModelsRead.FOUND, used)
    run_models.record(conn, Due("review_runs", reviewed, "ses_r1", 0), ModelsRead.FOUND, [ModelUse("o/gpt", 2, 0.75)])
    run_models.record(conn, Due("review_runs", elsewhere, "ses_r2", 0), ModelsRead.FOUND, [ModelUse("o/gpt", 2, 9.0)])
    # The overseer's is the workspace's, and a review that names no ticket is no ticket's.
    run_models.record(conn, Due("ticks", first, "ses_t", 0), ModelsRead.FOUND, [ModelUse("a/opus", 1, 5.0)])
    totals = [(m.model, m.runs, m.cost_usd) for m in run_models.of_ticket(conn, "PROJ-1")]
    assert totals == [("a/opus", 2, 1.75), ("o/gpt", 1, 0.75), ("a/sonnet", 1, 0.5)]
    assert run_models.of_ticket(conn, "PROJ-2") == []


def test_a_read_records_each_reply_s_model_and_replaces_those_of_one_before(conn: sqlite3.Connection) -> None:
    w = worker(conn, tick(conn, at(5), None), at(4), "ses_w")
    split = [ModelUse("a/x", 1, 0.1), ModelUse("a/y", 1, 0.2)]
    run_models.record(conn, Due("runs", w, "ses_w", 0), ModelsRead.FOUND, split, replies={"m1": "a/x", "m2": "a/y"})
    assert run_models.replies_of(conn, "runs", w) == {"m1": "a/x", "m2": "a/y"}
    assert run_models.replies_of(conn, "ticks", w) == {}  # another table's run of the same id
    # A read that fails, or finds the session gone, keeps them with the models.
    conn.execute("DELETE FROM run_model_reads")
    run_models.record(conn, Due("runs", w, "ses_w", 0), ModelsRead.FAILED, error="exited 1")
    conn.execute("DELETE FROM run_model_reads")
    run_models.record(conn, Due("runs", w, "ses_w", 0), ModelsRead.MISSING)
    assert run_models.replies_of(conn, "runs", w) == {"m1": "a/x", "m2": "a/y"}
    run_models.record(conn, Due("runs", w, "ses_w", 1), ModelsRead.FOUND, [ModelUse("a/z", 2, 0.3)])
    assert run_models.replies_of(conn, "runs", w) == {}


def test_0088_reads_again_only_the_runs_more_than_one_model_served(tmp_path: Path, journals: Journals) -> None:
    """A run read before canopy kept each reply's model is read again for them, if it had more than one model."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    shipped = db.discover(resources.migrations_dir())
    for m in shipped:
        if m.version < 88:
            (migrations / m.path.name).write_text(m.path.read_text())
    conn = journals.open(tmp_path / db.DB_FILE_NAME, migrate=False)
    db.migrate(conn, migrations)
    conn.execute("INSERT INTO tickets (key, repo, first_seen_at, last_seen_at) VALUES ('PROJ-1', 'ws', 'x', 'x')")
    first = tick(conn, at(5), "ses_t")
    w = worker(conn, first, at(4), "ses_w")
    conn.executemany(
        "INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at) "
        "VALUES (?, ?, 'found', NULL, 1, 'x')",
        [("ticks", first), ("runs", w)],
    )
    conn.executemany(
        "INSERT INTO run_models (run_table, run_id, model, replies, cost_usd) VALUES (?, ?, ?, 1, 0.1)",
        [("ticks", first, "a/x"), ("runs", w, "a/x"), ("runs", w, "a/y")],
    )
    [latest] = [m for m in shipped if m.version == 88]
    (migrations / latest.path.name).write_text(latest.path.read_text())
    db.migrate(conn, migrations)
    assert due(conn) == [("runs", w, "ses_w", 0)]
    # Its models are shown till a read replaces them.
    assert [m.model for m in run_models.of_run(conn, "runs", w)] == ["a/x", "a/y"]
