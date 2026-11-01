import re
import sqlite3
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

import pytest

from canopy.core import chore_runs, db, records, review_runs, sql
from canopy.core.vocab import (
    ChoreRunStatus,
    Decider,
    Phase,
    PlanSetting,
    PoolKind,
    ReviewRunStatus,
    StartStatus,
    TickStatus,
)
from tests.canopy.helpers import in_tick, present
from tests.conftest import Journals

# The field types a column of each declared type may be read as.
AFFINITY: dict[str, frozenset[object]] = {
    "INTEGER": frozenset({int, bool}),
    "TEXT": frozenset({str}),
    "REAL": frozenset({float}),
    "BLOB": frozenset({bytes}),
}
PR = "https://github.com/acme/api/pull/7"
DECISION_COLUMNS = "id, tick_id, ticket_key, action, rationale, created_at, repo, chore, pr, decider, kept, item, kind"


def row_types() -> list[type[records.Row]]:
    # A row type a test module defines for itself is not a journal table's.
    return [t for t in records.Row.__subclasses__() if t.__module__ == records.__name__]


@pytest.fixture
def conn(tmp_path: Path, journals: Journals) -> sqlite3.Connection:
    return journals.open(tmp_path / db.DB_FILE_NAME)


def made(text: str) -> sql.Fragment:
    """A query made at run time: these tests build their columns on purpose, to check what a row type refuses."""
    return sql.frag(typing.cast("typing.LiteralString", text))


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
    conn: sqlite3.Connection,
    row_type: type[records.Row],
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
    [first, second] = records.fetch_all(conn, records.Decision, sql.frag("SELECT * FROM decisions ORDER BY id"))
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
        decider=Decider.OVERSEER,
        kept=False,
        item=None,
        kind=None,
    )
    assert (second.ticket_key, second.chore) == (None, "deps")


def test_a_select_reads_its_tables_rows_as_the_row_type(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    for key in ("PROJ-1", "PROJ-2", "PROJ-3"):
        db.record_decision(conn, tick, key, "wait", "checks running")
    query = records.select(records.Decision).where("ticket_key != ?", "PROJ-2").order_by("id DESC")
    assert [d.ticket_key for d in query.all(conn)] == ["PROJ-3", "PROJ-1"]
    assert present(query.limit(1, offset=1).one(conn)).ticket_key == "PROJ-1"
    assert query.where("ticket_key = ?", "PROJ-9").one(conn) is None


def test_a_select_names_its_own_columns_so_a_joined_tables_cannot_shadow_them(conn: sqlite3.Connection) -> None:
    # A decision and its tick both have an `id` and a status-like column; the select reads the decision's alone.
    real = db.start_tick(conn, dry_run=False)
    dry = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, real, "PROJ-1", "wait", "checks running")
    db.record_decision(conn, dry, "PROJ-2", "wait", "checks running")
    query = records.select(records.Decision, "d").join("ticks t ON t.id = d.tick_id").where("t.dry_run = ?", 1)
    assert query.fragment().text.startswith("SELECT d.id, d.tick_id, d.ticket_key, ")
    [decision] = query.all(conn)
    assert (decision.ticket_key, decision.tick_id) == ("PROJ-2", dry)


def test_a_select_goes_in_a_slot_as_any_piece_of_sql(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks running")
    db.record_decision(conn, tick, "PROJ-2", "skip", "no tracker")
    waits = records.select(records.Decision).where("action = ?", "wait")
    counted = sql.execute(conn, sql.select("count(*)").from_("({}) AS w", waits)).fetchone()
    assert counted[0] == 1


def test_a_row_types_query_is_a_select_that_keeps_its_row_type_through_each_clause(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    for key in ("PROJ-1", "PROJ-1", "PROJ-2"):
        db.record_decision(conn, tick, key, "wait", "checks running")
    query = records.select(records.Decision).where("ticket_key = ?", "PROJ-1").order_by("id").limit(1)
    assert isinstance(query, sql.Select)
    assert query.row_type is records.Decision
    assert [d.ticket_key for d in query.all(conn)] == ["PROJ-1"]


@dataclass(frozen=True)
class Checked(records.View):
    ticket_key: str

    def __post_init__(self) -> None:
        assert self.ticket_key


def test_a_record_type_that_needs_its_init_run_is_refused(conn: sqlite3.Connection) -> None:
    # A record is read without its __init__, so a __post_init__ would be skipped.
    with pytest.raises(records.RowError, match="read without its __init__"):
        records.fetch_all(conn, Checked, sql.select("ticket_key").from_("decisions"))


@dataclass(frozen=True)
class DecisionTick(records.View):
    ticket_key: str | None
    status: TickStatus
    dry_run: bool


def test_a_view_reads_a_joins_columns_converted_as_a_rows_are(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks running")
    query = sql.select("d.ticket_key, t.status, t.dry_run").from_("decisions d").join("ticks t ON t.id = d.tick_id")
    [read] = records.fetch_all(conn, DecisionTick, query)
    assert read == DecisionTick("PROJ-1", TickStatus.RUNNING, dry_run=True)
    assert isinstance(read.status, TickStatus)


def test_a_views_refusal_names_the_view(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks running")
    query = (
        sql.select("d.ticket_key, 'gone' AS status, t.dry_run").from_("decisions d").join("ticks t ON t.id = d.tick_id")
    )
    with pytest.raises(records.RowError, match=r"^DecisionTick\.status holds 'gone', which is not a TickStatus$"):
        records.fetch_one(conn, DecisionTick, query)
    with pytest.raises(records.RowError, match=r"^query does not fit DecisionTick: missing dry_run$"):
        records.fetch_one(conn, DecisionTick, sql.select("ticket_key, 'ok' AS status").from_("decisions"))


def test_columns_are_matched_by_name_not_position(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, tick, "PROJ-1", "wait", "checks running")
    reversed_columns = ", ".join(reversed(DECISION_COLUMNS.split(", ")))
    row = records.fetch_one(conn, records.Decision, made(f"SELECT {reversed_columns} FROM decisions"))  # noqa: S608
    assert row is not None
    assert (row.ticket_key, row.action, row.rationale) == ("PROJ-1", "wait", "checks running")


def test_fetch_one_is_none_when_the_query_returns_nothing(conn: sqlite3.Connection) -> None:
    assert records.fetch_one(conn, records.Decision, sql.frag("SELECT * FROM decisions WHERE id = ?", 1)) is None


@pytest.mark.parametrize(
    ("query", "error"),
    [
        (
            "SELECT id, tick_id FROM decisions",
            "missing action, chore, created_at, decider, item, kept, kind, pr, rationale, repo, ticket_key",
        ),
        (f"SELECT {DECISION_COLUMNS}, 1 AS extra FROM decisions", "no field for extra"),  # noqa: S608
        (f"SELECT {DECISION_COLUMNS}, id FROM decisions", "a column is repeated"),  # noqa: S608
    ],
)
def test_a_query_whose_columns_do_not_fit_is_refused_before_any_row(
    conn: sqlite3.Connection,
    query: str,
    error: str,
) -> None:
    # Refused on the query's shape alone: an empty table still fails, so the mistake shows on its first run.
    with pytest.raises(records.RowError, match=f"^query does not fit Decision: {re.escape(error)}$"):
        records.fetch_all(conn, records.Decision, made(query))


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
    query = made(f"SELECT {DECISION_COLUMNS.replace('action', f'{action} AS action')} FROM decisions")  # noqa: S608
    with pytest.raises(records.RowError, match=error):
        records.fetch_all(conn, records.Decision, query)


@dataclass(frozen=True)
class Flagged(records.Row):
    TABLE: ClassVar[typing.LiteralString] = "flagged"

    id: int
    done: bool
    cost: float | None


def test_a_flag_reads_as_a_bool_and_a_whole_real_as_a_float(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE flagged (id INTEGER PRIMARY KEY, done INTEGER NOT NULL, cost REAL)")
    conn.execute("INSERT INTO flagged VALUES (1, 1, NULL), (2, 0, 3)")
    # SQLite gives back an integer for a value a query computes, whatever the column's type.
    found = records.fetch_all(
        conn,
        Flagged,
        sql.frag("SELECT id, done, CAST(cost AS INTEGER) AS cost FROM flagged ORDER BY id"),
    )
    assert found == [Flagged(1, done=True, cost=None), Flagged(2, done=False, cost=3.0)]
    assert isinstance(found[1].cost, float)


def test_a_flag_that_is_not_0_or_1_is_refused(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE flagged (id INTEGER PRIMARY KEY, done INTEGER NOT NULL, cost REAL)")
    conn.execute("INSERT INTO flagged VALUES (1, 2, NULL)")
    with pytest.raises(records.RowError, match=r"flagged\.done holds neither 0 nor 1"):
        records.fetch_all(conn, Flagged, sql.frag("SELECT * FROM flagged"))


def test_a_vocabulary_column_reads_as_its_member(conn: sqlite3.Connection, tmp_path: Path) -> None:
    run_id = chore_runs.insert_chore_run(conn, tick_id=None, chore="deps", logs_dir=tmp_path)
    db.finish_run(conn, "chore_runs", run_id, ChoreRunStatus.OK, "{}")
    run = present(chore_runs.get_chore_run(conn, run_id))
    assert run.status is ChoreRunStatus.OK


def test_a_value_the_vocabulary_does_not_hold_is_refused(conn: sqlite3.Connection, tmp_path: Path) -> None:
    run_id = chore_runs.insert_chore_run(conn, tick_id=None, chore="deps", logs_dir=tmp_path)
    conn.execute("UPDATE chore_runs SET status = 'done' WHERE id = ?", (run_id,))
    with pytest.raises(records.RowError, match=r"^chore_runs\.status holds 'done', which is not a ChoreRunStatus$"):
        chore_runs.get_chore_run(conn, run_id)


def test_columns_reads_a_typed_row_and_a_sqlite_row_alike(conn: sqlite3.Connection, tmp_path: Path) -> None:
    run_id = chore_runs.insert_chore_run(conn, tick_id=None, chore="deps", logs_dir=tmp_path)
    typed = present(chore_runs.get_chore_run(conn, run_id))
    untyped = conn.execute("SELECT * FROM chore_runs WHERE id = ?", (run_id,)).fetchone()
    assert {k: records.columns(typed)[k] for k in untyped.keys()} == dict(untyped)  # noqa: SIM118


def test_a_review_run_reads_its_status_and_pool_as_their_members(conn: sqlite3.Connection, tmp_path: Path) -> None:
    with in_tick(conn) as tick_id:
        run_id = review_runs.insert_review_run(
            conn,
            tick_id=tick_id,
            pr_url=PR,
            sha="abc",
            ticket=None,
            repo=None,
            purpose="request",
            logs_dir=tmp_path,
        )
    [run] = review_runs.review_runs_of(conn, PR)
    assert (run.id, run.status, run.pool) == (run_id, ReviewRunStatus.RUNNING, PoolKind.TREEHOUSE)
    assert isinstance(run.status, ReviewRunStatus)
    assert isinstance(run.pool, PoolKind)


def test_a_start_reads_its_status_as_its_member(conn: sqlite3.Connection) -> None:
    with db.transaction(conn):
        db.set_start(conn, db.SUBJECT_TICKET, "PROJ-1", status=StartStatus.STARTED, channel="cli")
    started = present(db.get_start(conn, db.SUBJECT_TICKET, "PROJ-1"))
    assert (started.status, started.stopped_at, started.channel) == (StartStatus.STARTED, None, "cli")
    with db.transaction(conn):
        db.set_start(conn, db.SUBJECT_TICKET, "PROJ-1", status=StartStatus.STOPPED, channel="web")
    [stopped] = db.starts(conn)
    assert (stopped.status, stopped.started_at, stopped.channel) == (StartStatus.STOPPED, started.started_at, "web")
    assert isinstance(stopped.status, StartStatus)
    assert stopped.stopped_at is not None


def test_a_tick_reads_its_status_as_its_member_and_its_flags_as_bools(conn: sqlite3.Connection) -> None:
    tick_id = db.start_tick(conn, dry_run=True)
    db.set_tick_loop(conn, tick_id, idle=False, woken_by="timer")
    db.finish_tick(conn, tick_id, TickStatus.CANOPY_UNAVAILABLE, "canopy --version failed")
    tick = present(db.get_tick(conn, tick_id))
    assert (tick.status, tick.dry_run, tick.idle, tick.query_due) == (TickStatus.CANOPY_UNAVAILABLE, True, False, None)
    assert isinstance(tick.status, TickStatus)


def test_recent_ticks_count_each_ticks_decisions(conn: sqlite3.Connection) -> None:
    quiet = db.start_tick(conn, dry_run=True)
    busy = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, busy, "PROJ-1", "wait", "checks running")
    db.record_decision(conn, busy, "PROJ-2", "wait", "checks running")
    assert [(t.id, n) for t, n in db.recent_ticks(conn, 5)] == [(busy, 2), (quiet, 0)]


def test_a_ticket_reads_its_phase_and_plan_setting_as_members_and_done_as_a_flag(conn: sqlite3.Connection) -> None:
    db.set_ticket(conn, "PROJ-1", "/ws", phase=Phase.CI_RED, done=True)
    conn.execute("UPDATE tickets SET plan_setting = 'skip' WHERE key = 'PROJ-1'")
    ticket = present(db.get_ticket(conn, "PROJ-1"))
    assert (ticket.phase, ticket.plan_setting, ticket.done) == (Phase.CI_RED, PlanSetting.SKIP, True)
    assert isinstance(ticket.phase, Phase)
    assert isinstance(ticket.plan_setting, PlanSetting)
    assert db.open_tickets(conn) == []


def test_an_insert_writes_through_its_row_type_and_reads_back_what_it_wrote(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    write = records.insert(
        records.Decision,
        tick_id=tick,
        ticket_key="PROJ-1",
        action="wait",
        rationale="checks running",
        created_at="2026-10-29T00:00:00Z",
        decider=Decider.HARNESS,
        kept=True,
    )
    [decision] = write.returned(conn)
    assert (decision.ticket_key, decision.decider, decision.kept) == ("PROJ-1", Decider.HARNESS, True)
    assert present(records.select(records.Decision).one(conn)) == decision


def test_an_update_and_a_delete_read_back_the_rows_they_changed(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    for key in ("PROJ-1", "PROJ-2"):
        db.record_decision(conn, tick, key, "wait", "checks running")
    [updated] = records.update(records.Decision).set(action="skip").where("ticket_key = ?", "PROJ-2").returned(conn)
    assert (updated.ticket_key, updated.action) == ("PROJ-2", "skip")
    gone = records.delete(records.Decision).where("action = ?", "wait").returned(conn)
    assert [d.ticket_key for d in gone] == ["PROJ-1"]
    assert [d.ticket_key for d in records.select(records.Decision).all(conn)] == ["PROJ-2"]


def test_a_write_runs_its_sql_statement(conn: sqlite3.Connection) -> None:
    write = records.update(records.Tick).set(summary="done").where("id = ?", 7)
    assert write.fragment() == sql.update("ticks").set(summary="done").where("id = ?", 7).fragment()  # noqa: TID251
    tick = db.start_tick(conn, dry_run=True)
    assert records.update(records.Tick).set(summary="done").where("id = ?", tick).run(conn).rowcount == 1


@pytest.mark.parametrize(
    ("write", "error"),
    [
        (lambda: records.insert(records.Decision, actoin="wait"), r"^decisions has no column actoin$"),
        (lambda: records.update(records.Tick).set(sumary="x"), r"^ticks has no column sumary$"),
        (lambda: records.insert_rows(records.RunReason, ("run_id", "why")), r"^run_reasons has no column why$"),
        (
            lambda: records.insert(records.ChoreRun, status="finished"),
            r"^chore_runs\.status holds 'finished', which is not a ChoreRunStatus$",
        ),
        (lambda: records.update(records.Tick).set(dry_run=2), r"^ticks\.dry_run holds neither 0 nor 1"),
        (lambda: records.update(records.Decision).set(action=7), r"^decisions\.action is int, not str$"),
        (lambda: records.update(records.Decision).set(action=None), r"^decisions\.action is NoneType, not str$"),
    ],
)
def test_a_write_refuses_a_column_or_a_value_its_row_type_would_not_read(
    write: Callable[[], object],
    error: str,
) -> None:
    # Refused as the statement is built: nothing need run for the mistake to show.
    with pytest.raises(records.RowError, match=error):
        write()


def test_a_write_takes_a_vocabularys_word_a_flag_as_a_bool_and_none_where_the_field_may_be(
    conn: sqlite3.Connection,
) -> None:
    tick = db.start_tick(conn, dry_run=False)
    write = records.update(records.Tick).set(status="ok", dry_run=True, summary=None).where("id = ?", tick)
    [written] = write.returned(conn)
    assert (written.status, written.dry_run, written.summary) == (TickStatus.OK, True, None)


def test_a_write_leaves_a_piece_of_sql_or_a_row_for_sqlite_to_judge(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    computed = records.update(records.Tick).set(summary=sql.frag("'tick ' || id")).where("id = ?", tick)
    assert present(computed.returned(conn)[0].summary) == f"tick {tick}"
    per_row = records.update(records.Tick).set(summary=sql.ROW).where("id = ?", sql.ROW)
    sql.execute_many(conn, per_row, [("again", tick)])
    assert present(db.get_tick(conn, tick)).summary == "again"


def test_an_insert_of_many_rows_holds_each_to_its_row_type(conn: sqlite3.Connection) -> None:
    rows = records.insert_rows(records.Notification, ("sink", "fingerprint", "reason", "sent_at"))
    rows.many(conn, [("desktop", "a", "needs-human", "t"), ("desktop", "b", "needs-human", "t")])
    assert [n.fingerprint for n in records.select(records.Notification).order_by("fingerprint").all(conn)] == ["a", "b"]
    with pytest.raises(records.RowError, match=r"^notifications\.reason is NoneType, not str$"):
        rows.many(conn, [("desktop", "c", "needs-human", "t"), ("desktop", "d", None, "t")])


def test_an_insert_of_many_rows_needs_each_row_to_fill_columns(conn: sqlite3.Connection) -> None:
    upsert = records.insert(records.PrTitle, pr_url=sql.ROW, title=sql.ROW, updated_at="t").on_conflict(
        "(pr_url) DO UPDATE SET title = ?",
        sql.ROW,
    )
    with pytest.raises(ValueError, match="binds a ROW that is not a column's value"):
        upsert.many(conn, [("u", "x", "x")])


def test_returned_refuses_a_write_that_returns_columns_of_its_own(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="already returns columns of its own"):
        records.delete(records.Decision).everything().returning("id").returned(conn)


def test_of_table_names_a_tables_row_type() -> None:
    assert records.of_table("runs") is records.Run
    assert all(records.of_table(t.TABLE) is t for t in row_types())
    with pytest.raises(KeyError):
        records.of_table("flagged")
