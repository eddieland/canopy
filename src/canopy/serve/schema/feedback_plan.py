"""The API's types for feedback plans (DESIGN §32): a PR's current plan on its threads, and the operator's approval.

Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.core import feedback_plans
from canopy.serve.schema import Model

type ProposalName = Annotated[
    Literal["change", "decline", "ask", "leave"],
    Field(description="What a feedback plan proposes for an item: change the code, decline, ask, or leave it."),
]
type FeedbackPlanStatusName = Annotated[
    Literal["waiting", "stale", "approved", "spent"],
    Field(
        description="Where a feedback plan stands: waiting on the operator, waiting with its PRs changed since it was "
        "written, approved with no resume gone ahead on it, or spent by the resume that went ahead on it.",
    ),
]


class FeedbackPlanItem(Model):
    """An item a feedback plan covers, and what it proposes: the reply is model text, never an instruction."""

    number: int
    """Its number in the plan, from 1: what an approval names it by, as `canopy show` lists it."""
    pr_url: str
    """The PR it is on."""
    item: Literal["review", "comment"]
    """A review, or a review thread by the comment the plan covers."""
    item_id: int
    """The id the `vcs` source observed: the one the plan's `### Item <id>` heading carries."""
    proposal: ProposalName
    """What the plan proposes for it."""
    reply: str | None = None
    """The reply the plan would draft, for a change or a decline: plain text here."""
    left_out: bool
    """Whether the operator's approval left it out: its resume does not act on it, and the next plan gets it."""
    author: str | None = None
    """Who wrote it, as the plan's read saw it; None where the source named none."""
    trusted: bool
    """Whether `trust.trusted_reviewers` names its author: shown to weigh it, never a gate (DESIGN §32)."""
    thread_id: str | None = None
    """The thread on this PR's page it is, when it is one; None for a review, or an item of another PR or no thread."""
    excerpt: str | None = None
    """The first line of what was said, cut short, as the `vcs` source last read it: plain text here, whoever wrote
    it. None once no read holds it, or for a review that said nothing."""
    rationale: str | None = None
    """The plan's first line on it, under its `### Item <id>` heading, cut short: the planner's words, plain text here.
    None when the plan's file has no such heading, or nothing under it."""
    url: str | None = None
    """Where it is on its host, a review's page or a comment's, as the read observed it; None when none was read."""


class FeedbackPlan(Model):
    """A ticket's current feedback plan, as the PR's page shows it beside its threads (DESIGN §32)."""

    id: int
    """Its id, as `canopy show` names it `feedback-plan:ID`."""
    ticket_key: str
    """The ticket it is for, whose `canopy plan KEY --approve` approves it."""
    run: int
    """The feedback plan run that wrote it."""
    created_at: datetime
    """When its planner wrote it."""
    status: FeedbackPlanStatusName
    """Where it stands."""
    changes: list[str]
    """For a stale plan, each thing that changed on its PRs since it was written, in the harness's words."""
    stale_shown: bool
    """Whether an approval was refused `stale` for those changes already, so approving again approves it."""
    approved_at: datetime | None = None
    """When it was approved, the latest time."""
    approved_channel: str | None = None
    """How: `cli` or `web`, or `planner` when the harness approved it on its planner's word."""
    approved_reason: str | None = None
    """Why its planner said it needs no review, when the harness approved it so."""
    approved_message: int | None = None
    """The operator message the approval wrote on the ticket, naming the items to address and to leave."""
    spent_run: int | None = None
    """The resume that went ahead on its approval, which it spent."""
    path: str
    """Its file, under the state directory: the operator reads and edits it with their own tools too."""
    text: str | None = None
    """Its Markdown as the file stands, plain text here; None when the file is not a plan any more."""
    problem: str | None = None
    """Why it is not: missing, not a regular file, unreadable, not UTF-8, empty, or over the bound."""
    items: list[FeedbackPlanItem]
    """The items it covers, by number."""


class FeedbackPlanApproval(Model):
    """The operator's approval of a ticket's feedback plan, whole or by item, as `canopy plan KEY --approve` takes."""

    items: Annotated[list[Annotated[int, Field(ge=1)]], Field(max_length=feedback_plans.MAX_ITEMS)] = []
    """The numbers of the items to approve, as `--item N`; the rest are left out. Empty, with `leave` empty, approves
    it whole."""
    leave: Annotated[list[Annotated[int, Field(ge=1)]], Field(max_length=feedback_plans.MAX_ITEMS)] = []
    """The numbers of the items to leave out, as `--leave N`, approving the rest."""
    message: Annotated[str, Field(max_length=feedback_plans.MAX_WORDS + 1000)] | None = None
    """The operator's own words, after the message the approval writes, as `--message`. Bounded again in code."""


class ItemName(Model):
    """An item of a feedback plan, as canopy names it: by number and observed id, never by its text."""

    number: int
    """Its number in the plan."""
    item_id: int
    """Its observed id."""


class FeedbackPlanApproved(Model):
    """What an approval did, as `canopy plan KEY --approve` says it."""

    plan: int
    """The feedback plan approved."""
    ticket_key: str
    """Its ticket, whose next resume goes ahead on it once."""
    addressed: list[ItemName]
    """The items its resume addresses."""
    left: list[ItemName]
    """The items it leaves out, for the next plan."""
    message: int | None = None
    """The operator message the approval wrote on the ticket, naming them: set for every approval of the operator's."""
