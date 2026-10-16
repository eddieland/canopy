import re
import sqlite3
import types
import typing
from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

import pytest

from canopy.core import db, records
from canopy.core.vocab import ChoreRunStatus
from tests.conftest import Journals

# The field types a column of each declared type may be read as.
AFFINITY: dict[str, frozenset[object]] = {
    "INTEGER": frozenset({int, bool}),
    "TEXT": frozenset({str}),
    "REAL": frozenset({float}),
    "BLOB": frozenset({bytes}),
}
DECISION_COLUMNS = "id, tick_id, ticket_key, action, rationale, created_at, repo, chore, pr"


def row_types() -> list[type[records.Row]]:
    # A row type a test module defines for itself is not a journal table's.
    return [t for t in records.Row.__subclasses__() if t.__module__ == records.__name__]


@pytest.fixture
def conn(tmp_path: Path, journals: Journals) -> sqlite3.Connection:
    return journals.open(tmp_path / db.DB_FILE_NAME)


def field_type(hint: object) -> tuple[object, bool]:
    """A field's type without its `| None`, and whether it had one."""
    args = typing.get_args(hint)
    if typing.get_origin(hint) is types.UnionType and type(None) in args:
        [inner] = [a for a in args if a is not type(None)]
        return inner, True
    return hint, False


def test_every_row_type_names_a_table_of_its_own(conn: sqlite3.Connection) -> None:
    tables = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert row_types()
    assert [t.TABLE for t in row_types() if t.TABLE not in tables] == []
    assert len({t.TABLE for t in row_types()}) == len(row_types())


@pytest.mark.parametrize("row_type", row_types(), ids=lambda t: t.TABLE)
def test_a_row_type_has_its_tables_columns_in_order_with_their_types(
    conn: sqlite3.Connection, row_type: type[records.Row]
) -> None:
    columns = conn.execute(f"PRAGMA table_info({row_type.TABLE})").fetchall()
    hints = typing.get_type_hints(row_type)
    assert [f.name for f in fields(row_type)] == [str(c["name"]) for c in columns]
    for column in columns:
        name = str(column["name"])
        inner, optional = field_type(hints[name])
        # An INTEGER PRIMARY KEY is never NULL, though the pragma does not mark it NOT NULL.
        nullable = not column["notnull"] and not column["pk"]
        assert optional == nullable, f"{row_type.TABLE}.{name}: a nullable column is a `| None` field, and only one is"
        # A vocabulary's members are the strings a TEXT column holds.
        read_as = str if isinstance(inner, type) and issubclass(inner, StrEnum) else inner
        assert read_as in AFFINITY[str(column["type"])], f"{row_type.TABLE}.{name} is {column['type']}, not {inner}"


def test_a_query_builds_its_rows_as_the_row_type(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks running", repo="api")
    db.record_decision(conn, tick, None, "skip", "no tracker", chore="deps")
    [first, second] = records.fetch_all(conn, records.Decision, "SELECT * FROM decisions ORDER BY id")
    assert first == records.Decision(
        id=first.id,
        tick_id=tick,
        ticket_key="PROJ-1",
        action="wait",
        rationale="checks running",
        created_at=first.created_at,
        repo="api",
        chore=None,
        pr=None,
    )
    assert (second.ticket_key, second.chore) == (None, "deps")


def test_columns_are_matched_by_name_not_position(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks running")
    reversed_columns = ", ".join(reversed(DECISION_COLUMNS.split(", ")))
    row = records.fetch_one(conn, records.Decision, f"SELECT {reversed_columns} FROM decisions")  # noqa: S608
    assert row is not None
    assert (row.ticket_key, row.action, row.rationale) == ("PROJ-1", "wait", "checks running")


def test_fetch_one_is_none_when_the_query_returns_nothing(conn: sqlite3.Connection) -> None:
    assert records.fetch_one(conn, records.Decision, "SELECT * FROM decisions WHERE id = ?", (1,)) is None


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("SELECT id, tick_id FROM decisions", "missing action, chore, created_at, pr, rationale, repo, ticket_key"),
        (f"SELECT {DECISION_COLUMNS}, 1 AS extra FROM decisions", "no field for extra"),  # noqa: S608
        (f"SELECT {DECISION_COLUMNS}, id FROM decisions", "a column is repeated"),  # noqa: S608
    ],
)
def test_a_query_whose_columns_do_not_fit_is_refused_before_any_row(
    conn: sqlite3.Connection, sql: str, error: str
) -> None:
    # Refused on the query's shape alone: an empty table still fails, so the mistake shows on its first run.
    with pytest.raises(records.RowError, match=f"^query does not fit Decision: {re.escape(error)}$"):
        records.fetch_all(conn, records.Decision, sql)


@pytest.mark.parametrize(
    ("action", "error"),
    [
        ("7", "decisions.action is int, not str"),
        ("NULL", "decisions.action is NoneType, not str"),
    ],
)
def test_a_value_of_another_type_is_refused(conn: sqlite3.Connection, action: str, error: str) -> None:
    tick = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks running")
    sql = f"SELECT {DECISION_COLUMNS.replace('action', f'{action} AS action')} FROM decisions"  # noqa: S608
    with pytest.raises(records.RowError, match=error):
        records.fetch_all(conn, records.Decision, sql)


@dataclass(frozen=True)
class Flagged(records.Row):
    TABLE: ClassVar[str] = "flagged"

    id: int
    done: bool
    cost: float | None


def test_a_flag_reads_as_a_bool_and_a_whole_real_as_a_float(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE flagged (id INTEGER PRIMARY KEY, done INTEGER NOT NULL, cost REAL)")
    conn.execute("INSERT INTO flagged VALUES (1, 1, NULL), (2, 0, 3)")
    # SQLite gives back an integer for a value a query computes, whatever the column's type.
    found = records.fetch_all(conn, Flagged, "SELECT id, done, CAST(cost AS INTEGER) AS cost FROM flagged ORDER BY id")
    assert found == [Flagged(1, done=True, cost=None), Flagged(2, done=False, cost=3.0)]
    assert isinstance(found[1].cost, float)


def test_a_flag_that_is_not_0_or_1_is_refused(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE flagged (id INTEGER PRIMARY KEY, done INTEGER NOT NULL, cost REAL)")
    conn.execute("INSERT INTO flagged VALUES (1, 2, NULL)")
    with pytest.raises(records.RowError, match=r"flagged\.done holds neither 0 nor 1"):
        records.fetch_all(conn, Flagged, "SELECT * FROM flagged")


def test_a_vocabulary_column_reads_as_its_member(conn: sqlite3.Connection, tmp_path: Path) -> None:
    run_id = db.insert_chore_run(conn, tick_id=None, chore="deps", logs_dir=tmp_path)
    db.finish_run(conn, "chore_runs", run_id, ChoreRunStatus.OK, "{}")
    run = db.get_chore_run(conn, run_id)
    assert run is not None
    assert run.status is ChoreRunStatus.OK


def test_a_value_the_vocabulary_does_not_hold_is_refused(conn: sqlite3.Connection, tmp_path: Path) -> None:
    run_id = db.insert_chore_run(conn, tick_id=None, chore="deps", logs_dir=tmp_path)
    conn.execute("UPDATE chore_runs SET status = 'done' WHERE id = ?", (run_id,))
    with pytest.raises(records.RowError, match=r"^chore_runs\.status holds 'done', which is not a ChoreRunStatus$"):
        db.get_chore_run(conn, run_id)


def test_columns_reads_a_typed_row_and_a_sqlite_row_alike(conn: sqlite3.Connection, tmp_path: Path) -> None:
    run_id = db.insert_chore_run(conn, tick_id=None, chore="deps", logs_dir=tmp_path)
    typed = db.get_chore_run(conn, run_id)
    assert typed is not None
    untyped = conn.execute("SELECT * FROM chore_runs WHERE id = ?", (run_id,)).fetchone()
    assert {k: records.columns(typed)[k] for k in untyped.keys()} == dict(untyped)  # noqa: SIM118
