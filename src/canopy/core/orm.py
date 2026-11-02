"""Reading and writing journal rows through their row types: the queries, the writes, and the reader.

A query of a table's whole rows starts from its row type, which names the table and each of its columns, and ends by
reading them as that type:

    running = records.select(records.Run).where("status = ?", RunStatus.RUNNING).order_by("id").all(conn)
    run = records.select(records.Run, "r").join("tickets t ON t.key = r.ticket_key").where("r.id = ?", 7).one(conn)

So a misspelled column is a type error where it is read, and no query can read one table's rows as another's. A query
built elsewhere, such as a constant that callers finish, reads its rows through `fetch_all` or `fetch_one`, which check
its columns against the row type where it runs.

A column holding one of `vocab`'s closed vocabularies is a field of that `StrEnum`, so the row carries the member and a
value the vocabulary does not hold is refused where the row is read, not where something later branches on it.

A query that reads some of a table's columns, computes some, or joins in another's reads them as a `View`: a frozen
dataclass defined beside it, a field per column it returns, read through `fetch_all` or `fetch_one` and converted and
checked as a row type's are.

A write starts from the row type too, and is held to it where the statement is built, before anything runs:

    records.insert(records.Tick, started_at=now, status=TickStatus.RUNNING, dry_run=True).run(conn)
    [run] = records.update(records.Run).set(status=RunStatus.OK).where("id = ?", run_id).returned(conn)

Each column it names must be one of the row type's fields, and each value one that field would read back, so a
misspelled column or a word outside a vocabulary is refused in canopy's code, not left for the column's CHECK, if it
has one, or for a later read. `returned` reads back the rows a write made, changed, or removed, as the row type.

The row types themselves are `records`'s, which re-exports this module's names, so a caller names a table and its
query from one module, as above.
"""

from __future__ import annotations

import functools
import sqlite3
import types
import typing
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import Field, asdict, dataclass, fields
from enum import StrEnum
from typing import Any, ClassVar, LiteralString, Self, override

from canopy.core import sql


class Record:
    """What a query's rows are read as: a frozen dataclass whose fields are the columns the query returns."""

    # Set by @dataclass on each subclass; declared so `dataclasses.fields` accepts any record type.
    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]


class Row(Record):
    """A row of one journal table: each subclass is a frozen dataclass whose fields are its columns, in order."""

    #: The table, spelled in canopy's code, so `select` may name it.
    TABLE: ClassVar[LiteralString]


class View(Record):
    """What a query that is not of one table's whole rows returns: each subclass's fields are its columns, by name.

    Defined beside the query that reads it, and read through `fetch_all` or `fetch_one`, as a row type is.
    """


class RowError(Exception):
    """A query's columns, or a value in one, do not fit the row type it was read as or written through."""


def select[R: Row](row_type: type[R], alias: LiteralString | None = None) -> Query[R]:
    """Start a query of `row_type`'s table, selecting each of its columns, by the table's name or by `alias`.

    Its columns are named in full, as `runs.id` or `r.id`, so a table it joins in cannot shadow one, and a condition
    may name either table's.

    Returns:
        The query, to add conditions to and end with `all` or `one`.
    """
    table = sql.name(row_type.TABLE)
    return Query(
        row_type=row_type,
        columns=_selected(row_type, alias or row_type.TABLE),
        source=table if alias is None else sql.frag("{} {}", table, sql.name(alias)),
    )


def insert[R: Row](row_type: type[R], **values: sql.Arg) -> Insert[R]:
    """Start an INSERT of one row into `row_type`'s table: a column per keyword, each a value or a piece of SQL.

    Each keyword must name one of its fields, and each value must be one that field would read back: a vocabulary's
    member for a vocabulary field, 0 or 1 for a flag, None only for a `| None` field. A piece of SQL, or a `ROW`, is
    left for SQLite to judge.

    Returns:
        The statement, to `run`, or to run with `returned` for the row it wrote.
    """
    return Insert(row_type=row_type, table=sql.name(row_type.TABLE)).set(**values)


def insert_rows[R: Row](row_type: type[R], columns: Sequence[LiteralString]) -> Insert[R]:
    """Start an INSERT into `row_type`'s table of a `ROW` per column, for `Insert.many` to run once per row.

    Returns:
        The statement.
    """
    return Insert(row_type=row_type, table=sql.name(row_type.TABLE)).set(**dict.fromkeys(columns, sql.ROW))


def insert_from[R: Row](row_type: type[R], columns: Sequence[LiteralString], rows: sql.Composable) -> Insert[R]:
    """Start an INSERT into `row_type`'s `columns` of the rows a SELECT returns, a value per column in order.

    Returns:
        The statement.
    """
    return Insert(row_type=row_type, table=sql.name(row_type.TABLE)).of_rows(columns, rows)


def update[R: Row](row_type: type[R]) -> Update[R]:
    """Start an UPDATE of `row_type`'s table, whose `set` holds each column and value to its fields, as `insert` does.

    Returns:
        The statement.
    """
    return Update(row_type=row_type, table=sql.name(row_type.TABLE))


def delete[R: Row](row_type: type[R]) -> Delete[R]:
    """Start a DELETE from `row_type`'s table.

    Returns:
        The statement.
    """
    return Delete(row_type=row_type, table=sql.name(row_type.TABLE))


def fetch_all[R: Record](conn: sqlite3.Connection, record_type: type[R], query: sql.Composable) -> list[R]:
    """Run `query`, a statement built with `sql`, and build each row it returns as `record_type`.

    Returns:
        The rows, in the order the query returned them.
    """
    cur = _cursor(conn, query)
    reading = _reading(record_type, _names(cur))
    return [_made(record_type, reading.names, reading.values(row)) for row in cur.fetchall()]


def fetch_one[R: Record](conn: sqlite3.Connection, record_type: type[R], query: sql.Composable) -> R | None:
    """Run `query`, a statement built with `sql`, and build its first row as `record_type`.

    Returns:
        The first row, or None when the query returned none.
    """
    cur = _cursor(conn, query)
    reading = _reading(record_type, _names(cur))
    first = cur.fetchone()
    return None if first is None else _made(record_type, reading.names, reading.values(first))


def columns(row: sqlite3.Row | Record) -> sqlite3.Row | dict[str, Any]:
    """A row of a table with a row type or one still read as `sqlite3.Row`, either way read by column name.

    For a helper that reads the same columns, such as a run's cost, from rows of several tables, while some of those
    tables have no row type yet.

    Returns:
        A typed row's fields by name, or the `sqlite3.Row` itself.
    """
    return asdict(row) if isinstance(row, Record) else row


@dataclass(frozen=True, kw_only=True)
class Query[R: Row](sql.Select):
    """A SELECT of one table's whole rows, read as its row type: `select` starts one, and `all` or `one` runs it.

    It is a `sql.Select`, built clause by clause as any is, and goes in a `{}` as itself.
    """

    #: The row type it reads, which names its table and columns.
    row_type: type[R]

    def all(self, conn: sqlite3.Connection) -> list[R]:
        """Run it on `conn`.

        Returns:
            Each row it matched, in the order it returned them.
        """
        return fetch_all(conn, self.row_type, self)

    def one(self, conn: sqlite3.Connection) -> R | None:
        """Run it on `conn` for its first row.

        Returns:
            The first row it matched, or None when it matched none.
        """
        return fetch_one(conn, self.row_type, self)


@dataclass(frozen=True, kw_only=True)
class _Write[R: Row](sql.Write):
    """What a write through a row type adds to its `sql` statement: the row type, and running it."""

    #: The row type of the table it writes, which holds its columns and values and reads back its rows.
    row_type: type[R]

    def run(self, conn: sqlite3.Connection) -> sqlite3.Cursor:
        """Run it on `conn`.

        Returns:
            The cursor, for its row count, its last row's id, or a RETURNING's rows.
        """
        return sql.execute(conn, self)

    def returned(self, conn: sqlite3.Connection) -> list[R]:
        """Run it on `conn`, returning each row it wrote: inserted, as it is now after an update, or as it was deleted.

        Returns:
            The rows, as the row type: none for a row an INSERT ignored on a conflict.

        Raises:
            ValueError: It already returns columns of its own.
        """
        if self.returns is not None:
            msg = f"this write to {self.row_type.TABLE} already returns columns of its own"
            raise ValueError(msg)
        return fetch_all(conn, self.row_type, self.returning("{}", _selected(self.row_type, self.row_type.TABLE)))


@dataclass(frozen=True, kw_only=True)
class Insert[R: Row](_Write[R], sql.Insert):
    """An INSERT into one table, its columns and values held to its row type: `insert` and its kin start one."""

    @override
    def set(self, **values: sql.Arg) -> Self:
        """Set a column per keyword to a value or a piece of SQL, each held to its field.

        Returns:
            The statement with them.
        """
        _check_values(self.row_type, values)
        return super().set(**values)

    @override
    def of_rows(self, columns: Sequence[LiteralString], rows: sql.Composable) -> Self:
        """Insert the rows `rows`, a SELECT, returns, into `columns`, each a field.

        Returns:
            The statement so.
        """
        _check_columns(self.row_type, columns)
        return super().of_rows(columns, rows)

    def many(self, conn: sqlite3.Connection, rows: Iterable[Sequence[sql.Value]]) -> sqlite3.Cursor:
        """Run it on `conn` once for each of `rows`, each a value per `ROW` column, held to its field as `insert` is.

        Returns:
            The cursor.

        Raises:
            ValueError: A `ROW` is somewhere other than a column's value, so a row's values cannot be checked.
        """
        per_row = [column for column, value in self.values if value == _PER_ROW]
        if self.fragment().params.count(sql.ROW) != len(per_row):
            msg = f"an INSERT into {self.row_type.TABLE} binds a ROW that is not a column's value"
            raise ValueError(msg)
        return sql.execute_many(conn, self, (self._checked(per_row, row) for row in rows))

    def _checked(self, per_row: Sequence[str], row: Sequence[sql.Value]) -> Sequence[sql.Value]:
        if len(row) == len(per_row):
            _check_values(self.row_type, dict(zip(per_row, row, strict=True)))
        # A row of the wrong length goes on for `sql.execute_many` to refuse.
        return row


@dataclass(frozen=True, kw_only=True)
class Update[R: Row](_Write[R], sql.Update):
    """An UPDATE of one table, each column it sets held to its row type, as `insert`'s are: `update` starts one."""

    @override
    def set(self, **values: sql.Arg) -> Self:
        """Set a column per keyword to a value or a piece of SQL, each held to its field.

        Returns:
            The statement with them.
        """
        _check_values(self.row_type, values)
        return super().set(**values)


@dataclass(frozen=True, kw_only=True)
class Delete[R: Row](_Write[R], sql.Delete):
    """A DELETE from one table: `delete` starts one."""


#: What makes a value of a type its field accepts the field's own, refusing one it cannot be.
type _Convert = Callable[[object], object]
#: A column's value as `insert_rows` binds it, from each row `Insert.many` runs for.
_PER_ROW = sql.frag("?", sql.ROW)


@dataclass(frozen=True)
class _Field:
    """How a record's field reads its column's value, and holds a value written to it."""

    #: `table.column` for a row type's field, `View.field` for a view's: what a refusal names.
    where: str
    #: The types its value may have, besides None for a `| None` field: a flag's is int, a vocabulary's str.
    types: tuple[type, ...]
    optional: bool
    #: What makes a value of one of `types` the field's own: a flag's bool, a vocabulary's member, a REAL's float.
    #: None to keep it as it is.
    convert: _Convert | None

    @functools.cached_property
    def exact(self) -> frozenset[type]:
        """The types a value may be exactly, NoneType among them for a `| None` field: a whole row's check at once.

        Returns:
            The types.
        """
        return frozenset((*self.types, type(None)) if self.optional else self.types)

    def read(self, value: object) -> object:
        """`value` as the field holds it.

        Returns:
            The value, converted.

        Raises:
            RowError: It is not of the field's type, or is a flag's other than 0 or 1, or a word outside a vocabulary.
        """
        if value is None and self.optional:
            return None
        if not isinstance(value, self.types):
            expected = " or ".join(t.__name__ for t in self.types)
            raise RowError(f"{self.where} is {type(value).__name__}, not {expected}")
        return value if self.convert is None else self.convert(value)


@dataclass(frozen=True)
class _Reading:
    """How one query's rows are read as one record type: a field per column, in the query's order."""

    #: The columns, by name.
    names: tuple[str, ...]
    fields: tuple[_Field, ...]
    #: Each column's `_Field.exact`.
    exact: tuple[frozenset[type], ...]
    #: Each column whose field converts its value, by position, with what converts it.
    converted: tuple[tuple[int, _Convert], ...]

    def values(self, row: Sequence[object]) -> list[object]:
        """A row's values as its record's fields hold them, in the query's order.

        Returns:
            The values.

        Raises:
            RowError: A value does not fit its field.
        """
        # Most rows hold each column's own type exactly: checked at once, they convert only their flags, vocabularies,
        # and REALs. Any other row is read value by value, which refuses one that does not fit, and names it.
        if not all(map(frozenset.__contains__, self.exact, map(type, row))):
            return [field.read(value) for field, value in zip(self.fields, row, strict=True)]
        values = list(row)
        for at, convert in self.converted:
            if values[at] is not None:
                values[at] = convert(values[at])
        return values


def _check_columns(row_type: type[Row], columns: Iterable[str]) -> None:
    """Refuse a column `row_type` has no field for.

    Raises:
        RowError: One of `columns` is not a field of `row_type`.
    """
    unknown = [c for c in columns if c not in _fields(row_type)]
    if unknown:
        raise RowError(f"{row_type.TABLE} has no column {', '.join(unknown)}")


def _check_values(row_type: type[Row], values: Mapping[str, sql.Arg]) -> None:
    """Refuse a column `row_type` has no field for, or a value its field would not read back.

    A piece of SQL, or a `ROW`, is not a value here: SQLite judges what it comes to.

    Raises:
        RowError: A column is not a field of `row_type`, or a value does not fit its field.
    """
    _check_columns(row_type, values)
    fields_of = _fields(row_type)
    for column, value in values.items():
        if not isinstance(value, sql.Composable | sql.PerRow):
            fields_of[column].read(value)


# Cached: a row type's columns never change, and a query of them is started on every read.
@functools.cache
def _selected(row_type: type[Row], qualifier: LiteralString) -> sql.Fragment:
    """Each of `row_type`'s columns, as `qualifier.column`, in field order.

    Returns:
        The column list, for a SELECT.
    """
    # A field's name is spelled in canopy's code, as the row type's is; `sql.name` still checks it is an identifier.
    named = [
        sql.frag("{}.{}", sql.name(qualifier), sql.name(typing.cast("LiteralString", f.name))) for f in fields(row_type)
    ]
    return functools.reduce(lambda listed, column: sql.frag("{}, {}", listed, column), named)


def _cursor(conn: sqlite3.Connection, query: sql.Composable) -> sqlite3.Cursor:
    """Run `query`, for its rows to be read as plain tuples.

    Returns:
        The cursor.
    """
    cur = sql.execute(conn, query)
    # A record reads its values by position: a `sqlite3.Row` per row would be made only to be taken apart again.
    cur.row_factory = None
    return cur


def _names(cur: sqlite3.Cursor) -> tuple[str, ...]:
    """The columns a cursor's query returns, by name.

    Returns:
        The names, in order.
    """
    return tuple([d[0] for d in cur.description])


# Cached: canopy's queries are written in its code, so few shapes recur, and a read of one row would plan it each time.
@functools.lru_cache(maxsize=1024)
def _reading(record_type: type[Record], names: tuple[str, ...]) -> _Reading:
    """Check a query's columns, `names`, against `record_type`'s fields, and plan how to read its rows.

    Returns:
        The plan.

    Raises:
        RowError: The query returns a column `record_type` has no field for, leaves a field out, or repeats one.
    """
    fields_of = _fields(record_type)
    if sorted(names) != sorted(fields_of):
        missing = sorted(set(fields_of) - set(names))
        extra = sorted(set(names) - set(fields_of))
        unfit: list[str] = []
        if missing:
            unfit.append(f"missing {', '.join(missing)}")
        if extra:
            unfit.append(f"no field for {', '.join(extra)}")
        # Neither, when the query names a column twice.
        raise RowError(f"query does not fit {record_type.__name__}: {'; '.join(unfit) or 'a column is repeated'}")
    read = tuple(fields_of[name] for name in names)
    return _Reading(
        names=names,
        fields=read,
        exact=tuple(field.exact for field in read),
        converted=tuple((at, field.convert) for at, field in enumerate(read) if field.convert is not None),
    )


def _made[R: Record](record_type: type[R], names: Iterable[str], values: Iterable[object]) -> R:
    """A record of `record_type` holding `values`, each already read by its field, under `names`.

    Made as `pickle` makes an object, without its `__init__`: a frozen dataclass's sets each field through
    `object.__setattr__`, which for a wide row costs more than reading it from SQLite. `_fields` refuses a record
    type that would need its `__init__` run.

    Returns:
        The record.
    """
    record = object.__new__(record_type)
    record.__dict__.update(zip(names, values, strict=True))
    return record


# Cached: resolving a record type's hints costs about a millisecond, and every fetch of a row would pay it again.
@functools.cache
def _fields(record_type: type[Record]) -> Mapping[str, _Field]:
    """Each field of `record_type`, by name, with how it reads its column's value.

    Returns:
        The fields, in order.

    Raises:
        RowError: `record_type` has a `__post_init__` or `__slots__`, which `_made` would not honor.
    """
    if hasattr(record_type, "__post_init__") or "__slots__" in vars(record_type):
        raise RowError(f"{record_type.__name__} is read without its __init__, so it may have no __post_init__ or slots")
    hints = typing.get_type_hints(record_type)
    # A row's errors name its table's column; a view's, its own field.
    owner = record_type.TABLE if issubclass(record_type, Row) else record_type.__name__
    return {f.name: _field(f"{owner}.{f.name}", hints[f.name]) for f in fields(record_type)}


def _field(where: str, hint: object) -> _Field:
    """How a field typed `hint` reads its column's value.

    Returns:
        The field.

    Raises:
        RowError: `hint` is not a type a column can hold.
    """
    args = typing.get_args(hint)
    others = [a for a in args if a is not type(None)]
    optional = typing.get_origin(hint) in {types.UnionType, typing.Union} and type(None) in args and len(others) == 1
    inner = others[0] if optional else hint
    if inner in {int, str, bytes}:
        return _Field(where, (typing.cast("type", inner),), optional, None)
    if inner is float:
        return _Field(where, (float, int), optional, _real)
    if inner is bool:
        return _Field(where, (int,), optional, functools.partial(_flag, where))
    if isinstance(inner, type) and issubclass(inner, StrEnum):
        return _Field(where, (str,), optional, functools.partial(_member, where, inner))
    raise RowError(
        f"{where} is a {hint}; a row's fields are int, float, str, bytes, bool, a StrEnum, or one of them or None",
    )


def _real(value: object) -> float:
    """A REAL column's value as a float: SQLite gives back an integer for a whole one a query computes.

    Returns:
        The value, as a float.
    """
    return float(typing.cast("float", value))


def _flag(where: str, value: object) -> bool:
    """A flag column's value as a bool. SQLite has no boolean: a flag is stored as 0 or 1.

    Returns:
        True for 1, False for 0.

    Raises:
        RowError: The value is anything else.
    """
    if value in {0, 1}:
        return value == 1
    raise RowError(f"{where} holds neither 0 nor 1, as a flag must")


def _member(where: str, vocabulary: type[StrEnum], value: object) -> StrEnum:
    """A vocabulary column's value as the member of `vocabulary` it names.

    Returns:
        The member whose value is `value`.

    Raises:
        RowError: The value is not one `vocabulary` holds.
    """
    try:
        return vocabulary(value)
    except ValueError:
        raise RowError(f"{where} holds {value!r}, which is not a {vocabulary.__name__}") from None
