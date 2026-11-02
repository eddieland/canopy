"""Comments a run would have posted, held for the operator.

Each draft and its versions, and the review replies each run was rendered under (DESIGN §29).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    DraftAuthor,
    DraftKind,
    DraftStance,
    DraftStatus,
    Reaction,
    ReplyMode,
)


@dataclass(frozen=True)
class Draft(Row):
    """A comment a run would have posted, waiting on the operator to send, edit, or drop it (DESIGN §29)."""

    TABLE: ClassVar[LiteralString] = "drafts"

    id: int
    run_id: int
    number: int
    ticket_key: str
    kind: DraftKind
    repo: str | None
    pr_url: str | None
    comment_id: int | None
    issue_url: str | None
    stance: DraftStance | None
    thread_id: str | None
    status: DraftStatus
    why: str | None
    basis: str
    superseded_by: int | None
    created_at: str
    checked_at: str | None
    send_started_at: str | None
    send_version: int | None
    pending_review: str | None
    pending_review_id: int | None
    sent_at: str | None
    sent_comment_id: int | None
    sent_review_id: int | None
    sent_url: str | None
    sent_channel: str | None
    #: The reaction a send added on GitHub, which stays there even when the send's review then failed.
    reacted: Reaction | None
    reacted_at: str | None
    #: The number of the item of its run's feedback plan whose proposed reply it started from, or None (0093).
    plan_item: int | None


@dataclass(frozen=True)
class DraftVersion(Row):
    """One version of a draft's text: the run's own, or one of the operator's edits (DESIGN §29)."""

    TABLE: ClassVar[LiteralString] = "draft_versions"

    draft_id: int
    version: int
    #: The text; empty when the version sends its reaction alone.
    body: str
    author: DraftAuthor
    channel: str | None
    created_at: str
    #: The reaction it stages on the review comment its thread's draft names, if any.
    reaction: Reaction | None


@dataclass(frozen=True)
class RunReplies(Row):
    """The `trust.review_replies` a run was rendered under, and the drafts `_run` refused of it (DESIGN §29)."""

    TABLE: ClassVar[LiteralString] = "run_replies"

    run_id: int
    mode: ReplyMode
    # Whether the run's prompt asked for a ticket's draft.
    ticket_drafts: bool
    # A JSON list of the drafts refused from the run's result, each its number and why.
    refused: str
