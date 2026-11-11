"""What every OpenCode 2 session cost (DESIGN §13), read from OpenCode 2.1.4's database, every project's in one.

OpenCode 2 keeps its sessions where OpenCode 1 does (`canopy.runtime.opencode.sessions`), in tables of its own:
`session_v2`, with the same columns of cost and tokens, its title, and when it was archived, and `session_message`,
whose rows of type `assistant` name the model that wrote each reply, `{providerID, id, variant}`, and its cost, as
`opencode session export` prints them (`canopy.runtime.opencode2.session_models`). `opencode session list` lists only
one project's top-level sessions, so the database is read here too, by OpenCode 1's reader, with OpenCode 2's queries.
A session is reopened as OpenCode 1's is, `opencode --session ID` in its directory.
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
WHERE typeof(time_updated) = 'integer' AND typeof(id) = 'text'
  AND (time_updated > ? OR (time_updated = ? AND id > ?))
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
#: The title of each session a JSON array of ids names, and when it was archived, as `opencode1.TITLES_SQL` reads them.
TITLES_SQL = "SELECT id, title, time_archived FROM session_v2 WHERE id IN (SELECT value FROM json_each(?))"
#: The same, of a table with no column for the archive.
UNARCHIVED_SQL = "SELECT id, title, NULL FROM session_v2 WHERE id IN (SELECT value FROM json_each(?))"
#: How OpenCode 2's record is asked for its sessions' titles.
TITLES = opencode1.TitleQueries("session_v2", TITLES_SQL, UNARCHIVED_SQL)
#: Between a model and its variant, as canopy's config spells one (`canopy.core.agent_models`), not as OpenCode 2's own
#: `#`, so the same variant reads the same under either runtime (`canopy.runtime.opencode2.session_models`).
VARIANT_MARK = "@"


def updated_after(cursor: SessionCursor | None, *, limit: int = MAX_SESSIONS, titles: bool = False) -> SessionPage:
    """Read OpenCode 2's sessions updated after `cursor` from its databases, the operator's and each sandbox role's.

    With `titles`, each session's title and archive are read too.

    Returns:
        At most `limit` sessions, the least recently updated first; `missing` when OpenCode has no database yet;
        `failed`, with why, when the operator's could not be read.
    """
    return opencode1.read(
        opencode1.databases(),
        SESSIONS_SQL,
        MODELS_SQL,
        cursor,
        limit=limit,
        variant_mark=VARIANT_MARK,
        titles=TITLES if titles else None,
    )


def reopen(session_id: str, directory: str) -> str:
    """The command that reopens session `session_id` in OpenCode 2, in the directory it ran in, as OpenCode 1's does.

    Returns:
        One shell line, each word quoted as the shell needs it.
    """
    return opencode1.reopen(session_id, directory)
