"""Ticket plans and feedback plans.

A ticket's plans and the operator's threads on them, and each feedback plan with what it read and covers
(DESIGN §25, §32).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    CheckConclusion,
    MoveKind,
    PlanEffort,
    PlanItem,
    PlanStatus,
    Proposal,
    ReviewItem,
)


@dataclass(frozen=True)
class Plan(Row):
    """A plan a plan run wrote (DESIGN §25): its status, its file's hash as written, and its approval. No text."""

    TABLE: ClassVar[LiteralString] = "plans"

    id: int
    ticket_key: str
    run_id: int
    created_at: str
    status: PlanStatus
    # The file's SHA-256, hex, and its size in bytes, as the planner wrote it.
    sha256: str
    size: int
    # The file's SHA-256 when the operator approved it, their edits included; set with the time and the channel.
    approved_sha256: str | None
    approved_at: str | None
    approved_channel: str | None
    #: Why the planner said its plan needs no review, when the harness approved it so (channel `planner`, DESIGN §25).
    approved_reason: str | None
    #: How much work the plan is for its worker, as its planner judged; None when it gave no estimate.
    effort: PlanEffort | None


@dataclass(frozen=True)
class PlanMetric(Row):
    """How long a ticket plan is, measured once from its file as its planner wrote it (DESIGN §25): a cache."""

    TABLE: ClassVar[LiteralString] = "plan_metrics"

    plan_id: int
    #: The measuring model's version (`plan_metrics.VERSION`) when it was measured; a row of an older one is not read.
    version: int
    measured_at: str
    #: Why it could not be measured: its original's problem, or `changed` when that is not the file written. Its
    #: measurements are then None.
    problem: str | None
    #: Its words outside code blocks and diagrams.
    words: int | None
    #: How many of the plan editor's lines it fills, estimated.
    lines: int | None
    code_blocks: int | None
    tables: int | None
    diagrams: int | None


@dataclass(frozen=True)
class FeedbackPlan(Row):
    """A plan a feedback plan run wrote for a ticket's PRs (DESIGN §32): its status, hashes, and approval. No text."""

    TABLE: ClassVar[LiteralString] = "feedback_plans"

    id: int
    ticket_key: str
    run_id: int
    created_at: str
    status: PlanStatus
    #: The file's SHA-256, hex, and its size in bytes, as the planner wrote it.
    sha256: str
    size: int
    #: The file's SHA-256 when the operator approved it, their edits included; set with the time and the channel.
    approved_sha256: str | None
    approved_at: str | None
    approved_channel: str | None
    #: The `resume` that went ahead on the approval, which it spent: an approval goes ahead once.
    spent_run_id: int | None
    #: Why the planner said its plan needs no review, when the harness approved it so (channel `planner`, DESIGN §25).
    approved_reason: str | None
    #: How much work the plan is for its worker, as its planner judged; None when it gave no estimate.
    effort: PlanEffort | None
    #: The SHA-256 of what changed that an approval of it, stale, was last refused for: approving again approves it.
    stale_shown: str | None
    #: The operator message its approval wrote on the ticket, naming its items; None unless the operator approved it.
    approved_message_id: int | None


@dataclass(frozen=True)
class FeedbackPlanPr(Row):
    """A PR a feedback plan read, and its head then (DESIGN §32, Planning again)."""

    TABLE: ClassVar[LiteralString] = "feedback_plan_prs"

    plan_id: int
    pr_url: str
    head_sha: str | None
    #: Whether it conflicted with its base then, as its host said; None while it had not said, or for a plan recorded
    #: before this was.
    conflicted: bool | None
    #: The merged PR it was stacked on then, its blocker's (DESIGN §10); None when it was on none, or for a plan
    #: recorded before this was.
    merged_blocker: str | None


@dataclass(frozen=True)
class FeedbackPlanCheck(Row):
    """A named check at the head a feedback plan read, and its conclusion then, None while it had none."""

    TABLE: ClassVar[LiteralString] = "feedback_plan_checks"

    plan_id: int
    pr_url: str
    name: str
    conclusion: CheckConclusion | None


@dataclass(frozen=True)
class FeedbackPlanMove(Row):
    """A waiting feedback plan's PR's head or check: its value now, and when canopy saw it take that value (§32)."""

    TABLE: ClassVar[LiteralString] = "feedback_plan_moves"

    plan_id: int
    pr_url: str
    kind: MoveKind
    #: A check's name; "" for the head.
    name: str
    #: The head's sha, or the check's conclusion; "" for none.
    value: str
    #: When the harness first saw it take `value`, since it last held another.
    seen_at: str


@dataclass(frozen=True)
class FeedbackPlanSeen(Row):
    """A review or review comment a feedback plan was given, by id and its body's hash, never its text."""

    TABLE: ClassVar[LiteralString] = "feedback_plan_seen"

    plan_id: int
    pr_url: str
    item: ReviewItem
    item_id: int
    thread_id: str | None
    author: str | None
    #: The SHA-256, hex, of its body as the plan's read observed it: an edit after changes it.
    body_sha256: str
    #: For a reply, given beside the item it answers: that item's id; None for an item.
    answers: int | None


@dataclass(frozen=True)
class FeedbackPlanItem(Row):
    """An item a feedback plan covers, by its id, and what the plan proposes for it (DESIGN §32)."""

    TABLE: ClassVar[LiteralString] = "feedback_plan_items"

    plan_id: int
    #: Its place in the planner's result line, from 1: what an approval names it by.
    number: int
    pr_url: str
    item: PlanItem
    #: A review's or comment's id as the `vcs` source observed it; a failed check's, a conflict's, or a merged
    #: blocker's, below zero, as canopy gave it (`feedback_items.check_id`).
    item_id: int
    proposal: Proposal
    #: The reply the plan would draft, for a review item's change or decline: model text, never an instruction.
    reply: str | None
    #: Whether the operator's approval left it out: its `resume` does not act on it, and the next plan gets it.
    left_out: bool


@dataclass(frozen=True)
class PlanThread(Row):
    """One of the operator's comments on a ticket's plan, anchored by its passage's words (DESIGN §25)."""

    TABLE: ClassVar[LiteralString] = "plan_threads"

    id: int
    ticket_key: str
    # The passage, and up to 32 characters either side of it, each with its whitespace collapsed.
    quote: str
    prefix: str
    suffix: str
    body: str
    created_at: str
    # When the operator resolved it; None while it is open.
    resolved_at: str | None


@dataclass(frozen=True)
class PlanReply(Row):
    """A reply in a plan's comment thread (DESIGN §25)."""

    TABLE: ClassVar[LiteralString] = "plan_replies"

    id: int
    thread_id: int
    body: str
    created_at: str


@dataclass(frozen=True)
class PlanWaiver(Row):
    """A plan an old triage run waived (M55). Kept as history: nothing reads it, so no waiver holds (DESIGN §25)."""

    TABLE: ClassVar[LiteralString] = "plan_waivers"

    id: int
    ticket_key: str
    #: The `needs-plan` run whose result waived it.
    run_id: int
    #: The triage's one-sentence reason, model text written from the ticket.
    reason: str
    at: str
