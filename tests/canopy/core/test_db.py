import hashlib
import os
import re
import sqlite3
import typing
from collections import Counter
from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet
from importlib.metadata import version
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import db, records, sql
from canopy.core.vocab import Phase, SeenKind, TickStatus
from canopy.infra import resources
from canopy.runtime.report import ToolUse, Usage
from tests.canopy.helpers import DEAD_PID, journal_at, old_ticket, present, shipped_through, versions_after
from tests.conftest import Journals

# Each migration has a companion here, named by its version alone, that opens with the migration's sha256 over LF line
# endings and holds a row for each table the migration creates, in an order the foreign keys allow. A file each, not a
# list in this module, so PRs that add migrations never meet in it; two that take the same version still collide, on
# the companion's name, which is the one conflict worth having.
COMPANIONS = Path(__file__).parent / "migrations"
HASH = re.compile(r"-- sha256 of (\S+): ([0-9a-f]{64})\n")
#: The tables a migration means to delete rows of, by its version: 0069 deletes the found reads, to read them again.
DELETES: Mapping[int, AbstractSet[str]] = {69: frozenset({"run_model_reads"})}


def companion(number: int) -> str:
    return (COMPANIONS / f"{number:04d}.sql").read_text()


def fresh(journals: Journals, tmp_path: Path) -> sqlite3.Connection:
    return journals.open(tmp_path / "canopy.db", migrate=False)


def tables(conn: sqlite3.Connection) -> list[str]:
    """The journal's tables but `schema_migrations`, and but full-text indexes and the tables SQLite keeps them in.

    An index is built from its content table, which holds the rows: `memories_fts` is rebuilt from `memories`.
    """
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
    ).fetchall()
    virtual = [str(r[0]) for r in rows if str(r[1]).upper().startswith("CREATE VIRTUAL TABLE")]
    return [
        str(r[0])
        for r in rows
        if r[0] != "schema_migrations" and not any(r[0] == v or str(r[0]).startswith(f"{v}_") for v in virtual)
    ]


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
    """Each migration matches the hash its companion recorded, and each companion has its migration.

    A journal applies a migration once, so an edit to a shipped one reaches only fresh journals and the two drift
    apart: a change to the schema is a new migration (AGENTS.md).
    """
    shipped = db.discover(resources.migrations_dir())
    companions = sorted(p.name for p in COMPANIONS.iterdir())
    assert companions == [f"{m.version:04d}.sql" for m in shipped], "a migration with no companion, or the reverse"
    for m in shipped:
        recorded = HASH.match(companion(m.version))
        assert recorded is not None, f"{m.version:04d}.sql does not open with the sha256 of its migration"
        found = hashlib.sha256(m.path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        assert recorded.groups() == (m.path.name, found), f"{m.path.name} was edited, or its companion names another"


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
    says so in `DELETES`. Each table is seeded from the companion of the migration that creates it, so each later
    migration runs against a journal with something in it: a rebuilt table or a new constraint fails on rows, not on an
    empty journal.
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
            if table not in DELETES.get(m.version, frozenset()):
                assert rows - kept == Counter(), f"{m.path.name} lost or changed rows of {table}"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        conn.executescript(companion(m.version))
        # The table name comes from sqlite_master, never from input.
        empty = [t for t in tables(conn) if conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0]  # noqa: S608
        assert empty == [], f"{m.path.name} created tables its companion seeds no row in"


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


# What the shared run lifecycle reads and writes in every table of detached runs (`db.claim_run` and the rest), besides
# the column each keeps its agent's pid in.
LIFECYCLE_COLUMNS = frozenset(
    {
        "id",
        "pid",
        "status",
        "started_at",
        "ended_at",
        "result_json",
        "log_path",
        "session_id",
        "cost_usd",
        "tokens_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_cache_read",
        "tokens_cache_write",
        "tokens_peak_context",
        "tokens_first_call",
        "tokens_first_cache_write",
        "definitions_digest",
    },
)


def test_every_run_table_has_what_the_shared_lifecycle_needs(tmp_path: Path, journals: Journals) -> None:
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    assert set(typing.get_args(db.RunTable.__value__)) == set(db.RUN_TABLES)
    assert set(db.RUN_NOUNS) == set(db.AGENT_PID) == set(db.RUN_TABLES)
    for table in db.RUN_TABLES:
        columns = {r["name"] for r in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))}
        assert columns >= LIFECYCLE_COLUMNS | {db.AGENT_PID[table]}, table


def test_a_report_keeps_the_first_call_and_the_snapshot_only_with_what_the_runtime_reported(
    tmp_path: Path,
    journals: Journals,
) -> None:
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    usage = Usage(0.25, 10, 2, 0, 400, 50, peak_context=900, first_call=460, first_cache_write=50)
    tick = db.start_tick(conn, dry_run=True)
    db.set_tick_report(conn, tick, "ses_o1", usage, digest="0123456789abcdef")
    row = conn.execute("SELECT * FROM ticks WHERE id = ?", (tick,)).fetchone()
    assert db.usage_of(row) == usage
    assert row["definitions_digest"] == "0123456789abcdef"

    # A plain-text overseer reported nothing: no agent canopy can tell loaded the snapshot.
    db.set_tick_report(conn, tick, None, None, digest="0123456789abcdef")
    row = conn.execute("SELECT * FROM ticks WHERE id = ?", (tick,)).fetchone()
    assert (row["tokens_first_call"], row["tokens_first_cache_write"], row["definitions_digest"]) == (None,) * 3

    # A cost recorded before the first call was kept reads it as unknown.
    db.set_tick_report(conn, tick, "ses_o1", Usage(0.25, 10, 2, 0, 400, 50, peak_context=900))
    usage = present(db.usage_of(conn.execute("SELECT * FROM ticks WHERE id = ?", (tick,)).fetchone()))
    assert (usage.first_call, usage.first_cache_write) == (None, None)


def test_a_report_replaces_the_tools_a_run_recorded(tmp_path: Path, journals: Journals) -> None:
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    tick = db.start_tick(conn, dry_run=True)
    usage = Usage(0.25, 10, 2, 0, 400, 50)
    db.set_tick_report(conn, tick, "s", usage, tools=[ToolUse("bash", 2, 1, 30), ToolUse("read", 1, 0, 90)])
    assert [(t.tool, t.calls, t.errors, t.result_chars) for t in db.run_tools(conn, "ticks", tick)] == [
        ("read", 1, 0, 90),
        ("bash", 2, 1, 30),
    ]
    assert db.run_tools(conn, "runs", tick) == []  # another table's run of the same id called none
    db.set_tick_report(conn, tick, "s", usage, tools=[ToolUse("bash", 3, 1, 40)])
    assert [t.calls for t in db.run_tools(conn, "ticks", tick)] == [3]
    db.set_tick_report(conn, tick, None, None)
    assert db.run_tools(conn, "ticks", tick) == []


# The last migration before M36. A table made after it constrains each column of a closed vocabulary (`core/vocab.py`)
# in SQL; the tables before it list their values in comments, since a shipped migration is never edited.
UNCHECKED_THROUGH = 26
CLOSED_COLUMNS = frozenset({"status", "kind", "phase"})


def unchecked(conn: sqlite3.Connection, made: Iterable[str]) -> list[str]:
    """The `table.column` of each closed column in the tables `made` with no `CHECK (column IN (...))`."""
    found: list[str] = []
    for table in sorted(made):
        sql = str(
            conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()[0],
        )
        columns = {str(r["name"]) for r in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))}
        found.extend(
            f"{table}.{column}"
            for column in sorted(columns & CLOSED_COLUMNS)
            if not re.search(rf"CHECK\s*\(\s*{column}\s+IN\s*\(", sql, re.IGNORECASE)
        )
    return found


def test_a_table_made_from_m36_on_checks_its_closed_columns(tmp_path: Path, journals: Journals) -> None:
    before = set(tables(journal_at(journals, tmp_path / "before", UNCHECKED_THROUGH)))
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    assert unchecked(conn, set(tables(conn)) - before) == []


def test_a_closed_column_without_a_check_is_found(tmp_path: Path, journals: Journals) -> None:
    migrations = shipped_through(tmp_path / "migrations", UNCHECKED_THROUGH)
    (migrations / f"{UNCHECKED_THROUGH + 1:04d}_observed.sql").write_text(
        "CREATE TABLE checked (id INTEGER PRIMARY KEY, status TEXT NOT NULL CHECK (status IN ('ok', 'failed')));\n"
        "CREATE TABLE unchecked (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, phase TEXT, note TEXT);\n",
    )
    conn = fresh(journals, tmp_path)
    db.migrate(conn, migrations)
    assert unchecked(conn, {"checked", "unchecked"}) == ["unchecked.kind", "unchecked.phase"]


def test_ticks_tickets_and_decisions(tmp_path: Path, journals: Journals) -> None:
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    stale = db.start_tick(conn, dry_run=False)
    assert db.abandon_unfinished_ticks(conn) == [stale]
    tick = db.start_tick(conn, dry_run=True)
    db.touch_ticket(conn, "PROJ-1", "/repo")
    db.set_ticket(conn, "PROJ-1", "/repo", phase=Phase.CI_RED, cursors={"comment": "c-7"})
    db.set_unit(conn, "PROJ-1", "/repo", "api", phase="ci_red", cursors={"ci": "run-7"})
    db.set_ticket(conn, "PROJ-2", "/repo", done=True)
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks pending")
    db.finish_tick(conn, tick, TickStatus.OK, "1 decision")

    row = present(db.get_tick(conn, stale))
    assert row.status == TickStatus.ABANDONED
    [ticket] = db.open_tickets(conn)
    assert (ticket.key, ticket.phase, ticket.last_comment_id) == ("PROJ-1", "ci_red", "c-7")
    [unit] = db.units(conn, "PROJ-1")
    assert (unit.repo, unit.phase, unit.last_ci_run_id, unit.branch) == ("api", "ci_red", "run-7", None)
    [decision] = db.decisions_for_tick(conn, tick)
    assert (decision.ticket_key, decision.action) == ("PROJ-1", "wait")
    last = present(db.last_tick(conn))
    assert (last.id, last.status, last.dry_run) == (tick, TickStatus.OK, True)
    assert last.canopy_version == version("canopy")


def test_a_ticket_is_active_when_it_changes_not_when_a_tick_sets_what_it_already_holds(
    tmp_path: Path,
    journals: Journals,
) -> None:
    """A tick that sets a ticket's phase, title, or PR to what it holds moves its sighting, not its activity."""
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    url = "https://e.test/pr/1"

    def at(minute: int) -> str:
        return f"2026-10-19T09:{minute:02d}:00.000Z"

    def active() -> tuple[str, str, str]:
        [ticket] = db.recent_tickets(conn, 5)
        [pr] = db.pull_requests(conn, 5)
        return ticket["last_seen_at"], ticket["active_at"], pr["active_at"]

    with mock.patch.object(db, "now", autospec=True, return_value=at(0)):
        db.set_ticket(conn, "PROJ-1", "/repo", phase=Phase.CI_RED, title="Sign in")
        db.set_unit(conn, "PROJ-1", "/repo", "api", phase=Phase.CI_RED, pr_url=url)
    with mock.patch.object(db, "now", autospec=True, return_value=at(10)):
        db.set_ticket(conn, "PROJ-1", "/repo", phase=Phase.CI_RED, title="Sign in", cursors={"comment": "c-1"})
        db.set_unit(conn, "PROJ-1", "/repo", "api", phase=Phase.CI_RED, pr_url=url, cursors={"ci": "run-1"})
    assert active() == (at(10), at(0), at(0))

    with mock.patch.object(db, "now", autospec=True, return_value=at(20)):
        db.set_unit(conn, "PROJ-1", "/repo", "api", phase=Phase.REVIEW_PENDING)
    assert active() == (at(20), at(20), at(20))
    with mock.patch.object(db, "now", autospec=True, return_value=at(30)):
        db.set_ticket(conn, "PROJ-1", "/repo", done=True)
    with mock.patch.object(db, "now", autospec=True, return_value=at(40)):
        db.set_ticket(conn, "PROJ-1", "/repo", done=True)
    assert active() == (at(40), at(30), at(30))


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
    for statement in statements:
        plan = [str(r["detail"]) for r in conn.execute(f"EXPLAIN QUERY PLAN {statement}")]
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
        old_ticket(conn, key)
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
    old_ticket(conn, "OLD-1")
    conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, log_path, status) "
        "VALUES (1, 'OLD-1', 'implement', 'agent/OLD-1-a', 'x', 'l', 'done')",
    )
    conn.execute(
        "INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path) VALUES (1, 'nightly', 'x', 'ok', 'l')",
    )
    conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, started_at, status, log_path) "
        "VALUES (1, 'https://github.com/acme/api/pull/7', 'abc', 'x', 'done', 'l')",
    )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(1)
    review_run = present(db.get_review_run(conn, 1))
    assert (review_run.session_id, review_run.cost_usd, review_run.tokens_input) == (None, None, None)
    chore_run = present(db.get_chore_run(conn, 1))
    assert (chore_run.session_id, chore_run.cost_usd, chore_run.tokens_input) == (None, None, None)
    run = present(db.get_run(conn, 1))
    assert (run["session_id"], run["cost_usd"], run["tokens_input"]) == (None, None, None)
    tick = present(db.get_tick(conn, 1))
    assert (tick.session_id, tick.cost_usd, tick.tokens_input) == (None, None, None)
    # Nor did the loop say whether it was idle or what woke it.
    assert (tick.idle, tick.woken_by) == (None, None)


def test_review_runs_from_before_their_purpose_are_own_only_where_their_tickets_unit_has_their_pr(
    tmp_path: Path,
    journals: Journals,
) -> None:
    """0023 settles the purpose of runs recorded before it: `own` for their ticket's unit's PR, `query` otherwise."""
    conn = journal_at(journals, tmp_path, 21)
    conn.execute("INSERT INTO ticks (id, started_at) VALUES (1, 'x')")
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, phase) "
        "VALUES ('OLD-1', '/r', 'x', 'y', 'ci_red')",
    )
    conn.execute(
        "INSERT INTO ticket_units (ticket_key, repo, branch, phase, pr_url) "
        "VALUES ('OLD-1', 'api', 'b', 'ci_red', 'https://e.test/pr/7')",
    )
    pr = "https://e.test/pr/7"
    # The unit's PR in its repository, and with no repository recorded (a workspace of one); another PR; no ticket; and
    # the unit's PR URL in another repository.
    for url, ticket, repo in [
        (pr, "OLD-1", "api"),
        (pr, "OLD-1", None),
        ("https://e.test/pr/8", "OLD-1", "api"),
        (pr, None, "api"),
        (pr, "OLD-1", "web"),
    ]:
        conn.execute(
            "INSERT INTO review_runs (tick_id, pr_url, sha, ticket_key, repo, started_at, status, log_path) "
            "VALUES (1, ?, 'abc', ?, ?, 'x', 'done', 'l')",
            (url, ticket, repo),
        )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(21)
    purposes = [r[0] for r in conn.execute("SELECT purpose FROM review_runs ORDER BY id")]
    assert purposes == ["own", "own", "query", "query", "query"]


def test_a_ticket_forgotten_before_forgets_were_recorded_has_its_latest_forget_with_what_it_dropped_unknown(
    tmp_path: Path,
    journals: Journals,
) -> None:
    """0045 records each ticket's latest forget from its row; what that forget dropped, and from where, is unknown."""
    conn = journal_at(journals, tmp_path, 44)
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, forgotten_at) VALUES "
        "('OLD-1', '/r', 'x', 'y', '2026-10-01T00:00:00Z'), ('OLD-2', '/r', 'x', 'y', NULL)",
    )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(44)
    [forget] = db.forgets_of(conn, "OLD-1")
    assert (forget.at, forget.channel, forget.run_id, forget.message_id, forget.branch, forget.prs) == (
        "2026-10-01T00:00:00Z",
        None,
        None,
        None,
        None,
        None,
    )
    assert db.forgets_of(conn, "OLD-2") == []


def test_the_memory_index_is_built_from_what_the_journal_holds_and_kept_in_step(
    tmp_path: Path,
    journals: Journals,
) -> None:
    """0038 indexes the memories already written, and its triggers follow every later write and delete."""
    conn = journal_at(journals, tmp_path, 37)
    conn.execute(
        "INSERT INTO memories (scope, key, body, status, author, created_at) "
        "VALUES ('lesson', 'api-tests', 'Run the whole suite with make check.', 'active', 'operator', 'x')",
    )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(37)

    def indexed(word: str) -> list[int]:
        return [r[0] for r in conn.execute("SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?", (word,))]

    assert indexed("suite") == [1]
    conn.execute("UPDATE memories SET body = 'Lint with make lint.' WHERE id = 1")
    assert (indexed("suite"), indexed("lint")) == ([], [1])
    conn.execute("UPDATE memories SET body = NULL WHERE id = 1")
    assert indexed("lint") == []
    conn.execute("DELETE FROM memories WHERE id = 1")
    # Raises if the index and the rows it is built from disagree.
    conn.execute("INSERT INTO memories_fts (memories_fts) VALUES ('integrity-check')")


def test_the_reviews_that_had_ended_are_taken_as_seen(tmp_path: Path, journals: Journals) -> None:
    """0055 marks every ended review run seen, with no channel, so the reviews before it are not all new at once."""
    conn = journal_at(journals, tmp_path, 54)
    conn.execute("INSERT INTO ticks (id, started_at) VALUES (1, 'x')")
    conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, started_at, ended_at, status, log_path) VALUES "
        "(1, 'https://github.com/acme/api/pull/7', 'abc', 'x', '2026-10-01T00:00:00Z', 'done', 'l'), "
        "(1, 'https://github.com/acme/api/pull/8', 'def', 'x', NULL, 'running', 'l')",
    )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(54)
    seen = records.fetch_all(conn, records.Seen, sql.select("*").from_("seen"))
    assert seen == [records.Seen(SeenKind.REVIEW, "1", "2026-10-01T00:00:00Z", None)]
    assert db.seen_among(conn, SeenKind.REVIEW, ["1", "2"]) == {"1"}


def test_runs_whose_models_were_found_are_read_again_and_keep_their_models(tmp_path: Path, journals: Journals) -> None:
    """0069 makes each found run due again, for the variant its models served at; missing and failed reads stay."""
    conn = journal_at(journals, tmp_path, 68)
    conn.executemany(
        "INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at) VALUES (?, ?, ?, ?, 1, 'x')",
        [("runs", 1, "found", None), ("runs", 2, "missing", None), ("ticks", 3, "failed", "exited 1")],
    )
    conn.execute(
        "INSERT INTO run_models (run_table, run_id, model, replies, cost_usd) VALUES ('runs', 1, 'a/x', 2, 0.5)",
    )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(68)
    reads = conn.execute("SELECT run_table, run_id, status FROM run_model_reads ORDER BY run_id").fetchall()
    assert [tuple(r) for r in reads] == [("runs", 2, "missing"), ("ticks", 3, "failed")]
    assert [tuple(r) for r in conn.execute("SELECT run_id, model FROM run_models")] == [(1, "a/x")]
