"""Typed journal rows: a frozen dataclass per table, and the queries that build them.

A query that returns a table's whole rows builds them through `fetch_all` or `fetch_one` with that table's row type,
so a misspelled column is a type error where it is read, and a query whose columns no longer match its row type fails
where it runs, not in a caller far from it. `tests/canopy/test_records.py` checks every row type against its table after
every migration: the same columns, in order, each with the type and nullability its column has.

A table's row type is added when a PR first reads that table through it; the rest still read `sqlite3.Row`.
"""

from __future__ import annotations

import sqlite3
import types
import typing
from collections.abc import Callable, Sequence
from dataclasses import Field, dataclass, fields
from typing import Any, ClassVar

# What a column's value is converted with, by its field's type.
_Convert = Callable[[object], object]
# The field types a column's value is checked against as is. A float field also takes an int, as REAL columns may.
_EXACT: dict[object, type] = {int: int, str: str, bytes: bytes}


class Row:
    """A row of one journal table: each subclass is a frozen dataclass whose fields are its columns, in order."""

    TABLE: ClassVar[str]
    # Set by @dataclass on each subclass; declared so `dataclasses.fields` accepts any row type.
    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]


class RowError(Exception):
    """A query's columns, or a value in one, do not fit the row type it was read as."""


@dataclass(frozen=True)
class Decision(Row):
    """A decision a tick recorded (DESIGN §6): the overseer's, a guard's refusal, or an attention item."""

    TABLE: ClassVar[str] = "decisions"

    id: int
    tick_id: int
    ticket_key: str | None
    action: str
    rationale: str
    created_at: str
    repo: str | None
    chore: str | None
    pr: str | None


def fetch_all[R: Row](conn: sqlite3.Connection, row_type: type[R], sql: str, params: Sequence[object] = ()) -> list[R]:
    """Run `sql` and build each row it returns as `row_type`.

    Returns:
        The rows, in the order the query returned them.
    """
    cur = conn.execute(sql, params)
    build = _builder(row_type, cur.description)
    return [build(r) for r in cur.fetchall()]


def fetch_one[R: Row](conn: sqlite3.Connection, row_type: type[R], sql: str, params: Sequence[object] = ()) -> R | None:
    """Run `sql` and build its first row as `row_type`.

    Returns:
        The first row, or None when the query returned none.
    """
    cur = conn.execute(sql, params)
    build = _builder(row_type, cur.description)
    first = cur.fetchone()
    return None if first is None else build(first)


def _builder[R: Row](row_type: type[R], description: Sequence[Sequence[object]]) -> Callable[[Sequence[object]], R]:
    """Check a query's columns against `row_type`'s fields, and return what builds one row of it.

    Returns:
        A function from one row the query returns to the row type.

    Raises:
        RowError: The query returns a column `row_type` has no field for, leaves a field out, or repeats one.
    """
    columns = [str(d[0]) for d in description]
    converters = _converters(row_type)
    if sorted(columns) != sorted(converters):
        missing = sorted(set(converters) - set(columns))
        extra = sorted(set(columns) - set(converters))
        unfit: list[str] = []
        if missing:
            unfit.append(f"missing {', '.join(missing)}")
        if extra:
            unfit.append(f"no field for {', '.join(extra)}")
        # Neither, when the query names a column twice.
        raise RowError(f"query does not fit {row_type.__name__}: {'; '.join(unfit) or 'a column is repeated'}")
    named = [(column, converters[column]) for column in columns]

    def build(row: Sequence[object]) -> R:
        return row_type(**{name: convert(value) for (name, convert), value in zip(named, row, strict=True)})

    return build


def _converters(row_type: type[Row]) -> dict[str, _Convert]:
    """Each field of `row_type`, by name, with what converts its column's value.

    Returns:
        The converters, in field order.
    """
    hints = typing.get_type_hints(row_type)
    return {f.name: _converter(row_type.TABLE, f.name, hints[f.name]) for f in fields(row_type)}


def _converter(table: str, name: str, hint: object) -> _Convert:
    """What converts a column's value to `hint`, refusing a value of another type.

    Returns:
        The converter. A `T | None` field passes None through and converts anything else as `T`.

    Raises:
        RowError: `hint` is not a type a column can hold.
    """
    args = typing.get_args(hint)
    others = [a for a in args if a is not type(None)]
    if typing.get_origin(hint) in {types.UnionType, typing.Union} and type(None) in args and len(others) == 1:
        inner = _converter(table, name, others[0])
        return lambda value: None if value is None else inner(value)
    where = f"{table}.{name}"
    exact = _EXACT.get(hint)
    if exact is not None:
        return lambda value: _checked(where, value, (exact,))
    if hint is float:
        return lambda value: float(typing.cast("float", _checked(where, value, (float, int))))
    if hint is bool:
        return lambda value: _flag(where, value)
    raise RowError(f"{where} is a {hint}; a row's fields are int, float, str, bytes, bool, or one of them or None")


def _checked(where: str, value: object, allowed: tuple[type, ...]) -> object:
    """`value`, if it is one of `allowed`.

    Returns:
        `value`, unchanged.

    Raises:
        RowError: It is of another type, None included.
    """
    if not isinstance(value, allowed):
        expected = " or ".join(t.__name__ for t in allowed)
        raise RowError(f"{where} is {type(value).__name__}, not {expected}")
    return value


def _flag(where: str, value: object) -> bool:
    """A flag column's value as a bool. SQLite has no boolean: a flag is stored as 0 or 1.

    Returns:
        True for 1, False for 0.

    Raises:
        RowError: The value is anything else.
    """
    if isinstance(value, int) and value in {0, 1}:
        return value == 1
    raise RowError(f"{where} holds neither 0 nor 1, as a flag must")
