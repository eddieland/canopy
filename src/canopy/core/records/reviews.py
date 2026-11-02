"""Reviews of PRs, and the drafts of reviews of PRs the loop does not own.

The operator's requests, each run, what became of its findings, and each draft's versions, notes, and grants
(DESIGN §21, §34).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    DismissalReason,
    FindingAnswer,
    HoldKind,
    PoolKind,
    ReviewDraftAuthor,
    ReviewDraftStatus,
    ReviewRunStatus,
)


@dataclass(frozen=True)
class ReviewRun(Row):
    """A run of a reviewer on one PR at one commit (DESIGN §21): the slot it leased, and how it ended."""

    TABLE: ClassVar[LiteralString] = "review_runs"

    id: int
    tick_id: int
    pr_url: str
    sha: str
    ticket_key: str | None
    # The repository whose pool the slot came from; None in a workspace of one.
    repo: str | None
    slot_path: str | None
    lease_id: str | None
    lease_holder: str | None
    pid: int | None
    agent_pid: int | None
    started_at: str
    ended_at: str | None
    status: ReviewRunStatus
    result_json: str | None
    log_path: str
    session_id: str | None
    cost_usd: float | None
    tokens_input: int | None
    tokens_output: int | None
    tokens_reasoning: int | None
    tokens_cache_read: int | None
    tokens_cache_write: int | None
    base_branch: str | None
    purpose: str
    tokens_peak_context: int | None
    tokens_first_call: int | None
    tokens_first_cache_write: int | None
    definitions_digest: str | None
    pool: PoolKind
    #: The persona it ran in, and the sha256 of its text (DESIGN §31); None for a review from before canopy recorded it.
    persona: str | None
    persona_digest: str | None
    #: A revision's draft, by its id, and the version of it the revision read (DESIGN §34); None for a review.
    revises: int | None
    revises_version: int | None
    #: Its journal number, taken when it ended (DESIGN §35); None while it runs.
    number: int | None
    #: What its first model call read from the cache; None where `tokens_first_call` is, and on a run from before
    #: canopy kept it.
    tokens_first_cache_read: int | None
    #: Its reviewer's latest card, as JSON, when it was recorded, and the tool calls made by then (DESIGN §41); None
    #: with no card.
    card_json: str | None
    card_at: str | None
    card_calls: int | None
    #: The tool calls its reviewer has ended so far.
    tool_calls: int
    #: When each step its card names as working was first seen so, as JSON by title (DESIGN §41); None with none.
    card_working_since: str | None
    #: When the question its card asks was first asked, the letter the operator answered it with, and when (DESIGN
    #: §41); None while it asks none, or waits on the operator.
    card_asked_at: str | None
    card_answer: str | None
    card_answered_at: str | None
    #: The model canopy chose for its reviewer, its ticket's override or `runtime.models`' (DESIGN §13), as it asked
    #: the runtime for it; None when it chose none, and on a run from before canopy recorded it.
    model: str | None
    #: How many times its card went stale while it ran, counted once each as a tool call found it (DESIGN §41), and
    #: whether its card as it stands, or the run with none yet, has been counted stale.
    card_lapses: int
    card_stale: bool


@dataclass(frozen=True)
class ReviewRequest(Row):
    """The operator's request to review a PR the loop does not own (DESIGN §21): open, or how it ended."""

    TABLE: ClassVar[LiteralString] = "review_requests"

    id: int
    pr_url: str
    created_at: str
    channel: str
    ended_at: str | None
    end_reason: str | None
    notes: str | None
    #: The model the operator chose for its reviews, `provider/model[@variant]`; None for the reviewer's own.
    model: str | None


@dataclass(frozen=True)
class ReviewRequestPersona(Row):
    """A persona the operator chose for a review request (DESIGN §31), in place of `[personas] reviewer`."""

    TABLE: ClassVar[LiteralString] = "review_request_personas"

    request_id: int
    #: The persona's name, as `canopy personas` lists it.
    persona: str


@dataclass(frozen=True)
class ReviewHead(Row):
    """A PR's head commit as canopy last saw it, and since when (DESIGN §21): the clock a review's settle time reads."""

    TABLE: ClassVar[LiteralString] = "review_heads"

    pr_url: str
    sha: str
    seen_at: str


@dataclass(frozen=True)
class ReviewDraft(Row):
    """A review's draft (DESIGN §34): a review of a PR the loop does not own, as the comment review it would post."""

    TABLE: ClassVar[LiteralString] = "review_drafts"

    id: int
    review_run_id: int
    pr_url: str
    #: The commit the review read, which the review is posted on.
    sha: str
    status: ReviewDraftStatus
    why: str | None
    created_at: str
    #: A publish's claim: the version it posts, when it began, and through which channel.
    publish_version: int | None
    publish_started_at: str | None
    publish_channel: str | None
    #: The pending review a post reported: its node id, which a later post deletes it by, and its id.
    pending_review: str | None
    pending_review_id: int | None
    published_at: str | None
    published_review_id: int | None
    published_url: str | None
    #: A JSON list, in the version's order, of each published comment's `id` and `url`.
    published_comments: str | None


@dataclass(frozen=True)
class ReviewDraftVersion(Row):
    """One version of a review's draft, exactly what would post: its body and its comments (DESIGN §34)."""

    TABLE: ClassVar[LiteralString] = "review_draft_versions"

    draft_id: int
    version: int
    body: str
    #: A JSON list of comments, each its `path`, `line`, and `text`, and the `finding` it was made from, if any.
    comments: str
    author: ReviewDraftAuthor
    channel: str | None
    #: What made it, in the harness's words.
    change: str
    #: A JSON list of what canopy left out as it made it, and why.
    refused: str
    created_at: str


@dataclass(frozen=True)
class ReviewDraftNote(Row):
    """The operator's note on a review's draft, which asks for a revision while it is newer than the newest version."""

    TABLE: ClassVar[LiteralString] = "review_draft_notes"

    id: int
    draft_id: int
    #: The draft's newest version when the note was written: the note is newer while that is still the newest.
    after_version: int
    body: str
    channel: str
    created_at: str


@dataclass(frozen=True)
class ReviewDraftGrant(Row):
    """Revisions the operator granted a review's draft past `policy.max_revisions_per_draft` (DESIGN §34)."""

    TABLE: ClassVar[LiteralString] = "review_draft_grants"

    id: int
    draft_id: int
    runs: int
    granted_at: str


@dataclass(frozen=True)
class ReviewDismissal(Row):
    """A review's finding the operator dismissed (DESIGN §21)."""

    TABLE: ClassVar[LiteralString] = "review_dismissals"

    review_run_id: int
    finding: int
    dismissed_at: str
    channel: str
    #: Why the operator dismissed it; None for a dismissal from before canopy asked.
    reason: DismissalReason | None


@dataclass(frozen=True)
class ReviewAnswer(Row):
    """What a resumed worker answered of one of a review's findings (DESIGN §21): the worker's words, untrusted."""

    TABLE: ClassVar[LiteralString] = "review_answers"

    run_id: int
    review_run_id: int
    finding: int
    answer: FindingAnswer
    #: Why it declined, or what it says of a fix; None for a fix it said nothing of.
    reason: str | None


@dataclass(frozen=True)
class ReviewHold(Row):
    """A review's finding the harness holds for the operator: it reaches no worker until they send it (DESIGN §21)."""

    TABLE: ClassVar[LiteralString] = "review_holds"

    review_run_id: int
    finding: int
    kind: HoldKind
    #: The earlier review run, and its finding, that a rebuttal answers; None for a `late` hold.
    rebuts_run_id: int | None
    rebuts_finding: int | None
    held_at: str
    #: When the operator sent it to a worker, and through which channel; None while it is held.
    released_at: str | None
    released_channel: str | None


@dataclass(frozen=True)
class ReviewGrant(Row):
    """Review runs the operator granted a PR past its limit (DESIGN §21)."""

    TABLE: ClassVar[LiteralString] = "review_grants"

    id: int
    pr_url: str
    runs: int
    granted_at: str
