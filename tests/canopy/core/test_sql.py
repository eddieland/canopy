# These tests are of the builders a write through a row type is made of.
# ruff: noqa: TID251
import sqlite3
from pathlib import Path

import pytest

from canopy.core import db, records, sql
from canopy.core.vocab import RunStatus, TickStatus
from tests.conftest import Journals


@pytest.fixture
def conn(tmp_path: Path, journals: Journals) -> sqlite3.Connection:
    return journals.open(tmp_path / db.DB_FILE_NAME)


def rendered(statement: sql.Composable) -> tuple[str, tuple[sql.Bound, ...]]:
    built = statement.fragment()
    return built.text, built.params


def test_a_fragment_fills_its_slots_in_the_order_they_appear() -> None:
    inner = sql.frag("kind = ?", "plan")
    assert rendered(sql.frag("status = ? AND ({}) AND id > ?", RunStatus.DONE, inner, 7)) == (
        "status = ? AND (kind = ?) AND id > ?",
        (RunStatus.DONE, "plan", 7),
    )


def test_a_slot_inside_a_quoted_string_or_name_is_part_of_it() -> None:
    assert rendered(sql.frag("body = '? {}' AND \"odd?\" = ?", 1)) == ("body = '? {}' AND \"odd?\" = ?", (1,))


@pytest.mark.parametrize(
    ("text", "args", "error"),
    [
        ("a = ? AND b = ?", (1,), ValueError),
        ("a = ?", (1, 2), ValueError),
        ("a = ?", (sql.frag("1"),), TypeError),
        ("a IN ({})", (1,), TypeError),
    ],
)
def test_a_fragment_refuses_args_that_do_not_fit_its_slots(
    text: str,
    args: tuple[sql.Arg, ...],
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        sql.frag(text, *args)  # pyrefly: ignore[bad-argument-type]  # a str, to test the slots alone


def test_a_name_is_only_an_identifier() -> None:
    assert sql.name("chore_runs").text == "chore_runs"
    with pytest.raises(ValueError, match="not a table or column name"):
        sql.name("runs; DROP TABLE ticks")


def test_an_in_list_has_a_mark_per_value_and_an_empty_one_matches_nothing(conn: sqlite3.Connection) -> None:
    ticks = [db.start_tick(conn, dry_run=True) for _ in range(3)]
    assert rendered(sql.in_("id", ticks[1:])) == ("id IN (?, ?)", tuple(ticks[1:]))
    found = sql.execute(conn, sql.select("id").from_("ticks").where_in("id", ticks[1:]).order_by("id"))
    assert [int(r[0]) for r in found] == ticks[1:]
    assert sql.execute(conn, sql.select("count(*)").from_("ticks").where_in("id", [])).fetchone()[0] == 0


def test_a_select_renders_its_clauses_in_sqls_order_whatever_order_they_were_built_in() -> None:
    q = (
        sql.select("r.ticket_key, count(*) AS n")
        .order_by("n DESC")
        .limit(5, offset=10)
        .having("count(*) > ?", 1)
        .group_by("r.ticket_key")
        .where("r.status = ?", RunStatus.FAILED)
        .left_join("tickets t ON t.key = r.ticket_key")
        .from_("runs r")
        .with_("recent(id) AS ({})", sql.select("id").from_("runs").where("started_at > ?", "2026-10-01"))
        .unique()
    )
    assert rendered(q) == (
        (
            "WITH recent(id) AS (SELECT id FROM runs WHERE started_at > ?) SELECT DISTINCT r.ticket_key, count(*) AS n "
            "FROM runs r LEFT JOIN tickets t ON t.key = r.ticket_key WHERE r.status = ? GROUP BY r.ticket_key "
            "HAVING count(*) > ? ORDER BY n DESC LIMIT ? OFFSET ?"
        ),
        ("2026-10-01", RunStatus.FAILED, 1, 5, 10),
    )


def test_conditions_are_anded_each_in_parentheses_so_an_or_keeps_to_its_own() -> None:
    one = sql.select("*").from_("ticks").where("status = ? OR idle = ?", TickStatus.OK, 1)
    assert rendered(one)[0] == "SELECT * FROM ticks WHERE status = ? OR idle = ?"
    two = one.where("id > ?", 3)
    assert rendered(two) == (
        "SELECT * FROM ticks WHERE (status = ? OR idle = ?) AND (id > ?)",
        (TickStatus.OK, 1, 3),
    )
    assert rendered(sql.any_of()) == ("0", ())
    assert rendered(sql.all_of()) == ("1", ())
    assert rendered(sql.any_of(sql.frag("a = ?", 1), sql.frag("b = ?", 2))) == ("(a = ?) OR (b = ?)", (1, 2))


def test_a_statement_is_immutable_so_a_partial_one_can_be_finished_many_ways() -> None:
    base = sql.select("*").from_("runs r")
    running = base.where("r.status = ?", RunStatus.RUNNING)
    assert rendered(base) == ("SELECT * FROM runs r", ())
    assert rendered(running) == ("SELECT * FROM runs r WHERE r.status = ?", (RunStatus.RUNNING,))


def test_selects_join_by_union_inside_another_statement() -> None:
    back = sql.select("id").from_("back")
    ahead = sql.select("id").from_("ahead")
    q = sql.select("*").from_("memories").where("id IN ({})", sql.union(back, ahead))
    assert rendered(q)[0] == "SELECT * FROM memories WHERE id IN (SELECT id FROM back UNION SELECT id FROM ahead)"
    assert rendered(sql.union(back, ahead, every=True))[0] == "SELECT id FROM back UNION ALL SELECT id FROM ahead"
    with pytest.raises(ValueError, match="its own ORDER BY"):
        sql.union(back, ahead.order_by("id"))
    with pytest.raises(ValueError, match="its own ORDER BY"):
        sql.union(back.limit(1), ahead)


def test_a_select_that_joins_needs_something_to_join_to() -> None:
    with pytest.raises(ValueError, match="needs a FROM"):
        sql.select("*").join("tickets t ON t.key = r.ticket_key").fragment()


def test_an_insert_binds_its_values_upserts_and_returns(conn: sqlite3.Connection) -> None:
    first = sql.insert("pr_titles", pr_url="u", title="one", updated_at=sql.frag("?", "t1"))
    assert rendered(first) == (
        "INSERT INTO pr_titles (pr_url, title, updated_at) VALUES (?, ?, ?)",
        ("u", "one", "t1"),
    )
    sql.execute(conn, first)
    again = (
        sql.insert("pr_titles", pr_url="u", title="two", updated_at="t2")
        .on_conflict("(pr_url) DO UPDATE SET title = excluded.title")
        .returning("title")
    )
    assert sql.execute(conn, again).fetchone()[0] == "two"
    assert sql.execute(conn, sql.insert("pr_titles", pr_url="u", title="x", updated_at="t").or_ignore()).rowcount == 0
    assert rendered(sql.insert("pause", id=1, paused_at="t", channel="cli").or_replace())[0].startswith(
        "INSERT OR REPLACE INTO pause",
    )


def test_rows_inserted_many_at_a_time_take_their_values_from_the_rows(conn: sqlite3.Connection) -> None:
    rows = sql.insert_rows("pr_titles", ("pr_url", "title", "updated_at"))
    sql.execute_many(conn, rows, [("a", "A", "t"), ("b", "B", "t")])
    assert [tuple(r) for r in sql.execute(conn, sql.select("pr_url, title").from_("pr_titles").order_by("pr_url"))] == [
        ("a", "A"),
        ("b", "B"),
    ]
    with pytest.raises(ValueError, match="needs a ROW"):
        sql.execute_many(conn, sql.insert("pr_titles", pr_url="c", title="C", updated_at="t"), [()])


def test_a_statement_run_per_row_fills_its_rows_and_keeps_its_other_values(conn: sqlite3.Connection) -> None:
    ticks = [db.start_tick(conn, dry_run=True) for _ in range(3)]
    closed = sql.update("ticks").set(status=TickStatus.OK, summary=sql.ROW).where("id = ?", sql.ROW)
    assert rendered(closed) == (
        "UPDATE ticks SET status = ?, summary = ? WHERE id = ?",
        (TickStatus.OK, sql.ROW, sql.ROW),
    )
    sql.execute_many(conn, closed, [("first", ticks[0]), ("second", ticks[1])])
    summaries = sql.select("summary, status").from_("ticks").order_by("id")
    assert [tuple(r) for r in sql.execute(conn, summaries)] == [("first", "ok"), ("second", "ok"), (None, "running")]
    sql.execute_many(conn, sql.delete("ticks").where("id = ?", sql.ROW), [(t,) for t in ticks[:2]])
    assert [int(r[0]) for r in sql.execute(conn, sql.select("id").from_("ticks"))] == ticks[2:]


def test_a_row_must_fill_every_row_and_only_execute_many_fills_them(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    closed = sql.update("ticks").set(summary=sql.ROW).where("id = ?", sql.ROW)
    with pytest.raises(ValueError, match="a row of 1 values for a statement with 2 ROWs"):
        sql.execute_many(conn, closed, [(tick,)])
    with pytest.raises(ValueError, match="through execute_many"):
        sql.execute(conn, closed)
    with pytest.raises(TypeError, match="takes a piece of SQL"):
        sql.frag("id IN ({})", sql.ROW)


def test_an_insert_takes_a_selects_rows(conn: sqlite3.Connection) -> None:
    sql.execute_many(conn, sql.insert_rows("pr_titles", ("pr_url", "title", "updated_at")), [("a", "A", "t")])
    copied = sql.select("pr_url || '/2', title, ?", "t2").from_("pr_titles").where("pr_url = ?", "a")
    q = sql.insert_from("pr_titles", ("pr_url", "title", "updated_at"), copied)
    assert rendered(q) == (
        (
            "INSERT INTO pr_titles (pr_url, title, updated_at) SELECT pr_url || '/2', title, ? FROM pr_titles "
            "WHERE pr_url = ?"
        ),
        ("t2", "a"),
    )
    sql.execute(conn, q)
    assert sql.execute(conn, q.or_ignore()).rowcount == 0
    found = sql.select("pr_url, updated_at").from_("pr_titles").order_by("pr_url")
    assert [tuple(r) for r in sql.execute(conn, found)] == [("a", "t"), ("a/2", "t2")]
    with pytest.raises(ValueError, match="names no column"):
        sql.insert_from("pr_titles", (), copied).fragment()


def test_not_in_keeps_the_rows_outside_the_list_and_every_row_for_none(conn: sqlite3.Connection) -> None:
    ticks = [db.start_tick(conn, dry_run=True) for _ in range(3)]
    assert rendered(sql.not_in("id", ticks[:2])) == ("id NOT IN (?, ?)", tuple(ticks[:2]))
    outside = sql.select("id").from_("ticks").where_not_in("id", ticks[:2])
    assert [int(r[0]) for r in sql.execute(conn, outside)] == ticks[2:]
    every = sql.select("count(*)").from_("ticks").where_not_in("id", [])
    assert sql.execute(conn, every).fetchone()[0] == 3
    sql.execute(conn, sql.update("ticks").set(summary="kept").where_not_in("id", ticks[:1]))
    sql.execute(conn, sql.delete("ticks").where_not_in("id", ticks[:1]))
    assert [int(r[0]) for r in sql.execute(conn, sql.select("id").from_("ticks"))] == ticks[:1]


def test_an_update_sets_by_keyword_or_in_sql_and_returns(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    q = (
        sql.update("ticks")
        .set(status=TickStatus.OK, summary="done")
        .set_to("tokens_input = coalesce(tokens_input, 0) + ?", 5)
        .where("id = ?", tick)
        .returning("status, tokens_input")
    )
    assert rendered(q) == (
        (
            "UPDATE ticks SET status = ?, summary = ?, tokens_input = coalesce(tokens_input, 0) + ? WHERE id = ? "
            "RETURNING status, tokens_input"
        ),
        (TickStatus.OK, "done", 5, tick),
    )
    assert tuple(sql.execute(conn, q).fetchone()) == ("ok", 5)
    with pytest.raises(ValueError, match="sets nothing"):
        sql.update("ticks").where("id = ?", tick).fragment()
    with pytest.raises(ValueError, match="no condition"):
        sql.update("ticks").set(summary="all").fragment()
    assert sql.execute(conn, sql.update("ticks").set(summary="all").everything()).rowcount == 1


def test_an_insert_that_sets_no_column_is_refused() -> None:
    with pytest.raises(ValueError, match="sets no column"):
        sql.insert("ticks").fragment()


def test_a_keyword_column_is_held_to_a_name(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not a table or column name"):
        sql.update("ticks").set(**{"status = 'ok' --": "x"})
    with pytest.raises(ValueError, match="not a table or column name"):
        sql.insert("ticks", **{"id) VALUES (1); --": 1})


def test_a_delete_needs_a_condition_unless_it_says_it_deletes_everything(conn: sqlite3.Connection) -> None:
    ticks = [db.start_tick(conn, dry_run=True) for _ in range(3)]
    gone = sql.execute(conn, sql.delete("ticks").where("id = ?", ticks[0]).returning("id")).fetchall()
    assert [int(r[0]) for r in gone] == ticks[:1]
    with pytest.raises(ValueError, match="no condition"):
        sql.delete("ticks").fragment()
    assert sql.execute(conn, sql.delete("ticks").everything()).rowcount == 2


def test_records_read_a_built_statement_as_typed_rows(conn: sqlite3.Connection) -> None:
    tick = db.start_tick(conn, dry_run=True)
    q = sql.select("*").from_("ticks").where("id = ?", tick)
    assert [t.id for t in records.fetch_all(conn, records.Tick, q)] == [tick]
    assert records.fetch_one(conn, records.Tick, q.where("dry_run = ?", 0)) is None


class Lookalike:
    """An object with a `fragment` method of its own, which does not make it a piece of SQL."""

    def fragment(self) -> sql.Fragment:
        return sql.frag("1; DROP TABLE ticks")


def test_only_sqls_own_classes_are_pieces_of_sql() -> None:
    with pytest.raises(TypeError, match="takes a piece of SQL"):
        sql.frag("id IN ({})", Lookalike())  # pyrefly: ignore[bad-argument-type]  # a lookalike, to test it is refused


def test_a_clause_read_once_is_filled_anew_each_time() -> None:
    def ticks_of(status: TickStatus) -> sql.Select:
        return sql.select("id").from_("ticks").where("status = ? AND summary != '?'", status)

    assert rendered(ticks_of(TickStatus.OK)) == ("SELECT id FROM ticks WHERE status = ? AND summary != '?'", ("ok",))
    assert rendered(ticks_of(TickStatus.RUNNING))[1] == (TickStatus.RUNNING,)
