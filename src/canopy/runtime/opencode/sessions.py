"""What every OpenCode session cost (DESIGN §13), read from OpenCode 1.19.3's database, every project's sessions in one.

OpenCode keeps every session it ran, in every directory, in one SQLite database, `opencode/opencode.db` under
`$XDG_DATA_HOME`, or `~/.local/share` when that is unset: canopy's runs, the operator's own sessions, and the
subagents' sessions each ran, which `opencode session list` leaves out, as it does other projects'. So the database is
read, not a command: opened read-only, one query for a page of sessions and one for their replies' models, each naming
the columns it reads, so the tables holding OpenCode's accounts and tokens are never read. Each session row carries its
cost and tokens, summed by OpenCode; each assistant message names its provider, model, variant when not the model's
default, and cost, as `opencode export` prints it (`canopy.runtime.opencode.session_models`), so each model is named as
that module names it.

A sandboxed run's OpenCode keeps its data in its role's own directory (DESIGN §24), so its sessions are in a database
of their own, under `canopy_sandbox.data_root()`, which the operator's OpenCode never reads. Each role's is read with
the operator's, and their sessions merged into one page, in the order of their update, under one cursor.

What a run writes there is not canopy's to trust, since a run can write OpenCode's data, its role's in a sandbox and
the operator's outside one (SANDBOX.md), so each row is validated (D026): a session row canopy cannot read is passed
over and counted, and a reply's that it cannot is left out of its session's models. Each database is opened as one
made to harm its reader could be (`opened`). `canopy.runtime.opencode2.sessions` reads
OpenCode 2's tables through `read`.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NamedTuple

import canopy_sandbox
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationError

from canopy.runtime.report import (
    MAX_COST_USD,
    MAX_DIRECTORY,
    MAX_SESSIONS,
    Count,
    SessionPage,
    SessionSpend,
    model_uses,
    session_id,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from canopy.runtime.report import SessionCursor

#: How long a read waits for OpenCode to let go of the database, in seconds.
TIMEOUT_SECONDS = 5.0
#: How long a database may take to answer, in seconds, before canopy stops it: a run can write one that never would.
READ_SECONDS = 60.0
#: How many of a session's messages `sandbox_session` reads: more than any run writes, and few enough to hold.
MAX_MESSAGES = 100_000
#: How many of SQLite's steps go between two looks at the time.
_STEPS = 10_000
#: A page of sessions updated after a cursor, the least recently updated first: the cursor's update, twice, its id, and
#: the page's size. The columns are `_Session`'s, in its order. A row whose update or id is not of its column's type is
#: never read, since the cursor could not pass it: SQLite stores any type in any column, and a run can write the file.
SESSIONS_SQL = """
SELECT id, parent_id, directory, time_created, time_updated,
       cost, tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write
FROM session
WHERE typeof(time_updated) = 'integer' AND typeof(id) = 'text'
  AND (time_updated > ? OR (time_updated = ? AND id > ?))
ORDER BY time_updated, id
LIMIT ?
"""
#: Each model's replies in the sessions a JSON array of ids names, and their cost: each assistant message whose JSON
#: names a provider and a model, by its session, provider, model, and variant.
MODELS_SQL = """
SELECT session_id, json_extract(data, '$.providerID'), json_extract(data, '$.modelID'),
       json_extract(data, '$.variant'), count(*), total(json_extract(data, '$.cost'))
FROM message
WHERE session_id IN (SELECT value FROM json_each(?))
  AND json_valid(data)
  AND json_extract(data, '$.role') = 'assistant'
  AND json_type(data, '$.providerID') = 'text'
  AND json_type(data, '$.modelID') = 'text'
  AND coalesce(json_type(data, '$.cost'), 'integer') IN ('integer', 'real')
GROUP BY 1, 2, 3, 4
"""
#: Between a model and its variant, as `canopy.runtime.opencode.session_models` names a model run at one.
VARIANT_MARK = "@"
#: Where the read starts when no cursor is given: before every session.
_FIRST: SessionCursor = (-1, "")

# Milliseconds since the epoch, as OpenCode stamps a session: up to the year 9999.
_Millis = Annotated[StrictInt, Field(ge=0, le=253_402_300_799_999)]
_Cost = Annotated[StrictFloat | StrictInt, Field(ge=0, le=MAX_COST_USD, allow_inf_nan=False)]


class _Session(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    id: StrictStr
    parent_id: StrictStr | None
    directory: StrictStr
    created: _Millis
    updated: _Millis
    cost: _Cost
    input: Count
    output: Count
    reasoning: Count
    cache_read: Count
    cache_write: Count


class _Replies(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    session_id: StrictStr
    provider: StrictStr
    model: StrictStr
    variant: StrictStr | None
    replies: Annotated[StrictInt, Field(ge=1)]
    cost: _Cost


def updated_after(cursor: SessionCursor | None, *, limit: int = MAX_SESSIONS) -> SessionPage:
    """Read OpenCode's sessions updated after `cursor` from its databases, the operator's and each sandbox role's.

    Returns:
        At most `limit` sessions, the least recently updated first; `missing` when OpenCode has no database yet;
        `failed`, with why, when the operator's could not be read.
    """
    return read(databases(), SESSIONS_SQL, MODELS_SQL, cursor, limit=limit, variant_mark=VARIANT_MARK)


def databases() -> list[Path]:
    """Where OpenCode keeps its sessions: the operator's database, then each sandbox role's.

    Returns:
        The operator's database's path, whether or not it exists, then each role's that does (`sandbox_databases`).
    """
    return [database(), *sandbox_databases()]


def database() -> Path:
    """Where OpenCode keeps its database: under `$XDG_DATA_HOME`, or `~/.local/share` when that is unset or empty.

    Returns:
        The database's path, whether or not it exists.
    """
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "opencode" / "opencode.db"


def sandbox_databases() -> list[Path]:
    """Each sandbox role's OpenCode database, in its data directory under `canopy_sandbox.data_root()`.

    A run writes its role's data directory, so one whose database a link leads out of it is left out.

    Returns:
        Each that exists, in the order of the roles' names.
    """
    try:
        roles = sorted(canopy_sandbox.data_root().iterdir())
    except OSError:
        return []
    found: list[Path] = []
    for role in roles:
        path = role / "opencode" / "opencode.db"
        with contextlib.suppress(OSError, RuntimeError):
            if path.is_file() and path.resolve().is_relative_to(role.resolve()):
                found.append(path)
    return found


def sandbox_session(
    session_id: str,
    session_sql: str,
    messages_sql: str,
) -> tuple[object, list[tuple[object, ...]]] | None:
    """Find session `session_id` in a sandbox role's database, where a sandboxed run's OpenCode keeps it.

    `session_sql` selects the session's version by its id, and `messages_sql` its messages, by its id and at most how
    many, in the order OpenCode wrote them. A database canopy cannot read is passed over, as `read` passes it over.

    Returns:
        The version the session names, and its messages' rows, at most `MAX_MESSAGES`; None when no database holds it.
    """
    for path in sandbox_databases():
        try:
            with opened(path) as conn:
                row = conn.execute(session_sql, (session_id,)).fetchone()
                if row is not None:
                    return row[0], conn.execute(messages_sql, (session_id, MAX_MESSAGES)).fetchall()
        except sqlite3.Error:
            continue
    return None


@contextlib.contextmanager
def opened(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the database at `path` read-only, as one a run may have written to harm its reader.

    SQLite's defensive mode keeps a query from changing it, its schema's functions are not trusted, and a query that
    runs past `READ_SECONDS` is stopped, raising `sqlite3.OperationalError`.

    Yields:
        The connection, closed when the block ends.
    """
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=TIMEOUT_SECONDS)
    try:
        conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)  # noqa: FBT003 # sqlite3's own positional flag
        conn.execute("PRAGMA trusted_schema = OFF")
        deadline = time.monotonic() + READ_SECONDS
        conn.set_progress_handler(lambda: time.monotonic() > deadline, _STEPS)
        yield conn
    finally:
        conn.close()


def read(
    paths: Sequence[Path],
    sessions_sql: str,
    models_sql: str,
    cursor: SessionCursor | None,
    *,
    limit: int,
    variant_mark: str,
) -> SessionPage:
    """Read a page of sessions from the databases at `paths`, with queries shaped as `SESSIONS_SQL` and `MODELS_SQL`.

    The first of `paths` is the operator's database, as `databases` gives them: when it cannot be read, nor can the
    page. Each after it is a sandbox role's, which its runs write: one canopy cannot read is passed over, so that a run
    can keep only its own role's sessions from being read. Each is read from the cursor, and their sessions merged in
    the order of their update, so the page's last is where every one of them is read from next.
    `variant_mark` goes between a model and the variant it ran at, as the version's export names it.

    Returns:
        The page, as `updated_after` gives it.
    """
    after = cursor or _FIRST
    rows: list[_Row] = []
    found = False
    for n, path in enumerate(paths):
        if not path.is_file():
            continue
        try:
            rows.extend(_rows(path, sessions_sql, models_sql, after, limit=limit, variant_mark=variant_mark))
        except _UnreadableError as e:
            if n == 0:
                return SessionPage("failed", error=str(e))
            continue
        found = True
    if not found:
        return SessionPage("missing")
    page = sorted(rows, key=lambda r: (r.updated, r.id))[:limit]
    if not page:
        return SessionPage("found", cursor=cursor)
    spent = tuple(r.spend for r in page if r.spend is not None)
    return SessionPage("found", spent, cursor=(page[-1].updated, page[-1].id), skipped=len(page) - len(spent))


class _Row(NamedTuple):
    """A session row read after the cursor: where it sorts, and what it cost, or None when canopy cannot read it."""

    updated: int
    id: str
    spend: SessionSpend | None


class _UnreadableError(Exception):
    """A database canopy cannot read, or cannot read past."""


# The database's sessions updated after the cursor, at most `limit` of them, in the order of their update.
def _rows(
    path: Path,
    sessions_sql: str,
    models_sql: str,
    after: SessionCursor,
    *,
    limit: int,
    variant_mark: str,
) -> list[_Row]:
    try:
        with opened(path) as conn:
            rows = conn.execute(sessions_sql, (after[0], after[0], after[1], limit)).fetchall()
            sessions = [_session(row) for row in rows]
            ids = json.dumps([s.id for s in sessions if s is not None])
            replies = _replies(conn.execute(models_sql, (ids,)).fetchall()) if any(sessions) else []
    except sqlite3.Error as e:
        raise _UnreadableError(f"OpenCode's database could not be read: {str(e)[:200]}") from None
    found: list[_Row] = []
    for row, session in zip(rows, sessions, strict=True):
        updated, row_id = row[4], row[0]
        if not isinstance(updated, int) or not isinstance(row_id, str):
            raise _UnreadableError("OpenCode's database holds a session canopy cannot read past")
        spend = _spend(session, [r for r in replies if r.session_id == session.id], variant_mark) if session else None
        found.append(_Row(updated, row_id, spend))
    return found


# The row as a session, or None when canopy cannot read it.
def _session(row: Sequence[object]) -> _Session | None:
    try:
        session = _Session.model_validate(dict(zip(_Session.model_fields, row, strict=True)))
    except (ValidationError, ValueError):
        return None
    if session_id(session.id) is None or (session.parent_id is not None and session_id(session.parent_id) is None):
        return None
    return session


# The rows canopy can read, as each model's replies in a session.
def _replies(rows: Iterable[Sequence[object]]) -> list[_Replies]:
    found: list[_Replies] = []
    for row in rows:
        with contextlib.suppress(ValidationError, ValueError):
            found.append(_Replies.model_validate(dict(zip(_Replies.model_fields, row, strict=True))))
    return found


def _spend(session: _Session, replies: Iterable[_Replies], variant_mark: str) -> SessionSpend:
    named = (
        (f"{r.provider}/{r.model}{f'{variant_mark}{r.variant}' if r.variant else ''}", r.replies, float(r.cost))
        for r in replies
    )
    return SessionSpend(
        session_id=session.id,
        parent_id=session.parent_id,
        directory="".join(c for c in session.directory if c.isprintable())[:MAX_DIRECTORY],
        created_ms=session.created,
        updated_ms=session.updated,
        cost_usd=float(session.cost),
        input=session.input,
        output=session.output,
        reasoning=session.reasoning,
        cache_read=session.cache_read,
        cache_write=session.cache_write,
        models=model_uses(named),
    )
