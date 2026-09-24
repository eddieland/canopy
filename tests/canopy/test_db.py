import sqlite3
from pathlib import Path

import pytest

from canopy import db, resources


def fresh(tmp_path: Path) -> sqlite3.Connection:
    return db.connect(tmp_path / "canopy.db")


def test_migrate_applies_once_and_records(tmp_path: Path) -> None:
    conn = fresh(tmp_path)
    assert db.migrate(conn, resources.migrations_dir()) == [1, 2, 3]
    assert db.migrate(conn, resources.migrations_dir()) == []
    rows = [tuple(r) for r in conn.execute("SELECT version, name FROM schema_migrations")]
    assert rows == [(1, "init"), (2, "runs_worker_pid"), (3, "attempts_from_runs")]
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
    db.set_ticket(conn, "PROJ-1", "/repo", phase="ci_red", cursors={"ci": "run-7"})
    db.set_ticket(conn, "PROJ-2", "/repo", done=True)
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks pending")
    db.finish_tick(conn, tick, "ok", "1 decision")

    row = db.get_tick(conn, stale)
    assert row is not None
    assert row["status"] == "abandoned"
    [ticket] = db.open_tickets(conn)
    assert (ticket["key"], ticket["phase"], ticket["last_ci_run_id"]) == ("PROJ-1", "ci_red", "run-7")
    [decision] = db.decisions_for_tick(conn, tick)
    assert (decision["ticket_key"], decision["action"]) == ("PROJ-1", "wait")
    last = db.last_tick(conn)
    assert last is not None
    assert (last["id"], last["status"], last["dry_run"]) == (tick, "ok", 1)
