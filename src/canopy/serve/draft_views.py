"""A run's draft as the API sends it (DESIGN §29): a PR's page and a ticket's both show drafts, through this one view.

A draft is a worker's text, written from coworkers' comments, until the operator sends it: sent as the journal holds
it, for the UI to show as plain text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from canopy.core import db, records, sql
from canopy.core.vocab import DraftKind
from canopy.runs import drafts, drafts_manage
from canopy.serve.schema.draft import (
    Draft,
    DraftFromPlan,
    DraftKindName,
    DraftStanceName,
    DraftStatusName,
    ProposalName,
    ReactionName,
)

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
    supersedes_edited = sql.execute(
        conn,
        sql.select("1")
        .from_("drafts d")
        .join("draft_versions v ON v.draft_id = d.id")
        .where("d.superseded_by = ?", found.id)
        .where("v.version > 1"),
    ).fetchone()
    planned = drafts.from_plan(conn, found)
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
        reaction=cast("ReactionName", text.reaction.value) if text.reaction is not None else None,
        hash=drafts_manage.hash_of_version(text),
        edited=text.version > 1,
        supersedes_edited=supersedes_edited is not None,
        sent_url=found.sent_url,
        reacted=cast("ReactionName", found.reacted.value) if found.reacted is not None else None,
        created_at=db.parse_time(found.created_at),
        from_plan=None
        if planned is None
        else DraftFromPlan(
            number=planned.number,
            item_id=planned.item_id,
            proposal=cast("ProposalName", planned.proposal.value),
            reply=planned.reply,
            left_out=planned.left_out,
            departs=planned.departs,
        ),
    )


def of_ticket(conn: sqlite3.Connection, key: str) -> list[Draft]:
    """The ticket's own drafts, the comments its runs would have posted on it, whatever became of them.

    Returns:
        At most `TICKET_DRAFTS`, the newest run's first.
    """
    found = records.fetch_all(
        conn,
        records.Draft,
        sql.select("*")
        .from_("drafts")
        .where("ticket_key = ?", key)
        .where("kind = ?", DraftKind.TICKET)
        .order_by("run_id DESC, number")
        .limit(TICKET_DRAFTS),
    )
    return [draft(conn, d) for d in found]
