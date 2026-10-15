import hashlib
import os
import sqlite3
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import pytest

from canopy.core import db
from canopy.infra import resources
from tests.canopy.helpers import journal_at, shipped_through, versions_after
from tests.canopy.test_reconcile import DEAD_PID
from tests.conftest import Journals

# Each shipped migration's sha256, over LF line endings. A journal applies a migration once, so an edit to a shipped
# one reaches only fresh journals and the two drift apart: a change to the schema is a new migration (AGENTS.md). A
# new migration adds its line here.
SHIPPED = {
    1: "29a6d9dc889e6665b59c3275c33cef6b110c91e5e91012bbeb54128ee247dfcc",
    2: "57a7f7c2c1c4a5ba3f1b2a6758fcfdc436300022f8d42ea9dcf448c0f28ac230",
    3: "2c6304b3bbd58ae42d99a556d89ce45f92a918a5928938eae6f0e03d4d82d077",
    4: "de8cac71aaac4d1b1519936ad84bee2c09892b64284f7b574d7adefb2d68884a",
    5: "dbfef8c285bc0ee62593db11e8ab5c6d2cff51ed4890244858a401f28772c8fd",
    6: "fe189eed7922fdf0e190d704d291171bfd5eb520ae06b77ff5f602b4bb0d5706",
    7: "7411e79251a21c3b9b0c27ec5b6760a12a99d6dae115a07e98c4b5e6fe504090",
    8: "d111db1b5b24bd675ec5f85155e070bcc0622347c35c8467b486d7fecf2bbb56",
    9: "a1ffa27d0c8256f924f9010f501f512bca480197c5797dd8afa105421367bbd1",
    10: "cf297c7f2eb5a217a1b326da730a56fb71b246241191fb6009592fc867c713e1",
    11: "b5f91649b20c6783e4f915816ba930c0ff986cee619acce6f03c313d398ce941",
    12: "04410ef0faf97f97e28ffdfb7c8a6c0f86ec7878222ef10336fad518f89196f7",
    13: "995116e0a3010b31af0f183154266a6774a5241972aac2a48ae62be9bf80a49a",
    14: "764761a8223991f778163245e702688715f2d9144de5573244c4fee8c74f533e",
    15: "91667c9b816fde738ca9809286ad3d2b49dce1db8f6fdc9dc2cb1cac46d200ee",
    16: "d8c8ca63da12108ce7fbca6f9e2baf36c8e6ba028db7598783fda0894d7167c6",
    17: "51c8d5942669378ea5984b9dde80851f26684e7bdefae6a384aaabc2985ed1c1",
    18: "8da85c12a7f48e16cc76fd4be19beafeecfbd7f79b5418d2e86b608abfb4baae",
    19: "df22e157b9cd5981c11536a7787e7ada6e0cd4d5d9715c261d4a3c45b3cf4927",
    20: "00382891c078ea709d9987a62de8d5cfc493e6985abdf8ccc7884b778366bd46",
    21: "58c9215c4a5ebe34410cc620a9feeb8f7b8fb60a9cb23fdced184000ee5b6fdc",
    22: "089e023a4a03edec3e74abb101b22e5b1e54461350e31d5122323a23db227398",
}

# A row for every table, inserted once the migration that creates the table is applied, so each later migration runs
# against a journal with something in it: a rebuilt table or a new constraint fails on rows, not on an empty journal.
# A migration that creates a table adds its row here, in an order the foreign keys allow.
SEED: Mapping[str, str] = {
    "ticks": "INSERT INTO ticks (id, started_at, ended_at, status) VALUES (1, 'x', 'y', 'ok')",
    "tickets": (
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, phase) VALUES ('OLD-1', '/r', 'x', 'y', 'ci_red')"
    ),
    "runs": (
        "INSERT INTO runs (id, tick_id, ticket_key, kind, branch, started_at, ended_at, log_path, status, result_json) "
        """VALUES (1, 1, 'OLD-1', 'implement', 'agent/OLD-1-a', 'x', 'y', 'l', 'done', '{"summary": "did it"}')"""
    ),
    "decisions": "INSERT INTO decisions (tick_id, ticket_key, action, rationale) VALUES (1, 'OLD-1', 'wait', 'r')",
    "notifications": (
        "INSERT INTO notifications (sink, fingerprint, ticket_key, reason, sent_at) "
        "VALUES ('log', 'f', 'OLD-1', 'r', 'x')"
    ),
    "ticket_units": "INSERT INTO ticket_units (ticket_key, repo, branch, phase) VALUES ('OLD-1', 'api', 'b', 'ci_red')",
    "run_slots": (
        "INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder) VALUES (1, 'api', '/s', 'l', 'h')"
    ),
    "split_children": (
        "INSERT INTO split_children (child_key, parent_key, repo, run_id) VALUES ('OLD-2', 'OLD-1', 'api', 1)"
    ),
    "chore_runs": (
        "INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path) VALUES (1, 'nightly', 'x', 'ok', 'l')"
    ),
    "notify_events": "INSERT INTO notify_events (grp, kind, at, fields) VALUES ('runs', 'run.ended', 'x', '{}')",
    "notify_sinks": "INSERT INTO notify_sinks (name, cursor, created_at) VALUES ('log', 1, 'x')",
    "review_runs": (
        "INSERT INTO review_runs (tick_id, pr_url, sha, started_at, status, log_path) "
        "VALUES (1, 'https://e.test/pr/7', 'abc', 'x', 'done', 'l')"
    ),
    "messages": (
        "INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body) "
        "VALUES ('ticket', 'OLD-1', 'x', 'operator', 'reply', 'cli', 'Blue.')"
    ),
    "starts": (
        "INSERT INTO starts (subject_kind, subject_id, status, started_at, channel) "
        "VALUES ('ticket', 'OLD-1', 'started', 'x', 'cli')"
    ),
    "pause": "INSERT INTO pause (id, paused_at, channel) VALUES (1, 'x', 'cli')",
    "attempt_grants": (
        "INSERT INTO attempt_grants (ticket_key, repo, kind, runs, granted_at) "
        "VALUES ('OLD-1', 'api', 'resume', 1, 'x')"
    ),
    "finding_dismissals": (
        "INSERT INTO finding_dismissals (chore, finding_id, dismissed_at, channel) "
        "VALUES ('nightly', 'f/1', 'x', 'cli')"
    ),
    "review_dismissals": (
        "INSERT INTO review_dismissals (review_run_id, finding, dismissed_at, channel) VALUES (1, 1, 'x', 'cli')"
    ),
    "review_grants": "INSERT INTO review_grants (pr_url, runs, granted_at) VALUES ('https://e.test/pr/7', 1, 'x')",
}


def fresh(journals: Journals, tmp_path: Path) -> sqlite3.Connection:
    return journals.open(tmp_path / "canopy.db", migrate=False)


def tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [r[0] for r in rows if r[0] != "schema_migrations"]


def contents(conn: sqlite3.Connection) -> dict[str, tuple[list[str], Counter[tuple[object, ...]]]]:
    """Every table's columns and rows, the rows as a multiset, since a rebuilt table may not keep their order."""
    found: dict[str, tuple[list[str], Counter[tuple[object, ...]]]] = {}
    for table in tables(conn):
        columns = [r["name"] for r in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))]
        # The table name comes from sqlite_master, never from input.
        rows = conn.execute(f"SELECT * FROM {table}")  # noqa: S608
        found[table] = (columns, Counter(tuple(r) for r in rows))
    return found


def test_shipped_migrations_are_never_edited() -> None:
    shipped = db.discover(resources.migrations_dir())
    found = {m.version: hashlib.sha256(m.path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for m in shipped}
    assert found == SHIPPED


def test_migrate_applies_once_and_records(tmp_path: Path, journals: Journals) -> None:
    shipped = db.discover(resources.migrations_dir())
    conn = fresh(journals, tmp_path)
    assert db.migrate(conn, resources.migrations_dir()) == [m.version for m in shipped]
    assert db.migrate(conn, resources.migrations_dir()) == []
    rows = [tuple(r) for r in conn.execute("SELECT version, name FROM schema_migrations ORDER BY version")]
    assert rows == [(m.version, m.name) for m in shipped]
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_each_migration_keeps_every_row_and_value_it_finds(tmp_path: Path, journals: Journals) -> None:
    """Applied one at a time to a journal with a row in every table, no migration loses a row, a column, or a value.

    A migration may add rows, as 0003's backfill does, and columns. One that means to drop or rewrite what it finds
    says so here.
    """
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    conn = fresh(journals, tmp_path)
    for m in db.discover(resources.migrations_dir()):
        before = contents(conn)
        (migrations / m.path.name).write_text(m.path.read_text())
        assert db.migrate(conn, migrations) == [m.version]
        after = contents(conn)
        for table, (columns, rows) in before.items():
            assert table in after, f"{m.path.name} dropped {table}"
            now_columns, now_rows = after[table]
            assert set(columns) <= set(now_columns), f"{m.path.name} dropped columns of {table}"
            kept = Counter(tuple(row[now_columns.index(c)] for c in columns) for row in now_rows.elements())
            assert rows - kept == Counter(), f"{m.path.name} lost or changed rows of {table}"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        unseeded = [t for t in tables(conn) if t not in SEED]
        assert unseeded == [], f"{m.path.name} created tables with no row in SEED"
        for table, insert in SEED.items():
            if table in after and conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0:  # noqa: S608
                conn.execute(insert)


def test_new_migration_is_applied_and_recorded(tmp_path: Path, journals: Journals) -> None:
    migrations = shipped_through(tmp_path / "migrations", 1)
    conn = fresh(journals, tmp_path)
    db.migrate(conn, migrations)
    (migrations / "0002_extra.sql").write_text("CREATE TABLE extra (id INTEGER PRIMARY KEY);\n")
    assert db.migrate(conn, migrations) == [2]
    assert conn.execute("SELECT name FROM schema_migrations WHERE version = 2").fetchone()[0] == "extra"


def test_failed_migration_rolls_back(tmp_path: Path, journals: Journals) -> None:
    migrations = shipped_through(tmp_path / "migrations", 1)
    (migrations / "0002_bad.sql").write_text("CREATE TABLE half (id INTEGER);\nNOT SQL;\n")
    conn = fresh(journals, tmp_path)
    with pytest.raises(sqlite3.Error):
        db.migrate(conn, migrations)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name IN ('ticks', 'half')").fetchall() == []


def test_a_failed_migration_rolls_back_every_pending_one(tmp_path: Path, journals: Journals) -> None:
    conn = journal_at(journals, tmp_path, 1)
    migrations = tmp_path / "migrations"
    (migrations / "0002_extra.sql").write_text("ALTER TABLE runs ADD COLUMN extra TEXT;\n")
    (migrations / "0003_bad.sql").write_text("NOT SQL;\n")
    with pytest.raises(sqlite3.Error):
        db.migrate(conn, migrations)
    # Pending migrations apply in one transaction: the good one before the bad one rolls back with it.
    assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations")] == [1]
    assert "extra" not in [r["name"] for r in conn.execute("SELECT name FROM pragma_table_info('runs')")]
    (migrations / "0003_bad.sql").write_text("SELECT 1;\n")
    assert db.migrate(conn, migrations) == [2, 3]


@pytest.mark.parametrize("names", [["0001_a.sql", "0003_b.sql"], ["1_a.sql"], ["0002_a.sql"]])
def test_migration_files_must_be_numbered_in_order(tmp_path: Path, names: list[str]) -> None:
    for name in names:
        (tmp_path / name).write_text("SELECT 1;\n")
    with pytest.raises(db.MigrationError):
        db.discover(tmp_path)


def test_journal_newer_than_code_is_an_error(tmp_path: Path, journals: Journals) -> None:
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    conn.execute("INSERT INTO schema_migrations (version, name) VALUES (99, 'future')")
    with pytest.raises(db.MigrationError, match="does not know"):
        db.migrate(conn, resources.migrations_dir())


def test_ticks_tickets_and_decisions(tmp_path: Path, journals: Journals) -> None:
    conn = fresh(journals, tmp_path)
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


def test_a_tickets_decisions_are_found_by_index(tmp_path: Path, journals: Journals) -> None:
    """A ticket's newest decisions are read through an index, not a scan of every decision ever recorded."""
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    tick = db.start_tick(conn, dry_run=False)
    db.touch_ticket(conn, "PROJ-1", "/repo")
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks pending")
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    assert db.last_decision_of(conn, "PROJ-1") == "wait"
    assert len(db.decisions_about(conn, "PROJ-1", 20)) == 1
    conn.set_trace_callback(None)
    assert len(statements) == 2
    for sql in statements:
        plan = [str(r["detail"]) for r in conn.execute(f"EXPLAIN QUERY PLAN {sql}")]
        assert any("USING INDEX decisions_ticket" in step for step in plan), plan
        assert not any(step.startswith("SCAN d") for step in plan), plan


def test_an_unknown_journal_waits_for_runs_an_earlier_canopy_started(tmp_path: Path, journals: Journals) -> None:
    """D068: a journal this canopy cannot open names its live runs first, so it is not moved aside under one."""
    conn = fresh(journals, tmp_path)
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


def test_pending_migrations_wait_for_runs_an_earlier_canopy_started(tmp_path: Path, journals: Journals) -> None:
    """A live `_run` of the old version would write the old schema, so the journal is not migrated under it."""
    conn = journal_at(journals, tmp_path, 1)
    migrations = tmp_path / "migrations"
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


def test_a_v01_journal_gains_sessions_and_costs_with_nothing_reported(tmp_path: Path, journals: Journals) -> None:
    conn = journal_at(journals, tmp_path, 1)
    conn.execute("INSERT INTO ticks (id, started_at) VALUES (1, 'x')")
    db.touch_ticket(conn, "OLD-1", "/r")
    conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, log_path, status) "
        "VALUES (1, 'OLD-1', 'implement', 'agent/OLD-1-a', 'x', 'l', 'done')"
    )
    conn.execute(
        "INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path) VALUES (1, 'nightly', 'x', 'ok', 'l')"
    )
    conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, started_at, status, log_path) "
        "VALUES (1, 'https://github.com/acme/api/pull/7', 'abc', 'x', 'done', 'l')"
    )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(1)
    review_run = db.get_review_run(conn, 1)
    assert review_run is not None
    assert (review_run["session_id"], review_run["cost_usd"], review_run["tokens_input"]) == (None, None, None)
    chore_run = db.get_chore_run(conn, 1)
    assert chore_run is not None
    assert (chore_run["session_id"], chore_run["cost_usd"], chore_run["tokens_input"]) == (None, None, None)
    run = db.get_run(conn, 1)
    assert run is not None
    assert (run["session_id"], run["cost_usd"], run["tokens_input"]) == (None, None, None)
    tick = db.get_tick(conn, 1)
    assert tick is not None
    assert (tick["session_id"], tick["cost_usd"], tick["tokens_input"]) == (None, None, None)
    # Nor did the loop say whether it was idle or what woke it.
    assert (tick["idle"], tick["woken_by"]) == (None, None)
