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

A clause's text is read for its slots once, the first time it is used, and kept: canopy writes each in its code, so
there are a few hundred, and a query built on every call pays for its values alone.
"""

from __future__ import annotations

import functools
import re
import sqlite3
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import Field, dataclass
from enum import Enum
from typing import Any, ClassVar, LiteralString, Self, override

#: A value sqlite3 binds to a `?`. A `StrEnum` member is a `str`, and a `bool` an `int`.
type Value = str | int | float | bytes | None


class PerRow(Enum):
    """The type of `ROW`, a value `execute_many` binds from each row in turn."""

    ROW = "row"


#: A value bound from each row a statement is run for, by `execute_many`, in the order the `ROW`s appear.
ROW = PerRow.ROW
#: What a fragment binds to its `?`s: a value, or a `ROW` that `execute_many` fills.
type Bound = Value | PerRow


class Composable:
    """Anything that renders as a piece of SQL with its values: a fragment, or a statement built here.

    A base class, not a protocol: only this module's classes, and their subclasses, are pieces of SQL, and telling one
    from a value, as every slot filled does, is a plain `isinstance`.
    """

    __slots__ = ()

    def fragment(self) -> Fragment:
        """Render as a fragment.

        Returns:
            The SQL text and its values.
        """
        raise NotImplementedError


#: What fills a `{}` or a `?` in a clause's text: a piece of SQL, or a value, or a `ROW`.
type Arg = Composable | Value | PerRow


@dataclass(frozen=True)
class Fragment(Composable):
    """A piece of SQL, and the values its `?`s bind, in order.

    Only this module makes one, from literal text: `frag` and the builders are how code elsewhere gets one.
    """

    #: The SQL, with a `?` per value.
    text: str
    params: tuple[Bound, ...] = ()

    @override
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
    return Fragment(_identifier(identifier))


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
    return Insert(table=name(table)).set(**values)


def insert_rows(table: LiteralString, columns: Sequence[LiteralString]) -> Insert:
    """Start an INSERT into `table` of a `ROW` per column, for `execute_many` to run once per row.

    Returns:
        The statement.
    """
    return Insert(table=name(table)).set(**dict.fromkeys(columns, ROW))


def insert_from(table: LiteralString, columns: Sequence[LiteralString], rows: Composable) -> Insert:
    """Start an INSERT into `table`'s `columns` of the rows a SELECT returns, a value per column in order.

    An `on_conflict` on one needs a WHERE in the SELECT, or SQLite reads the ON as the SELECT's join.

    Returns:
        The statement.
    """
    return Insert(table=name(table)).of_rows(columns, rows)


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
    if ROW in built.params:
        msg = "a statement with a ROW in it runs once per row, through execute_many"
        raise ValueError(msg)
    return conn.execute(built.text, built.params)


def execute_many(conn: sqlite3.Connection, statement: Composable, rows: Iterable[Sequence[Value]]) -> sqlite3.Cursor:
    """Run `statement` on `conn` once for each of `rows`, each filling the statement's `ROW`s in order.

    Its other values are bound as they are, the same for every row.

    Returns:
        The cursor.

    Raises:
        ValueError: `statement` holds no `ROW`, or a row has more or fewer values than it has `ROW`s.
    """
    built = statement.fragment()
    wanted = built.params.count(ROW)
    if not wanted:
        msg = "a statement run for many rows needs a ROW where a value differs per row"
        raise ValueError(msg)
    return conn.executemany(built.text, (_filled(built.params, row, wanted) for row in rows))


class _Statement(Composable):
    """A statement built here: a frozen dataclass, each method of which returns a copy with a clause added."""

    __slots__ = ()
    # Set by @dataclass on each subclass; declared so `_but` may read it.
    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]

    def _but(self, **changes: object) -> Self:
        """A copy of this statement with `changes` made to its fields.

        What `dataclasses.replace` does, less its pass over every field and through `__init__`, which cost several
        times what the rest of a clause does: a statement has no `__post_init__`, so a copy of its fields is all it is.

        Returns:
            The copy.

        Raises:
            TypeError: A change names no field.
        """
        if not changes.keys() <= self.__dataclass_fields__.keys():
            msg = f"{type(self).__name__} has no field {', '.join(changes.keys() - self.__dataclass_fields__.keys())}"
            raise TypeError(msg)
        changed = object.__new__(type(self))
        changed.__dict__.update(self.__dict__, **changes)
        return changed


@dataclass(frozen=True, kw_only=True)
class _Filtered(_Statement):
    """What a SELECT, an UPDATE, and a DELETE share: the conditions that pick their rows, ANDed together."""

    conditions: tuple[Fragment, ...] = ()

    def where(self, condition: LiteralString, *args: Arg) -> Self:
        """Add a condition, ANDed with any already there.

        Returns:
            The statement with it.
        """
        return self._but(conditions=(*self.conditions, _fill(condition, args)))

    def where_in(self, column: LiteralString, values: Collection[Value]) -> Self:
        """Add `column IN (...)` of `values`, ANDed with any condition already there.

        Returns:
            The statement with it.
        """
        return self._but(conditions=(*self.conditions, in_(column, values)))

    def where_not_in(self, column: LiteralString, values: Collection[Value]) -> Self:
        """Add `column NOT IN (...)` of `values`, ANDed with any condition already there.

        Returns:
            The statement with it.
        """
        return self._but(conditions=(*self.conditions, not_in(column, values)))


@dataclass(frozen=True, kw_only=True)
class Select(_Filtered):
    """A SELECT, each clause held apart until it is rendered, in SQL's order whatever order it was built in."""

    columns: Fragment
    distinct: bool = False
    #: The common table expressions of its WITH, and whether any is recursive.
    ctes: tuple[Fragment, ...] = ()
    recursive: bool = False
    source: Fragment | None = None
    joins: tuple[Fragment, ...] = ()
    groups: Fragment | None = None
    having_conditions: tuple[Fragment, ...] = ()
    order: Fragment | None = None
    #: Its LIMIT and OFFSET, bound as values.
    row_limit: int | None = None
    row_offset: int | None = None

    def with_(self, cte: LiteralString, *args: Arg, recursive: bool = False) -> Self:
        """Add a common table expression, `name(columns) AS (select)`, to the WITH.

        Returns:
            The statement with it.
        """
        return self._but(ctes=(*self.ctes, _fill(cte, args)), recursive=self.recursive or recursive)

    def unique(self) -> Self:
        """Make it SELECT DISTINCT.

        Returns:
            The statement, distinct.
        """
        return self._but(distinct=True)

    def from_(self, source: LiteralString, *args: Arg) -> Self:
        """Set what it selects from: a table, with an alias if any, or a `({}) AS alias` subquery.

        Returns:
            The statement with it.
        """
        return self._but(source=_fill(source, args))

    def join(self, table_on: LiteralString, *args: Arg) -> Self:
        """Add an inner JOIN of `table alias ON condition`.

        Returns:
            The statement with it.
        """
        return self._but(joins=(*self.joins, _clause("JOIN", _fill(table_on, args))))

    def left_join(self, table_on: LiteralString, *args: Arg) -> Self:
        """Add a LEFT JOIN of `table alias ON condition`.

        Returns:
            The statement with it.
        """
        return self._but(joins=(*self.joins, _clause("LEFT JOIN", _fill(table_on, args))))

    def group_by(self, columns: LiteralString, *args: Arg) -> Self:
        """Set its GROUP BY.

        Returns:
            The statement with it.
        """
        return self._but(groups=_fill(columns, args))

    def having(self, condition: LiteralString, *args: Arg) -> Self:
        """Add a HAVING condition, ANDed with any already there.

        Returns:
            The statement with it.
        """
        return self._but(having_conditions=(*self.having_conditions, _fill(condition, args)))

    def order_by(self, terms: LiteralString, *args: Arg) -> Self:
        """Set its ORDER BY.

        Returns:
            The statement with it.
        """
        return self._but(order=_fill(terms, args))

    def limit(self, rows: int, offset: int | None = None) -> Self:
        """Set its LIMIT, and its OFFSET if given.

        Returns:
            The statement with them.
        """
        return self._but(row_limit=rows, row_offset=offset)

    @override
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
        return _rendered(
            _clause("WITH RECURSIVE" if self.recursive else "WITH", _listed(self.ctes)),
            _clause("SELECT DISTINCT" if self.distinct else "SELECT", self.columns),
            _clause("FROM", self.source),
            *self.joins,
            _clause("WHERE", _anded(self.conditions)),
            _clause("GROUP BY", self.groups),
            _clause("HAVING", _anded(self.having_conditions)),
            _clause("ORDER BY", self.order),
            None if self.row_limit is None else Fragment("LIMIT ?", (self.row_limit,)),
            None if self.row_offset is None else Fragment("OFFSET ?", (self.row_offset,)),
        )


@dataclass(frozen=True, kw_only=True)
class Write(_Statement):
    """What an INSERT, an UPDATE, and a DELETE share: the table they write, and what they return."""

    table: Fragment
    returns: Fragment | None = None

    def returning(self, columns: LiteralString, *args: Arg) -> Self:
        """Add a RETURNING of `columns`.

        Returns:
            The statement with it.
        """
        return self._but(returns=_clause("RETURNING", _fill(columns, args)))


@dataclass(frozen=True, kw_only=True)
class Insert(Write):
    """An INSERT of one row, or of a SELECT's rows, with what it does on a conflict and what it returns."""

    #: Each column and what it is set to: a `?` and its value, or a piece of SQL.
    values: tuple[tuple[str, Fragment], ...] = ()
    #: `OR IGNORE` or `OR REPLACE`, if either.
    resolution: str = ""
    conflict: Fragment | None = None
    #: For an INSERT of a SELECT's rows: the columns they fill, and the SELECT.
    selected: tuple[str, ...] = ()
    source: Fragment | None = None

    def set(self, **values: Arg) -> Self:
        """Set a column per keyword to a value or a piece of SQL.

        Returns:
            The statement with them.
        """
        return self._but(values=(*self.values, *_assignments(values)))

    def of_rows(self, columns: Sequence[LiteralString], rows: Composable) -> Self:
        """Insert the rows `rows`, a SELECT, returns, into `columns`, a value per column in order.

        Returns:
            The statement so.
        """
        return self._but(selected=tuple(map(_identifier, columns)), source=rows.fragment())

    def or_ignore(self) -> Self:
        """Make it INSERT OR IGNORE.

        Returns:
            The statement so.
        """
        return self._but(resolution=" OR IGNORE")

    def or_replace(self) -> Self:
        """Make it INSERT OR REPLACE.

        Returns:
            The statement so.
        """
        return self._but(resolution=" OR REPLACE")

    def on_conflict(self, action: LiteralString, *args: Arg) -> Self:
        """Add an upsert clause: `(columns) DO NOTHING`, or `(columns) DO UPDATE SET ...`.

        Returns:
            The statement with it.
        """
        return self._but(conflict=_clause("ON CONFLICT", _fill(action, args)))

    @override
    def fragment(self) -> Fragment:
        """Render the statement.

        Returns:
            Its SQL and values.

        Raises:
            ValueError: It sets no column, or inserts a SELECT's rows into none.
        """
        into = f"INSERT{self.resolution} INTO {self.table.text}"
        if self.source is not None:
            if not self.selected:
                msg = f"an INSERT into {self.table.text} from a SELECT names no column"
                raise ValueError(msg)
            head = Fragment(f"{into} ({', '.join(self.selected)}) {self.source.text}", self.source.params)
        elif self.values:
            row = _joined(", ", (value for _, value in self.values), empty=None, parenthesize=False)
            head = Fragment(f"{into} ({', '.join(c for c, _ in self.values)}) VALUES ({row.text})", row.params)
        else:
            msg = f"an INSERT into {self.table.text} sets no column"
            raise ValueError(msg)
        return _rendered(head, self.conflict, self.returns)


@dataclass(frozen=True, kw_only=True)
class _Guarded(_Filtered):
    """A write that picks its rows by condition, refused with none unless it says it means every row."""

    #: Set by `everything`, so a write with no condition is meant.
    unconditional: bool = False

    def everything(self) -> Self:
        """Write every row: a write with no condition is refused unless it says so.

        Returns:
            The statement so.
        """
        return self._but(unconditional=True)

    def _where(self, rows: str, verb: str) -> Fragment | None:
        """Its WHERE clause, None for every row; `rows` and `verb` say what it does, for the refusal.

        Returns:
            The clause.

        Raises:
            ValueError: It has no condition and was not told to write every row.
        """
        if not self.conditions and not self.unconditional:
            msg = f"{rows} has no condition; call everything() to {verb} every row"
            raise ValueError(msg)
        return _clause("WHERE", _anded(self.conditions))


@dataclass(frozen=True, kw_only=True)
class Update(Write, _Guarded):
    """An UPDATE: what it sets, of which rows, and what it returns."""

    #: Each assignment, `column = ?` or `column = expression`.
    assignments: tuple[Fragment, ...] = ()

    def set(self, **values: Arg) -> Self:
        """Set a column per keyword to a value or a piece of SQL.

        Returns:
            The statement with them.
        """
        new = tuple(Fragment(f"{c} = {v.text}", v.params) for c, v in _assignments(values))
        return self._but(assignments=(*self.assignments, *new))

    def set_to(self, assignment: LiteralString, *args: Arg) -> Self:
        """Add an assignment written in SQL, such as `failures = failures + 1`.

        Returns:
            The statement with it.
        """
        return self._but(assignments=(*self.assignments, _fill(assignment, args)))

    @override
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
        return _rendered(
            _clause(f"UPDATE {self.table.text} SET", _listed(self.assignments)),
            self._where(f"an update of {self.table.text}'s rows", "update"),
            self.returns,
        )


@dataclass(frozen=True, kw_only=True)
class Delete(Write, _Guarded):
    """A DELETE: of which rows, and what it returns."""

    @override
    def fragment(self) -> Fragment:
        """Render the statement.

        Returns:
            Its SQL and values.

        Raises:
            ValueError: It has no condition and was not told to delete everything.
        """
        return _rendered(
            Fragment(f"DELETE FROM {self.table.text}"),  # noqa: S608  (a name `name` checked)
            self._where(f"a delete of {self.table.text}'s rows", "delete"),
            self.returns,
        )


# A slot, or a quoted string or identifier, whose `?`s and `{}`s are not slots.
_TOKEN = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\?|\{\}")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _fill(text: str, args: Sequence[Arg]) -> Fragment:
    """`text` with its slots filled by `args`, in order: a value bound to each `?`, a piece of SQL in each `{}`.

    Returns:
        The fragment.

    Raises:
        ValueError: `text` has more or fewer slots than `args`.
        TypeError: A `?` is given a piece of SQL, or a `{}` a value.
    """
    pieces, slots = _template(text)
    if len(slots) != len(args):
        more = "more" if len(slots) > len(args) else "fewer"
        msg = f"{text!r} has {more} slots than the {len(args)} values given"
        raise ValueError(msg)
    if not slots:
        return Fragment(text)
    out = [pieces[0]]
    params: list[Bound] = []
    for slot, arg, after in zip(slots, args, pieces[1:], strict=True):
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
        out.append(after)
    return Fragment("".join(out), tuple(params))


# Bounded all the same, in case a caller builds its text, from literals, in a loop.
@functools.lru_cache(maxsize=4096)
def _template(text: str) -> tuple[tuple[str, ...], str]:
    """`text` split at its slots: the text before, between, and after them, and the slots, `?` or `{`, in order.

    Returns:
        The pieces, one more than the slots, and the slots.
    """
    pieces: list[str] = []
    slots: list[str] = []
    at = 0
    for match in _TOKEN.finditer(text):
        slot = match.group()
        if slot in {"?", "{}"}:
            pieces.append(text[at : match.start()])
            slots.append(slot[0])
            at = match.end()
    pieces.append(text[at:])
    return tuple(pieces), "".join(slots)


def _filled(params: Sequence[Bound], row: Sequence[Value], wanted: int) -> list[Value]:
    if len(row) != wanted:
        msg = f"a row of {len(row)} values for a statement with {wanted} ROWs"
        raise ValueError(msg)
    values = iter(row)
    return [next(values) if p is ROW else p for p in params]


def _rendered(*parts: Fragment | None) -> Fragment:
    """The parts a statement has, in order, joined by spaces; a None is a clause it does not have.

    Returns:
        The statement.
    """
    present = [p for p in parts if p is not None]
    return Fragment(" ".join(p.text for p in present), tuple(v for p in present for v in p.params))


def _clause(keyword: str, body: Fragment | None) -> Fragment | None:
    """`keyword` before `body`, as `WHERE ...`; None when there is no body.

    Returns:
        The clause.
    """
    return None if body is None else Fragment(f"{keyword} {body.text}", body.params)


def _anded(conditions: Sequence[Fragment]) -> Fragment | None:
    """The conditions, ANDed; None for none.

    One condition stays as written; several are each parenthesized, so an OR in one cannot swallow the others.

    Returns:
        The condition.
    """
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else all_of(*conditions)


def _listed(pieces: Iterable[Composable]) -> Fragment | None:
    """The pieces, separated by commas; None for none.

    Returns:
        The list.
    """
    rendered = [p.fragment() for p in pieces]
    return _joined(", ", rendered, empty=None, parenthesize=False) if rendered else None


def _joined(
    sep: str,
    pieces: Iterable[Composable],
    *,
    empty: str | None,
    parenthesize: bool = True,
) -> Fragment:
    rendered = [p.fragment() for p in pieces]
    if not rendered:
        if empty is None:
            msg = "nothing to join"
            raise ValueError(msg)
        return Fragment(empty)
    texts = [f"({r.text})" if parenthesize else r.text for r in rendered]
    return Fragment(sep.join(texts), tuple(v for r in rendered for v in r.params))


def _assignments(values: Mapping[str, Arg]) -> tuple[tuple[str, Fragment], ...]:
    return tuple(
        (_identifier(column), value.fragment() if isinstance(value, Composable) else Fragment("?", (value,)))
        for column, value in values.items()
    )


def _identifier(text: str) -> str:
    if not _IDENTIFIER.fullmatch(text):
        msg = f"{text!r} is not a table or column name"
        raise ValueError(msg)
    return text
