"""What every OpenCode session cost (DESIGN §13), read from OpenCode 1.19.3's database, every project's sessions in one.

OpenCode keeps every session it ran, in every directory, in one SQLite database, `opencode/opencode.db` under
`$XDG_DATA_HOME`, or `~/.local/share` when that is unset: canopy's runs, the operator's own sessions, and the
subagents' sessions each ran, which `opencode session list` leaves out, as it does other projects'. So the database is
read, not a command: opened read-only, one query for a page of sessions and one for their replies' models, each naming
the columns it reads, so the tables holding OpenCode's accounts and tokens are never read. Each session row carries its
cost and tokens, summed by OpenCode; each assistant message names its provider, model, variant when not the model's
default, and cost, as `opencode export` prints it (`canopy.runtime.opencode.session_models`), so each model is named as
that module names it.

What a run writes there is not canopy's to trust, since a run can write OpenCode's data directory (SANDBOX.md), so each
row is validated (D026): a session row canopy cannot read is passed over and counted, and a reply's that it cannot is
left out of its session's models. `canopy.runtime.opencode2.sessions` reads OpenCode 2's tables through `read`.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

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
    from collections.abc import Iterable, Sequence

    from canopy.runtime.report import SessionCursor

#: How long a read waits for OpenCode to let go of the database, in seconds.
TIMEOUT_SECONDS = 5.0
#: A page of sessions updated after a cursor, the least recently updated first: the cursor's update, twice, its id, and
#: the page's size. The columns are `_Session`'s, in its order.
SESSIONS_SQL = """
SELECT id, parent_id, directory, time_created, time_updated,
       cost, tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write
FROM session
WHERE time_updated > ? OR (time_updated = ? AND id > ?)
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
    """Read OpenCode's sessions updated after `cursor` from its database.

    Returns:
        At most `limit` sessions, the least recently updated first; `missing` when OpenCode has no database yet;
        `failed`, with why, when it could not be read.
    """
    return read(database(), SESSIONS_SQL, MODELS_SQL, cursor, limit=limit, variant_mark=VARIANT_MARK)


def database() -> Path:
    """Where OpenCode keeps its database: under `$XDG_DATA_HOME`, or `~/.local/share` when that is unset or empty.

    Returns:
        The database's path, whether or not it exists.
    """
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "opencode" / "opencode.db"


def read(
    path: Path,
    sessions_sql: str,
    models_sql: str,
    cursor: SessionCursor | None,
    *,
    limit: int,
    variant_mark: str,
) -> SessionPage:
    """Read a page of sessions from the database at `path`, with queries shaped as `SESSIONS_SQL` and `MODELS_SQL`.

    `variant_mark` goes between a model and the variant it ran at, as the version's export names it.

    Returns:
        The page, as `updated_after` gives it.
    """
    if not path.is_file():
        return SessionPage("missing")
    after = cursor or _FIRST
    try:
        with contextlib.closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=TIMEOUT_SECONDS)) as conn:
            rows = conn.execute(sessions_sql, (after[0], after[0], after[1], limit)).fetchall()
            sessions, skipped = _sessions(rows)
            ids = json.dumps([s.id for s in sessions])
            replies = _replies(conn.execute(models_sql, (ids,)).fetchall()) if sessions else []
    except sqlite3.Error as e:
        return SessionPage("failed", error=f"OpenCode's database could not be read: {str(e)[:200]}")
    if not rows:
        return SessionPage("found", cursor=cursor)
    last_updated, last_id = rows[-1][4], rows[-1][0]
    if not isinstance(last_updated, int) or not isinstance(last_id, str):
        return SessionPage("failed", error="OpenCode's database holds a session canopy cannot read past")
    spent = [_spend(s, [r for r in replies if r.session_id == s.id], variant_mark) for s in sessions]
    return SessionPage("found", tuple(spent), cursor=(last_updated, last_id), skipped=skipped)


# The rows canopy can read, as sessions, and how many it cannot.
def _sessions(rows: Iterable[Sequence[object]]) -> tuple[list[_Session], int]:
    found: list[_Session] = []
    skipped = 0
    for row in rows:
        try:
            session = _Session.model_validate(dict(zip(_Session.model_fields, row, strict=True)))
        except (ValidationError, ValueError):
            skipped += 1
            continue
        if session_id(session.id) is None or (session.parent_id is not None and session_id(session.parent_id) is None):
            skipped += 1
            continue
        found.append(session)
    return found, skipped


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
