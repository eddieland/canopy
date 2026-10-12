import os
import sqlite3
from pathlib import Path

import pytest

from canopy.core import db
from canopy.infra import resources
from tests.canopy.test_reconcile import DEAD_PID


def fresh(tmp_path: Path) -> sqlite3.Connection:
    return db.connect(tmp_path / "canopy.db")


def test_migrate_applies_once_and_records(tmp_path: Path) -> None:
    conn = fresh(tmp_path)
    assert db.migrate(conn, resources.migrations_dir()) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert db.migrate(conn, resources.migrations_dir()) == []
    rows = [tuple(r) for r in conn.execute("SELECT version, name FROM schema_migrations")]
    assert rows == [
        (1, "init"),
        (2, "run_sessions"),
        (3, "conversations"),
        (4, "mirrored_comments"),
        (5, "forget"),
        (6, "tick_cost"),
        (7, "tick_messages"),
        (8, "chore_cost"),
        (9, "tick_read_at"),
    ]
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_new_migration_is_applied_and_recorded(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_init.sql").write_text((resources.migrations_dir() / "0001_init.sql").read_text())
    conn = fresh(tmp_path)
    db.migrate(conn, migrations)
    (migrations / "0002_extra.sql").write_text("CREATE TABLE extra (id INTEGER PRIMARY KEY);\n")
    assert db.migrate(conn, migrations) == [2]
    assert conn.execute("SELECT name FROM schema_migrations WHERE version = 2").fetchone()[0] == "extra"


def test_failed_migration_rolls_back(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_init.sql").write_text((resources.migrations_dir() / "0001_init.sql").read_text())
    (migrations / "0002_bad.sql").write_text("CREATE TABLE half (id INTEGER);\nNOT SQL;\n")
    conn = fresh(tmp_path)
    with pytest.raises(sqlite3.Error):
        db.migrate(conn, migrations)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name IN ('ticks', 'half')").fetchall() == []


@pytest.mark.parametrize("names", [["0001_a.sql", "0003_b.sql"], ["1_a.sql"], ["0002_a.sql"]])
def test_migration_files_must_be_numbered_in_order(tmp_path: Path, names: list[str]) -> None:
    for name in names:
        (tmp_path / name).write_text("SELECT 1;\n")
    with pytest.raises(db.MigrationError):
        db.discover(tmp_path)


def test_journal_newer_than_code_is_an_error(tmp_path: Path) -> None:
    conn = fresh(tmp_path)
    db.migrate(conn, resources.migrations_dir())
    conn.execute("INSERT INTO schema_migrations (version, name) VALUES (99, 'future')")
    with pytest.raises(db.MigrationError, match="does not know"):
        db.migrate(conn, resources.migrations_dir())


def test_ticks_tickets_and_decisions(tmp_path: Path) -> None:
    conn = fresh(tmp_path)
    db.migrate(conn, resources.migrations_dir())
    stale = db.start_tick(conn, dry_run=False)
    assert db.abandon_unfinished_ticks(conn) == [stale]
    tick = db.start_tick(conn, dry_run=True)
    db.touch_ticket(conn, "PROJ-1", "/repo")
    db.set_ticket(conn, "PROJ-1", "/repo", phase="ci_red", cursors={"comment": "c-7"})
    db.set_unit(conn, "PROJ-1", "/repo", "api", phase="ci_red", cursors={"ci": "run-7"})
    db.set_ticket(conn, "PROJ-2", "/repo", done=True)
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks pending")
    db.finish_tick(conn, tick, "ok", "1 decision")

    row = db.get_tick(conn, stale)
    assert row is not None
    assert row["status"] == "abandoned"
    [ticket] = db.open_tickets(conn)
    assert (ticket["key"], ticket["phase"], ticket["last_comment_id"]) == ("PROJ-1", "ci_red", "c-7")
    [unit] = db.units(conn, "PROJ-1")
    assert (unit["repo"], unit["phase"], unit["last_ci_run_id"], unit["branch"]) == ("api", "ci_red", "run-7", None)
    [decision] = db.decisions_for_tick(conn, tick)
    assert (decision["ticket_key"], decision["action"]) == ("PROJ-1", "wait")
    last = db.last_tick(conn)
    assert last is not None
    assert (last["id"], last["status"], last["dry_run"]) == (tick, "ok", 1)


def test_an_unknown_journal_waits_for_runs_an_earlier_canopy_started(tmp_path: Path) -> None:
    """D068: a journal this canopy cannot open names its live runs first, so it is not moved aside under one."""
    conn = fresh(tmp_path)
    db.migrate(conn, resources.migrations_dir())
    conn.execute("INSERT INTO schema_migrations (version, name) VALUES (99, 'from_before_the_squash')")
    conn.execute("INSERT INTO ticks (id, started_at) VALUES (1, 'x')")
    db.touch_ticket(conn, "OLD-1", "/r")
    conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, log_path, status, pid) "
        "VALUES (1, 'OLD-1', 'implement', 'agent/OLD-1-a', 'x', 'l', 'running', ?)",
        (os.getpid(),),
    )
    with pytest.raises(db.MigrationError, match="run 1 is still working for the canopy before it"):
        db.migrate(conn, resources.migrations_dir())
    conn.execute("UPDATE runs SET status = 'done' WHERE id = 1")
    with pytest.raises(db.MigrationError, match=r"migrations this canopy does not know: \[99\]"):
        db.migrate(conn, resources.migrations_dir())


def test_pending_migrations_wait_for_runs_an_earlier_canopy_started(tmp_path: Path) -> None:
    """D060: a live `_run` of the old version would write the old schema, so the journal is not migrated under it."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_init.sql").write_text((resources.migrations_dir() / "0001_init.sql").read_text())
    conn = fresh(tmp_path)
    db.migrate(conn, migrations)
    conn.execute("INSERT INTO ticks (id, started_at) VALUES (1, 'x')")
    for key in ("OLD-1", "OLD-2", "OLD-3"):
        db.touch_ticket(conn, key, "/r")
    conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, log_path, status, pid) VALUES "
        "(1, 'OLD-1', 'implement', 'agent/OLD-1-a', 'x', 'l', 'running', ?), "
        "(1, 'OLD-2', 'implement', 'agent/OLD-2-a', 'x', 'l', 'running', ?), "
        "(1, 'OLD-3', 'implement', 'agent/OLD-3-a', 'x', 'l', 'done', ?)",
        (DEAD_PID, os.getpid(), os.getpid()),
    )
    (migrations / "0002_extra.sql").write_text("ALTER TABLE runs ADD COLUMN extra TEXT;\n")
    with pytest.raises(db.MigrationError, match="run 2 is still working for the canopy before it"):
        db.migrate(conn, migrations)
    assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations")] == [1]

    # Once it finishes, the run whose `_run` died does not hold the journal back: reconcile closes it.
    conn.execute("UPDATE runs SET status = 'done' WHERE id = 2")
    assert db.migrate(conn, migrations) == [2]
    # With nothing pending, a live run is no reason to refuse.
    conn.execute("UPDATE runs SET status = 'running' WHERE id = 2")
    assert db.migrate(conn, migrations) == []


def test_a_v01_journal_gains_sessions_and_costs_with_nothing_reported(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_init.sql").write_text((resources.migrations_dir() / "0001_init.sql").read_text())
    conn = fresh(tmp_path)
    db.migrate(conn, migrations)
    conn.execute("INSERT INTO ticks (id, started_at) VALUES (1, 'x')")
    db.touch_ticket(conn, "OLD-1", "/r")
    conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, log_path, status) "
        "VALUES (1, 'OLD-1', 'implement', 'agent/OLD-1-a', 'x', 'l', 'done')"
    )
    conn.execute(
        "INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path) VALUES (1, 'nightly', 'x', 'ok', 'l')"
    )
    assert db.migrate(conn, resources.migrations_dir()) == [2, 3, 4, 5, 6, 7, 8, 9]
    chore_run = db.get_chore_run(conn, 1)
    assert chore_run is not None
    assert (chore_run["session_id"], chore_run["cost_usd"], chore_run["tokens_input"]) == (None, None, None)
    run = db.get_run(conn, 1)
    assert run is not None
    assert (run["session_id"], run["cost_usd"], run["tokens_input"]) == (None, None, None)
    tick = db.get_tick(conn, 1)
    assert tick is not None
    assert (tick["session_id"], tick["cost_usd"], tick["tokens_input"]) == (None, None, None)
