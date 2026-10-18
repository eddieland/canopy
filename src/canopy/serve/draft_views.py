"""A run's draft as the API sends it (DESIGN §29): a PR's page and a ticket's both show drafts, through this one view.

A draft is a worker's text, written from coworkers' comments, until the operator sends it: sent as the journal holds
it, for the UI to show as plain text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from canopy.core import db, drafts, drafts_manage, records
from canopy.core.vocab import DraftKind
from canopy.serve.schema import Draft, DraftKindName, DraftStanceName, DraftStatusName

if TYPE_CHECKING:
    import sqlite3

# How many of a ticket's own drafts its page carries, the newest runs' first.
TICKET_DRAFTS = 10


def draft(conn: sqlite3.Connection, found: records.Draft) -> Draft:
    """A draft as the API sends it: its text as it stands, named by its hash.

    Returns:
        The draft.
    """
    text = drafts.text_of(conn, found.id)
    supersedes_edited = conn.execute(
        "SELECT 1 FROM drafts d JOIN draft_versions v ON v.draft_id = d.id WHERE d.superseded_by = ? AND v.version > 1",
        (found.id,),
    ).fetchone()
    return Draft(
        run=found.run_id,
        number=found.number,
        ticket_key=found.ticket_key,
        kind=cast("DraftKindName", found.kind.value),
        status=cast("DraftStatusName", found.status.value),
        stance=cast("DraftStanceName", found.stance.value) if found.stance is not None else None,
        comment_id=found.comment_id,
        thread_id=found.thread_id,
        issue_url=found.issue_url,
        why=found.why,
        text=text.body,
        hash=drafts_manage.hash_of(text.body),
        edited=text.version > 1,
        supersedes_edited=supersedes_edited is not None,
        sent_url=found.sent_url,
        created_at=db.parse_time(found.created_at),
    )


def of_ticket(conn: sqlite3.Connection, key: str) -> list[Draft]:
    """The ticket's own drafts, the comments its runs would have posted on it, whatever became of them.

    Returns:
        At most `TICKET_DRAFTS`, the newest run's first.
    """
    found = records.fetch_all(
        conn,
        records.Draft,
        "SELECT * FROM drafts WHERE ticket_key = ? AND kind = ? ORDER BY run_id DESC, number LIMIT ?",
        (key, DraftKind.TICKET, TICKET_DRAFTS),
    )
    return [draft(conn, d) for d in found]
