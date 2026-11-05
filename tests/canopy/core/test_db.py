import hashlib
import os
import re
import sqlite3
import typing
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from importlib.metadata import version
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import db, recorded_runs, sql
from canopy.core.vocab import Phase, TickStatus
from canopy.infra import resources
from canopy.reviews import review_requests
from canopy.runs import policy
from canopy.runtime.report import ToolUse, Usage
from canopy.serve import pr_list
from tests.canopy.helpers import DEAD_PID, journal_at, old_ticket, present, shipped_through
from tests.conftest import Journals

# Each migration has a companion here, named by its version alone, that opens with the migration's sha256 over LF line
# endings and holds a row for each table the migration creates, in an order the foreign keys allow. A file each, not a
# list in this module, so PRs that add migrations never meet in it; two that take the same version still collide, on
# the companion's name, which is the one conflict worth having.
COMPANIONS = Path(__file__).parent / "migrations"
HASH = re.compile(r"-- sha256 of (\S+): ([0-9a-f]{64})\n")
#: The tables a migration means to delete rows of, by its version. None does yet.
DELETES: Mapping[int, AbstractSet[str]] = {}
#: The tables a migration renames, by its version: each old name to its new one and its renamed columns. None does yet.
RENAMES: Mapping[int, Mapping[str, tuple[str, Mapping[str, str]]]] = {}


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
    says so in `DELETES`, and one that renames a table or a column in `RENAMES`. Each table is seeded from the companion
    of the migration that creates it, so each later migration runs against a journal with something in it: a rebuilt
    table or a new constraint fails on rows, not on an empty journal.
    """
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    conn = fresh(journals, tmp_path)
    for m in db.discover(resources.migrations_dir()):
        before = contents(conn)
        (migrations / m.path.name).write_text(m.path.read_text())
        assert db.migrate(conn, migrations) == [m.version]
        after = contents(conn)
        for old_table, (old_columns, rows) in before.items():
            table, renamed = RENAMES.get(m.version, {}).get(old_table, (old_table, {}))
            columns = [renamed.get(c, c) for c in old_columns]
            assert table in after, f"{m.path.name} dropped {old_table}"
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


def test_a_journal_through_the_squashed_migrations_is_taken_as_having_applied_0001(
    tmp_path: Path,
    journals: Journals,
) -> None:
    """D068: 0001 makes the schema a journal migrated through 0129 holds, so its ledger is rewritten, and nothing run.

    A live run of the canopy before is no reason to wait: the schema it writes is the same. The canopy that squashed
    them ships 0001 alone; later migrations run on the rewritten ledger as on any other.
    """
    squashed = shipped_through(tmp_path / "migrations", 1)
    conn = fresh(journals, tmp_path)
    db.migrate(conn, squashed)
    conn.executemany(
        "INSERT INTO schema_migrations (version, name) VALUES (?, 'squashed')",
        [(v,) for v in range(2, db.SQUASHED_THROUGH + 1)],
    )
    conn.execute("INSERT INTO ticks (id, started_at) VALUES (1, 'x')")
    db.touch_ticket(conn, "OLD-1", "/r")
    conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, log_path, status, pid) "
        "VALUES (1, 'OLD-1', 'implement', 'agent/OLD-1-a', 'x', 'l', 'running', ?)",
        (os.getpid(),),
    )
    before = contents(conn)
    assert db.migrate(conn, squashed) == []
    assert [tuple(r) for r in conn.execute("SELECT version, name FROM schema_migrations")] == [(1, "init")]
    assert contents(conn) == before


def test_a_journal_short_of_the_last_squashed_migration_is_unknown(tmp_path: Path, journals: Journals) -> None:
    """Only a journal at the last squashed migration holds 0001's schema; one before it is not upgraded (D068)."""
    conn = fresh(journals, tmp_path)
    db.migrate(conn, shipped_through(tmp_path / "migrations", 1))
    conn.executemany(
        "INSERT INTO schema_migrations (version, name) VALUES (?, 'squashed')",
        [(v,) for v in range(2, db.SQUASHED_THROUGH)],
    )
    with pytest.raises(db.MigrationError, match="migrations this canopy does not know"):
        db.migrate(conn, resources.migrations_dir())


def test_journal_newer_than_code_is_an_error(tmp_path: Path, journals: Journals) -> None:
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    conn.execute("INSERT INTO schema_migrations (version, name) VALUES (9999, 'future')")
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
        "tokens_first_cache_read",
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
    usage = Usage(0.25, 10, 2, 0, 400, 50, peak_context=900, first_call=460, first_cache_write=50, first_cache_read=400)
    tick = db.start_tick(conn, dry_run=True)
    db.set_tick_report(conn, tick, "ses_o1", usage, digest="0123456789abcdef")
    row = conn.execute("SELECT * FROM ticks WHERE id = ?", (tick,)).fetchone()
    assert db.usage_of(row) == usage
    assert row["definitions_digest"] == "0123456789abcdef"

    # A plain-text overseer reported nothing: no agent canopy can tell loaded the snapshot.
    db.set_tick_report(conn, tick, None, None, digest="0123456789abcdef")
    row = conn.execute("SELECT * FROM ticks WHERE id = ?", (tick,)).fetchone()
    first = ("tokens_first_call", "tokens_first_cache_write", "tokens_first_cache_read", "definitions_digest")
    assert tuple(row[c] for c in first) == (None,) * 4

    # A cost recorded before the first call was kept reads it as unknown.
    db.set_tick_report(conn, tick, "ses_o1", Usage(0.25, 10, 2, 0, 400, 50, peak_context=900))
    usage = present(db.usage_of(conn.execute("SELECT * FROM ticks WHERE id = ?", (tick,)).fetchone()))
    assert (usage.first_call, usage.first_cache_write, usage.first_cache_read) == (None, None, None)


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


#: The closed columns of the tables made before M36, which list their values in comments: their schema was kept when
#: the migrations were squashed into 0001 (D068). Every other column of a closed vocabulary (`core/vocab.py`)
#: constrains its values in SQL.
UNCHECKED = frozenset(
    {
        "chore_runs.status",
        "messages.kind",
        "notify_events.kind",
        "review_runs.status",
        "runs.kind",
        "runs.status",
        "starts.status",
        "ticket_units.phase",
        "tickets.phase",
        "ticks.status",
    },
)
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
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    assert set(unchecked(conn, tables(conn))) == UNCHECKED


def test_a_closed_column_without_a_check_is_found(tmp_path: Path, journals: Journals) -> None:
    migrations = shipped_through(tmp_path / "migrations", 1)
    (migrations / "0002_observed.sql").write_text(
        "CREATE TABLE checked (id INTEGER PRIMARY KEY, status TEXT NOT NULL CHECK (status IN ('ok', 'failed')));\n"
        "CREATE TABLE unchecked (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, phase TEXT, note TEXT);\n",
    )
    conn = fresh(journals, tmp_path)
    db.migrate(conn, migrations)
    assert unchecked(conn, {"checked", "unchecked"}) == ["unchecked.kind", "unchecked.phase"]


def test_a_transaction_inside_another_commits_or_rolls_back_with_it(tmp_path: Path, journals: Journals) -> None:
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())

    def fails_after_setting() -> None:
        with db.transaction(conn):
            db.set_ticket(conn, "PROJ-1", "/repo", phase=Phase.READY)
            raise RuntimeError

    with pytest.raises(RuntimeError):
        fails_after_setting()
    assert db.get_ticket(conn, "PROJ-1") is None
    with db.transaction(conn):
        db.set_ticket(conn, "PROJ-1", "/repo", phase=Phase.READY)
        db.set_unit(conn, "PROJ-1", "/repo", "api", phase="ci_red")
    assert not conn.in_transaction
    assert present(db.get_ticket(conn, "PROJ-1")).phase == Phase.READY


def test_ticks_tickets_and_decisions(tmp_path: Path, journals: Journals) -> None:
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    stale = db.start_tick(conn, dry_run=False)
    assert db.abandon_unfinished_ticks(conn) == [stale]
    tick = db.start_tick(conn, dry_run=True)
    db.touch_ticket(conn, "PROJ-1", "/repo")
    db.set_ticket(conn, "PROJ-1", "/repo", phase=Phase.CI_RED, cursors={"comment": "7"})
    db.set_unit(conn, "PROJ-1", "/repo", "api", phase="ci_red", cursors={"ci": "9"})
    db.set_ticket(conn, "PROJ-2", "/repo", done=True)
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks pending")
    db.finish_tick(conn, tick, TickStatus.OK, "1 decision")

    row = present(db.get_tick(conn, stale))
    assert row.status == TickStatus.ABANDONED
    [ticket] = db.open_tickets(conn)
    assert (ticket.key, ticket.phase, ticket.comment_cursor) == ("PROJ-1", "ci_red", 7)
    [unit] = db.units(conn, "PROJ-1")
    assert (unit.repo, unit.phase, unit.ci_cursor, unit.branch) == ("api", "ci_red", 9, None)
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
        [pr] = pr_list.pull_requests(conn, 5)
        return ticket["last_seen_at"], ticket["active_at"], pr.active_at

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


def test_the_loops_reads_at_each_wait_step_and_tick_are_found_by_index(tmp_path: Path, journals: Journals) -> None:
    """The wait's probes, and a tick's reads of every ticket, read no table of the journal's history whole.

    A probe that finds nothing, as an idle wait's do twice a second, would otherwise read to the end of its table. A
    read of every ticket's attempts may read an index whole, which holds the two columns it needs and not the rows.
    Each statement is explained as canopy prepares it, its values bound to its `?`s, since a partial index on a literal
    serves a bound value only once SQLite sees what is bound.
    """
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    since = "2026-01-01T00:00:00.000Z"
    reads: dict[str, Callable[[], object]] = {
        "newest operator message": lambda: db.latest_message_id(conn, source="operator", subject_kind="ticket"),
        "runs moved": lambda: db.runs_moved_after(conn, since),
        "runs ended": lambda: db.runs_ended_after(conn, since),
        "starts moved": lambda: db.starts_moved_after(conn, since),
        "review requested": lambda: review_requests.made_after(conn, since),
        "open tickets": lambda: db.open_tickets(conn),
        "recently done": lambda: db.recently_done(conn, since),
        "abandoned ticks": lambda: db.abandon_unfinished_ticks(conn),
        "attempts": lambda: policy.ticket_attempts(conn, "resume"),
        "waiting runs": lambda: recorded_runs.holding(conn),
        "unstarted runs": lambda: recorded_runs.close_unstarted(conn, tick_id=1),
    }
    # A read that finds its rows by an index still reads every row under its key, so one whose key is most of a table
    # names the index that narrows it: every message to a ticket shares `subject_kind`.
    narrowed = {"newest operator message": "messages_operator"}
    run = sql.execute

    def explained(c: sqlite3.Connection, statement: sql.Composable) -> sqlite3.Cursor:
        built = statement.fragment()
        statements.append((built.text, built.params))
        return run(c, statement)

    for name, read in reads.items():
        statements: list[tuple[str, Sequence[sql.Bound]]] = []
        with mock.patch.object(sql, "execute", autospec=True, side_effect=explained):
            read()
        assert statements, f"{name} ran no statement"
        for statement, params in statements:
            plan = [str(r["detail"]) for r in conn.execute(f"EXPLAIN QUERY PLAN {statement}", params)]
            # A plan names a table by its alias where the query gives one, so every scan counts, whatever it names.
            scans = [step for step in plan if step.startswith("SCAN ") and "COVERING INDEX" not in step]
            assert scans == [], (name, statement, plan)
            if name in narrowed:
                assert any(f"INDEX {narrowed[name]} " in step for step in plan), (name, statement, plan)


def test_an_unknown_journal_waits_for_runs_an_earlier_canopy_started(tmp_path: Path, journals: Journals) -> None:
    """D068: a journal this canopy cannot open names its live runs first, so it is not moved aside under one."""
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    conn.execute("INSERT INTO schema_migrations (version, name) VALUES (9999, 'from_before_the_squash')")
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
    with pytest.raises(db.MigrationError, match=r"migrations this canopy does not know: \[9999\]"):
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


def test_the_memory_index_is_kept_in_step_with_every_write_and_delete(tmp_path: Path, journals: Journals) -> None:
    """The full-text index's triggers follow every write and delete of `memories`."""
    conn = fresh(journals, tmp_path)
    db.migrate(conn, resources.migrations_dir())
    conn.execute(
        "INSERT INTO memories (scope, key, body, status, author, created_at) "
        "VALUES ('lesson', 'api-tests', 'Run the whole suite with make check.', 'active', 'operator', 'x')",
    )

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
