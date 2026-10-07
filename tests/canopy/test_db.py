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
    assert db.migrate(conn, resources.migrations_dir()) == [1, 2, 3, 4, 5, 6]
    assert db.migrate(conn, resources.migrations_dir()) == []
    rows = [tuple(r) for r in conn.execute("SELECT version, name FROM schema_migrations")]
    assert rows == [
        (1, "init"),
        (2, "runs_worker_pid"),
        (3, "attempts_from_runs"),
        (4, "workspace_repos"),
        (5, "units"),
        (6, "split_children"),
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
    db.set_unit(conn, "PROJ-1", "/repo", "api", single=False, phase="ci_red", cursors={"ci": "run-7"})
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


def test_units_carry_over_what_tickets_and_runs_held(tmp_path: Path) -> None:
    """Migration 0005 moves each run's slot to `run_slots`, and a ticket's branch, PR, phase, and cursors to a unit."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in sorted(resources.migrations_dir().glob("000[1-4]_*.sql")):
        (migrations / path.name).write_text(path.read_text())
    conn = fresh(tmp_path)
    db.migrate(conn, migrations)
    conn.execute("INSERT INTO ticks (id, started_at) VALUES (1, 'x')")
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, phase, branch, pr_url, last_comment_id, "
        "last_review_id, last_ci_run_id) VALUES "
        "('OLD-1', '/r', 'x', 'x', 'ci_red', 'agent/OLD-1-work', 'https://x.test/pr/1', 'c1', 'r1', 'ci1'), "
        "('WS-2', '/w', 'x', 'x', NULL, 'agent/WS-2-work', NULL, NULL, NULL, NULL), "
        "('NEW-3', '/r', 'x', 'x', 'ready', NULL, NULL, 'c3', NULL, NULL)"
    )
    conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, slot_path, lease_id, lease_holder, base_branch, branch, "
        "started_at, log_path, repo) VALUES "
        "(1, 'OLD-1', 'implement', '/pool/1', 'l1', 'canopy:OLD-1', 'main', 'agent/OLD-1-work', 'x', 'l', NULL), "
        "(1, 'WS-2', 'implement', '/ws/1', 'l2', 'canopy:WS-2', 'dev', 'agent/WS-2-work', 'x', 'l', 'api')"
    )
    for path in sorted(resources.migrations_dir().glob("000[1-5]_*.sql")):
        (migrations / path.name).write_text(path.read_text())
    assert db.migrate(conn, migrations) == [5]

    assert [tuple(r) for r in conn.execute("SELECT * FROM run_slots ORDER BY run_id")] == [
        (1, None, "/pool/1", "l1", "canopy:OLD-1", "main"),
        (2, "api", "/ws/1", "l2", "canopy:WS-2", "dev"),
    ]
    assert [tuple(r) for r in conn.execute("SELECT * FROM ticket_units ORDER BY ticket_key")] == [
        ("OLD-1", None, "agent/OLD-1-work", "https://x.test/pr/1", "ci_red", "r1", "ci1"),
        ("WS-2", "api", "agent/WS-2-work", None, None, None, None),
    ]
    old = db.get_ticket(conn, "OLD-1")
    assert old is not None
    assert (old["phase"], old["branch"], old["last_comment_id"]) == (None, "agent/OLD-1-work", "c1")
    new = db.get_ticket(conn, "NEW-3")
    assert new is not None
    assert new["phase"] == "ready"  # the ticket's own phase stays
    assert db.units(conn, "NEW-3") == []
    assert "pr_url" not in old.keys()  # noqa: SIM118  (a Row is not a mapping)
    run = db.get_run(conn, 1)
    assert run is not None
    assert "slot_path" not in run.keys()  # noqa: SIM118

    # A workspace of one names its unit when it next writes it, whatever the repository was called before.
    db.set_unit(conn, "OLD-1", "/r", "renamed", single=True, phase="ci_running")
    assert [(u["repo"], u["phase"], u["pr_url"]) for u in db.units(conn, "OLD-1")] == [
        ("renamed", "ci_running", "https://x.test/pr/1")
    ]


def test_pending_migrations_wait_for_runs_an_earlier_canopy_started(tmp_path: Path) -> None:
    """D060: a live `_run` of the old version would write the old schema, so the journal is not migrated under it."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in sorted(resources.migrations_dir().glob("000[1-4]_*.sql")):
        (migrations / path.name).write_text(path.read_text())
    conn = fresh(tmp_path)
    db.migrate(conn, migrations)
    conn.execute("INSERT INTO ticks (id, started_at) VALUES (1, 'x')")
    for key in ("OLD-1", "OLD-2", "OLD-3"):
        db.touch_ticket(conn, key, "/r")
    conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, slot_path, lease_id, lease_holder, base_branch, branch, "
        "started_at, log_path, status, pid) VALUES "
        "(1, 'OLD-1', 'implement', '/p/1', 'l1', 'canopy:OLD-1', 'main', 'agent/OLD-1-a', 'x', 'l', 'running', ?), "
        "(1, 'OLD-2', 'implement', '/p/2', 'l2', 'canopy:OLD-2', 'main', 'agent/OLD-2-a', 'x', 'l', 'running', ?), "
        "(1, 'OLD-3', 'implement', '/p/3', 'l3', 'canopy:OLD-3', 'main', 'agent/OLD-3-a', 'x', 'l', 'done', ?)",
        (DEAD_PID, os.getpid(), os.getpid()),
    )
    for path in sorted(resources.migrations_dir().glob("000[1-5]_*.sql")):
        (migrations / path.name).write_text(path.read_text())
    with pytest.raises(db.MigrationError, match="run 2 is still working for the canopy before it"):
        db.migrate(conn, migrations)
    assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations")] == [1, 2, 3, 4]

    # Once it finishes, the run whose `_run` died does not hold the journal back: reconcile closes it.
    conn.execute("UPDATE runs SET status = 'done' WHERE id = 2")
    assert db.migrate(conn, migrations) == [5]
    # With nothing pending, a live run is no reason to refuse.
    conn.execute("UPDATE runs SET status = 'running' WHERE id = 2")
    assert db.migrate(conn, migrations) == []
