"""SQL statements built from pieces of literal SQL and the values bound to them.

Every query canopy runs on its journal is built here and run through `execute` or `execute_many`. A statement is
written clause by clause, in SQL, and each clause's text is a `LiteralString`: SQL written in canopy's code, never a
string built at run time. A value goes in as a `?` and is bound by sqlite3; a piece of SQL built elsewhere, a
subquery or a condition, goes in as a `{}` and keeps its own values. A table or column name chosen at run time comes
from a `Literal` type, which the type checker holds to the names it lists, or through `name`, which takes only an
identifier. So no clause can carry text that came from outside canopy's code, and the type checker says so.

    q = sql.select("id, pid").from_(table).where("status = ?", RunStatus.RUNNING).order_by("id")
    rows = sql.execute(conn, q).fetchall()

Each builder is immutable: a method returns a new statement, so a partial query can be kept in a constant and
finished by each caller. A statement run once per row, by `execute_many`, takes `ROW` where a value differs per row:

    q = sql.update("ticks").set(ended_at=sql.ROW, status=TickStatus.ABANDONED).where("id = ?", sql.ROW)
    sql.execute_many(conn, q, [(now(), tick) for tick in ticks])
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import LiteralString, Protocol, runtime_checkable

#: A value sqlite3 binds to a `?`. A `StrEnum` member is a `str`, and a `bool` an `int`.
type Value = str | int | float | bytes | None


class PerRow(Enum):
    """The type of `ROW`, a value `execute_many` binds from each row in turn."""

    ROW = "row"


#: A value bound from each row a statement is run for, by `execute_many`, in the order the `ROW`s appear.
ROW = PerRow.ROW
#: What a fragment binds to its `?`s: a value, or a `ROW` that `execute_many` fills.
type Bound = Value | PerRow


@runtime_checkable
class Composable(Protocol):
    """Anything that renders as a piece of SQL with its values: a fragment, or a statement built here."""

    def fragment(self) -> Fragment:
        """Render as a fragment.

        Returns:
            The SQL text and its values.
        """
        ...


#: What fills a `{}` or a `?` in a clause's text: a piece of SQL, or a value, or a `ROW`.
type Arg = Composable | Value | PerRow


@dataclass(frozen=True)
class Fragment:
    """A piece of SQL, and the values its `?`s bind, in order.

    Only this module makes one, from literal text: `frag` and the builders are how code elsewhere gets one.
    """

    #: The SQL, with a `?` per value.
    text: str
    params: tuple[Bound, ...] = ()

    def fragment(self) -> Fragment:
        """Render as a fragment: itself.

        Returns:
            This fragment.
        """
        return self


def frag(text: LiteralString, *args: Arg) -> Fragment:
    """Build a piece of SQL from `text`, filling its `?`s with values and its `{}`s with pieces of SQL.

    `args` fill the slots in the order they appear in `text`. A `?` or a `{}` inside a quoted string or identifier
    is part of it, not a slot.

    Returns:
        The fragment.
    """
    return _fill(text, args)


def name(identifier: LiteralString) -> Fragment:
    """Return a table or column name, for a `{}`, chosen from names canopy's code spells out.

    Returns:
        The name, as a fragment.

    Raises:
        ValueError: `identifier` is not a plain identifier.
    """
    _check_identifier(identifier)
    return Fragment(identifier)


def in_(column: LiteralString, values: Collection[Value]) -> Fragment:
    """Return `column IN (?, ...)`, a `?` per value.

    No values give `IN ()`, which SQLite reads as matching nothing.

    Returns:
        The condition.
    """
    return Fragment(f"{column} IN ({', '.join('?' * len(values))})", tuple(values))


def not_in(column: LiteralString, values: Collection[Value]) -> Fragment:
    """Return `column NOT IN (?, ...)`, a `?` per value.

    No values give `NOT IN ()`, which SQLite reads as matching every row. A NULL in `column` matches neither.

    Returns:
        The condition.
    """
    return Fragment(f"{column} NOT IN ({', '.join('?' * len(values))})", tuple(values))


def any_of(*conditions: Composable) -> Fragment:
    """Return the conditions joined by OR, each in parentheses; none gives a condition that is false.

    Returns:
        The condition.
    """
    return _joined(" OR ", conditions, empty="0")


def all_of(*conditions: Composable) -> Fragment:
    """Return the conditions joined by AND, each in parentheses; none gives a condition that is true.

    Returns:
        The condition.
    """
    return _joined(" AND ", conditions, empty="1")


def union(*selects: Composable, every: bool = False) -> Fragment:
    """Return the selects joined by UNION, or by UNION ALL when `every`, keeping each row of each.

    An ORDER BY or LIMIT of the whole goes on a select of the union, as `select("*").from_("({}) AS u", ...)`.

    Returns:
        The compound select.

    Raises:
        ValueError: One of `selects` has an ORDER BY, LIMIT, or OFFSET of its own, which SQLite refuses there.
    """
    if any(isinstance(s, Select) and (s.order or s.row_limit is not None or s.row_offset is not None) for s in selects):
        msg = "a select in a UNION may not have its own ORDER BY, LIMIT, or OFFSET"
        raise ValueError(msg)
    return _joined(" UNION ALL " if every else " UNION ", selects, empty=None, parenthesize=False)


def select(columns: LiteralString, *args: Arg) -> Select:
    """Start a SELECT of `columns`, an expression list that may hold slots for `args`.

    Returns:
        The statement.
    """
    return Select(columns=_fill(columns, args))


def insert(table: LiteralString, **values: Arg) -> Insert:
    """Start an INSERT of one row into `table`: a column per keyword, each a value or a piece of SQL.

    Returns:
        The statement.
    """
    return Insert(table=name(table), values=_assignments(values))


def insert_rows(table: LiteralString, columns: Sequence[LiteralString]) -> Insert:
    """Start an INSERT into `table` of a `ROW` per column, for `execute_many` to run once per row.

    Returns:
        The statement.
    """
    return Insert(table=name(table), values=tuple((c, Fragment("?", (ROW,))) for c in map(_identifier, columns)))


def insert_from(table: LiteralString, columns: Sequence[LiteralString], rows: Composable) -> Insert:
    """Start an INSERT into `table`'s `columns` of the rows a SELECT returns, a value per column in order.

    An `on_conflict` on one needs a WHERE in the SELECT, or SQLite reads the ON as the SELECT's join.

    Returns:
        The statement.

    Raises:
        ValueError: `columns` is empty.
    """
    if not columns:
        msg = f"an INSERT into {table} from a SELECT names no column"
        raise ValueError(msg)
    return Insert(table=name(table), values=(), selected=tuple(map(_identifier, columns)), source=rows.fragment())


def update(table: LiteralString) -> Update:
    """Start an UPDATE of `table`.

    Returns:
        The statement.
    """
    return Update(table=name(table))


def delete(table: LiteralString) -> Delete:
    """Start a DELETE from `table`.

    Returns:
        The statement.
    """
    return Delete(table=name(table))


def execute(conn: sqlite3.Connection, statement: Composable) -> sqlite3.Cursor:
    """Run `statement` on `conn`.

    Returns:
        The cursor, to read its rows from.

    Raises:
        ValueError: `statement` holds a `ROW`, which only `execute_many` fills.
    """
    built = statement.fragment()
    values = [p for p in built.params if not isinstance(p, PerRow)]
    if len(values) < len(built.params):
        msg = "a statement with a ROW in it runs once per row, through execute_many"
        raise ValueError(msg)
    return conn.execute(built.text, values)


def execute_many(conn: sqlite3.Connection, statement: Composable, rows: Iterable[Sequence[Value]]) -> sqlite3.Cursor:
    """Run `statement` on `conn` once for each of `rows`, each filling the statement's `ROW`s in order.

    Its other values are bound as they are, the same for every row.

    Returns:
        The cursor.

    Raises:
        ValueError: `statement` holds no `ROW`, or a row has more or fewer values than it has `ROW`s.
    """
    built = statement.fragment()
    wanted = sum(isinstance(p, PerRow) for p in built.params)
    if not wanted:
        msg = "a statement run for many rows needs a ROW where a value differs per row"
        raise ValueError(msg)
    return conn.executemany(built.text, (_filled(built.params, row, wanted) for row in rows))


@dataclass(frozen=True)
class Select:
    """A SELECT, each clause held apart until it is rendered, in SQL's order whatever order it was built in."""

    columns: Fragment
    distinct: bool = False
    #: The common table expressions of its WITH, and whether any is recursive.
    ctes: tuple[Fragment, ...] = ()
    recursive: bool = False
    source: Fragment | None = None
    joins: tuple[Fragment, ...] = ()
    conditions: tuple[Fragment, ...] = ()
    groups: Fragment | None = None
    having_conditions: tuple[Fragment, ...] = ()
    order: Fragment | None = None
    #: Its LIMIT and OFFSET, bound as values.
    row_limit: int | None = None
    row_offset: int | None = None

    def with_(self, cte: LiteralString, *args: Arg, recursive: bool = False) -> Select:
        """Add a common table expression, `name(columns) AS (select)`, to the WITH.

        Returns:
            The statement with it.
        """
        return replace(self, ctes=(*self.ctes, _fill(cte, args)), recursive=self.recursive or recursive)

    def unique(self) -> Select:
        """Make it SELECT DISTINCT.

        Returns:
            The statement, distinct.
        """
        return replace(self, distinct=True)

    def from_(self, source: LiteralString, *args: Arg) -> Select:
        """Set what it selects from: a table, with an alias if any, or a `({}) AS alias` subquery.

        Returns:
            The statement with it.
        """
        return replace(self, source=_fill(source, args))

    def join(self, table_on: LiteralString, *args: Arg) -> Select:
        """Add an inner JOIN of `table alias ON condition`.

        Returns:
            The statement with it.
        """
        return replace(self, joins=(*self.joins, _prefixed("JOIN ", table_on, args)))

    def left_join(self, table_on: LiteralString, *args: Arg) -> Select:
        """Add a LEFT JOIN of `table alias ON condition`.

        Returns:
            The statement with it.
        """
        return replace(self, joins=(*self.joins, _prefixed("LEFT JOIN ", table_on, args)))

    def where(self, condition: LiteralString, *args: Arg) -> Select:
        """Add a condition, ANDed with any already there.

        Returns:
            The statement with it.
        """
        return replace(self, conditions=(*self.conditions, _fill(condition, args)))

    def where_in(self, column: LiteralString, values: Collection[Value]) -> Select:
        """Add `column IN (...)` of `values`, ANDed with any condition already there.

        Returns:
            The statement with it.
        """
        return replace(self, conditions=(*self.conditions, in_(column, values)))

    def where_not_in(self, column: LiteralString, values: Collection[Value]) -> Select:
        """Add `column NOT IN (...)` of `values`, ANDed with any condition already there.

        Returns:
            The statement with it.
        """
        return replace(self, conditions=(*self.conditions, not_in(column, values)))

    def group_by(self, columns: LiteralString, *args: Arg) -> Select:
        """Set its GROUP BY.

        Returns:
            The statement with it.
        """
        return replace(self, groups=_fill(columns, args))

    def having(self, condition: LiteralString, *args: Arg) -> Select:
        """Add a HAVING condition, ANDed with any already there.

        Returns:
            The statement with it.
        """
        return replace(self, having_conditions=(*self.having_conditions, _fill(condition, args)))

    def order_by(self, terms: LiteralString, *args: Arg) -> Select:
        """Set its ORDER BY.

        Returns:
            The statement with it.
        """
        return replace(self, order=_fill(terms, args))

    def limit(self, rows: int, offset: int | None = None) -> Select:
        """Set its LIMIT, and its OFFSET if given.

        Returns:
            The statement with them.
        """
        return replace(self, row_limit=rows, row_offset=offset)

    def fragment(self) -> Fragment:
        """Render the statement.

        Returns:
            Its SQL and values.

        Raises:
            ValueError: It joins a table with nothing to join it to.
        """
        if self.joins and self.source is None:
            msg = "a SELECT with a JOIN needs a FROM"
            raise ValueError(msg)
        parts: list[Fragment] = []
        if self.ctes:
            parts += [
                _joined(
                    ", ",
                    self.ctes,
                    empty=None,
                    parenthesize=False,
                    prefix="WITH RECURSIVE " if self.recursive else "WITH ",
                )
            ]
        parts.append(_prefixed("SELECT DISTINCT " if self.distinct else "SELECT ", "{}", (self.columns,)))
        if self.source is not None:
            parts.append(_prefixed("FROM ", "{}", (self.source,)))
        parts += self.joins
        if self.conditions:
            parts.append(_prefixed("WHERE ", "{}", (_conditions(self.conditions),)))
        if self.groups is not None:
            parts.append(_prefixed("GROUP BY ", "{}", (self.groups,)))
        if self.having_conditions:
            parts.append(_prefixed("HAVING ", "{}", (_conditions(self.having_conditions),)))
        if self.order is not None:
            parts.append(_prefixed("ORDER BY ", "{}", (self.order,)))
        if self.row_limit is not None:
            parts.append(Fragment("LIMIT ?", (self.row_limit,)))
        if self.row_offset is not None:
            parts.append(Fragment("OFFSET ?", (self.row_offset,)))
        return _joined(" ", parts, empty=None, parenthesize=False)


@dataclass(frozen=True)
class Insert:
    """An INSERT of one row, with what it does on a conflict and what it returns."""

    table: Fragment
    #: Each column and what it is set to: a `?` and its value, or a piece of SQL.
    values: tuple[tuple[str, Fragment], ...]
    #: `OR IGNORE` or `OR REPLACE`, if either.
    resolution: str = ""
    conflict: Fragment | None = None
    returns: Fragment | None = None
    #: For an INSERT of a SELECT's rows: the columns they fill, and the SELECT.
    selected: tuple[str, ...] = ()
    source: Fragment | None = None

    def or_ignore(self) -> Insert:
        """Make it INSERT OR IGNORE.

        Returns:
            The statement so.
        """
        return replace(self, resolution=" OR IGNORE")

    def or_replace(self) -> Insert:
        """Make it INSERT OR REPLACE.

        Returns:
            The statement so.
        """
        return replace(self, resolution=" OR REPLACE")

    def on_conflict(self, action: LiteralString, *args: Arg) -> Insert:
        """Add an upsert clause: `(columns) DO NOTHING`, or `(columns) DO UPDATE SET ...`.

        Returns:
            The statement with it.
        """
        return replace(self, conflict=_prefixed("ON CONFLICT ", action, args))

    def returning(self, columns: LiteralString, *args: Arg) -> Insert:
        """Add a RETURNING of `columns`.

        Returns:
            The statement with it.
        """
        return replace(self, returns=_prefixed("RETURNING ", columns, args))

    def fragment(self) -> Fragment:
        """Render the statement.

        Returns:
            Its SQL and values.

        Raises:
            ValueError: It sets no column.
        """
        if self.source is not None:
            into = f"INSERT{self.resolution} INTO {self.table.text} ({', '.join(self.selected)}) "
            head = Fragment(into + self.source.text, self.source.params)
        elif not self.values:
            msg = f"an INSERT into {self.table.text} sets no column"
            raise ValueError(msg)
        else:
            columns = ", ".join(c for c, _ in self.values)
            row = _joined(", ", [v for _, v in self.values], empty=None, parenthesize=False)
            head = Fragment(
                f"INSERT{self.resolution} INTO {self.table.text} ({columns}) VALUES ({row.text})", row.params
            )
        return _joined(
            " ", [p for p in (head, self.conflict, self.returns) if p is not None], empty=None, parenthesize=False
        )


@dataclass(frozen=True)
class Update:
    """An UPDATE: what it sets, of which rows, and what it returns."""

    table: Fragment
    #: Each assignment, `column = ?` or `column = expression`.
    assignments: tuple[Fragment, ...] = ()
    conditions: tuple[Fragment, ...] = ()
    returns: Fragment | None = None
    #: Set by `everything`, so an UPDATE with no condition is meant.
    unconditional: bool = False

    def set(self, **values: Arg) -> Update:
        """Set a column per keyword to a value or a piece of SQL.

        Returns:
            The statement with them.
        """
        new = tuple(Fragment(f"{c} = {v.text}", v.params) for c, v in _assignments(values))
        return replace(self, assignments=(*self.assignments, *new))

    def set_to(self, assignment: LiteralString, *args: Arg) -> Update:
        """Add an assignment written in SQL, such as `failures = failures + 1`.

        Returns:
            The statement with it.
        """
        return replace(self, assignments=(*self.assignments, _fill(assignment, args)))

    def where(self, condition: LiteralString, *args: Arg) -> Update:
        """Add a condition, ANDed with any already there.

        Returns:
            The statement with it.
        """
        return replace(self, conditions=(*self.conditions, _fill(condition, args)))

    def where_in(self, column: LiteralString, values: Collection[Value]) -> Update:
        """Add `column IN (...)` of `values`, ANDed with any condition already there.

        Returns:
            The statement with it.
        """
        return replace(self, conditions=(*self.conditions, in_(column, values)))

    def where_not_in(self, column: LiteralString, values: Collection[Value]) -> Update:
        """Add `column NOT IN (...)` of `values`, ANDed with any condition already there.

        Returns:
            The statement with it.
        """
        return replace(self, conditions=(*self.conditions, not_in(column, values)))

    def everything(self) -> Update:
        """Update every row: an UPDATE with no condition is refused unless it says so.

        Returns:
            The statement so.
        """
        return replace(self, unconditional=True)

    def returning(self, columns: LiteralString, *args: Arg) -> Update:
        """Add a RETURNING of `columns`.

        Returns:
            The statement with it.
        """
        return replace(self, returns=_prefixed("RETURNING ", columns, args))

    def fragment(self) -> Fragment:
        """Render the statement.

        Returns:
            Its SQL and values.

        Raises:
            ValueError: It sets nothing, or has no condition and was not told to update everything.
        """
        if not self.assignments:
            msg = f"an UPDATE of {self.table.text} sets nothing"
            raise ValueError(msg)
        if not self.conditions and not self.unconditional:
            msg = f"an update of {self.table.text}'s rows has no condition; call everything() to update every row"
            raise ValueError(msg)
        parts = [
            Fragment(f"UPDATE {self.table.text} SET"),
            _joined(", ", self.assignments, empty=None, parenthesize=False),
        ]
        if self.conditions:
            parts.append(_prefixed("WHERE ", "{}", (_conditions(self.conditions),)))
        if self.returns is not None:
            parts.append(self.returns)
        return _joined(" ", parts, empty=None, parenthesize=False)


@dataclass(frozen=True)
class Delete:
    """A DELETE: of which rows, and what it returns."""

    table: Fragment
    conditions: tuple[Fragment, ...] = ()
    returns: Fragment | None = None
    #: Set by `everything`, so a DELETE with no condition is meant.
    unconditional: bool = False

    def where(self, condition: LiteralString, *args: Arg) -> Delete:
        """Add a condition, ANDed with any already there.

        Returns:
            The statement with it.
        """
        return replace(self, conditions=(*self.conditions, _fill(condition, args)))

    def where_in(self, column: LiteralString, values: Collection[Value]) -> Delete:
        """Add `column IN (...)` of `values`, ANDed with any condition already there.

        Returns:
            The statement with it.
        """
        return replace(self, conditions=(*self.conditions, in_(column, values)))

    def where_not_in(self, column: LiteralString, values: Collection[Value]) -> Delete:
        """Add `column NOT IN (...)` of `values`, ANDed with any condition already there.

        Returns:
            The statement with it.
        """
        return replace(self, conditions=(*self.conditions, not_in(column, values)))

    def everything(self) -> Delete:
        """Delete every row: a DELETE with no condition is refused unless it says so.

        Returns:
            The statement so.
        """
        return replace(self, unconditional=True)

    def returning(self, columns: LiteralString, *args: Arg) -> Delete:
        """Add a RETURNING of `columns`.

        Returns:
            The statement with it.
        """
        return replace(self, returns=_prefixed("RETURNING ", columns, args))

    def fragment(self) -> Fragment:
        """Render the statement.

        Returns:
            Its SQL and values.

        Raises:
            ValueError: It has no condition and was not told to delete everything.
        """
        if not self.conditions and not self.unconditional:
            msg = f"a delete of {self.table.text}'s rows has no condition; call everything() to delete every row"
            raise ValueError(msg)
        parts = [Fragment(f"DELETE FROM {self.table.text}")]  # noqa: S608  (a name `name` checked)
        if self.conditions:
            parts.append(_prefixed("WHERE ", "{}", (_conditions(self.conditions),)))
        if self.returns is not None:
            parts.append(self.returns)
        return _joined(" ", parts, empty=None, parenthesize=False)


# A slot, or a quoted string or identifier, whose `?`s and `{}`s are not slots.
_TOKEN = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\?|\{\}")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _filled(params: Sequence[Bound], row: Sequence[Value], wanted: int) -> list[Value]:
    if len(row) != wanted:
        msg = f"a row of {len(row)} values for a statement with {wanted} ROWs"
        raise ValueError(msg)
    values = iter(row)
    return [next(values) if isinstance(p, PerRow) else p for p in params]


def _fill(text: str, args: Sequence[Arg]) -> Fragment:
    out: list[str] = []
    params: list[Bound] = []
    rest = list(args)
    at = 0
    for match in _TOKEN.finditer(text):
        slot = match.group()
        if slot not in {"?", "{}"}:
            continue
        out.append(text[at : match.start()])
        at = match.end()
        if not rest:
            msg = f"{text!r} has more slots than the {len(args)} values given"
            raise ValueError(msg)
        arg = rest.pop(0)
        if slot == "?":
            if isinstance(arg, Composable):
                msg = f"a `?` in {text!r} takes a value; a piece of SQL goes in a `{{}}`"
                raise TypeError(msg)
            out.append("?")
            params.append(arg)
        else:
            if not isinstance(arg, Composable):
                msg = f"a `{{}}` in {text!r} takes a piece of SQL; a value goes in a `?`"
                raise TypeError(msg)
            inner = arg.fragment()
            out.append(inner.text)
            params += inner.params
    if rest:
        msg = f"{text!r} has fewer slots than the {len(args)} values given"
        raise ValueError(msg)
    out.append(text[at:])
    return Fragment("".join(out), tuple(params))


def _joined(
    sep: str,
    pieces: Iterable[Composable],
    *,
    empty: str | None,
    parenthesize: bool = True,
    prefix: str = "",
) -> Fragment:
    rendered = [p.fragment() for p in pieces]
    if not rendered:
        if empty is None:
            msg = "nothing to join"
            raise ValueError(msg)
        return Fragment(empty)
    texts = [f"({r.text})" if parenthesize else r.text for r in rendered]
    return Fragment(prefix + sep.join(texts), tuple(v for r in rendered for v in r.params))


def _conditions(conditions: Sequence[Fragment]) -> Fragment:
    # One condition stays as written; several are each parenthesized, so an OR in one cannot swallow the others.
    return conditions[0] if len(conditions) == 1 else all_of(*conditions)


def _prefixed(prefix: str, text: str, args: Sequence[Arg]) -> Fragment:
    inner = _fill(text, args)
    return Fragment(prefix + inner.text, inner.params)


def _assignments(values: Mapping[str, Arg]) -> tuple[tuple[str, Fragment], ...]:
    return tuple(
        (_identifier(column), value.fragment() if isinstance(value, Composable) else Fragment("?", (value,)))
        for column, value in values.items()
    )


def _identifier(text: str) -> str:
    _check_identifier(text)
    return text


def _check_identifier(text: str) -> None:
    if not _IDENTIFIER.fullmatch(text):
        msg = f"{text!r} is not a table or column name"
        raise ValueError(msg)
