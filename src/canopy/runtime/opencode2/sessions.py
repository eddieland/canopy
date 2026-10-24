"""What every OpenCode 2 session cost (DESIGN §13), read from OpenCode 2.1.4's database, every project's in one.

OpenCode 2 keeps its sessions where OpenCode 1 does (`canopy.runtime.opencode.sessions`), in tables of its own:
`session_v2`, with the same columns of cost and tokens, and `session_message`, whose rows of type `assistant` name the
model that wrote each reply, `{providerID, id, variant}`, and its cost, as `opencode session export` prints them
(`canopy.runtime.opencode2.session_models`). `opencode session list` lists only one project's top-level sessions, so
the database is read here too, by OpenCode 1's reader, with OpenCode 2's queries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.opencode import sessions as opencode1
from canopy.runtime.report import MAX_SESSIONS

if TYPE_CHECKING:
    from canopy.runtime.report import SessionCursor, SessionPage

#: A page of sessions updated after a cursor, as OpenCode 1's reader takes it (`opencode1.SESSIONS_SQL`).
SESSIONS_SQL = """
SELECT id, parent_id, directory, time_created, time_updated,
       cost, tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write
FROM session_v2
WHERE time_updated > ? OR (time_updated = ? AND id > ?)
ORDER BY time_updated, id
LIMIT ?
"""
#: Each model's replies in the sessions a JSON array of ids names, and their cost, as `opencode1.MODELS_SQL` reads them.
MODELS_SQL = """
SELECT session_id, json_extract(data, '$.model.providerID'), json_extract(data, '$.model.id'),
       json_extract(data, '$.model.variant'), count(*), total(json_extract(data, '$.cost'))
FROM session_message
WHERE session_id IN (SELECT value FROM json_each(?))
  AND type = 'assistant'
  AND json_valid(data)
  AND json_type(data, '$.model.providerID') = 'text'
  AND json_type(data, '$.model.id') = 'text'
  AND coalesce(json_type(data, '$.cost'), 'integer') IN ('integer', 'real')
GROUP BY 1, 2, 3, 4
"""
#: Between a model and its variant, as `canopy.runtime.opencode2.session_models` names a model run at one.
VARIANT_MARK = "#"


def updated_after(cursor: SessionCursor | None, *, limit: int = MAX_SESSIONS) -> SessionPage:
    """Read OpenCode 2's sessions updated after `cursor` from its database.

    Returns:
        At most `limit` sessions, the least recently updated first; `missing` when OpenCode has no database yet;
        `failed`, with why, when it could not be read.
    """
    return opencode1.read(
        opencode1.database(),
        SESSIONS_SQL,
        MODELS_SQL,
        cursor,
        limit=limit,
        variant_mark=VARIANT_MARK,
    )
