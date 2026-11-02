"""The API's types for a ticket's plans (DESIGN §25): the plans, the newest as its file stands, and comments on it.

Also the operator's word on a plan, and edits of it. Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.core import plans
from canopy.serve.schema import Model
from canopy.serve.schema.persona import RunPersona


class PlanSummary(Model):
    """One of a ticket's plans (DESIGN §25): its status and approval, never its text."""

    id: int
    """The plan's id, as `canopy show --plans` names it `plan:ID`."""
    run_id: int
    """The plan run that wrote it, whose id names its file."""
    status: Literal["proposed", "approved", "superseded"]
    """Waiting on the operator, approved, or replaced by a newer plan, a request for one, a skip, or a forget."""
    created_at: datetime
    """When the planner wrote it."""
    approved_at: datetime | None = None
    """When the operator approved it, the latest time; none if never."""
    approved_channel: str | None = None
    """How they approved it: `cli` or `web`; or `planner`, when the harness approved it on its planner's word."""
    approved_reason: str | None = None
    """Why the planner said the plan needs no review, when the harness approved it so; none otherwise."""
    effort: Literal["small", "medium", "large"] | None = None
    """How much work the plan is for its worker, as its planner judged; none when it gave no estimate."""


class PlanFile(Model):
    """A plan as its file stands now, read bounded and never through a link (DESIGN §25, Where plans live)."""

    plan: PlanSummary
    """The plan the file is."""
    persona: RunPersona | None = None
    """The persona its planner wrote in, and its instructions; none for a run from before canopy recorded one."""
    path: str
    """The file, under the state directory: the operator reads and edits it with their own tools too."""
    text: str | None = None
    """Its Markdown, or none when the file is not a plan any more: `problem` says why."""
    problem: str | None = None
    """Why it is not: missing, not a regular file, unreadable, not UTF-8, empty, or over the bound."""
    sha256: str | None = None
    """The file's SHA-256 now, whenever it could be read: what a save sends back, so an edit made elsewhere since is
    never overwritten unseen."""
    edited: bool
    """Whether it differs from what the planner wrote."""
    changed_since_approval: bool
    """For an approved plan, whether it differs from the text the operator approved, which then needs approving again
    before its implement (`plan_changed`)."""


class PlanReplyView(Model):
    """A reply in a comment thread on a plan."""

    id: int
    """Its id, unique among the ticket's replies."""
    body: str
    """What it says."""
    at: datetime
    """When it was written."""


class PlanThreadView(Model):
    """One of the operator's comments on a ticket's plan: a thread on a passage, with its replies (DESIGN §25)."""

    id: int
    """Its id, unique among the ticket's threads."""
    quote: str
    """The passage it is on, whitespace collapsed."""
    prefix: str
    """Up to 32 characters before the passage, the nearest last."""
    suffix: str
    """Up to 32 characters after it, the nearest first."""
    body: str
    """What the comment says."""
    at: datetime
    """When it was written."""
    resolved: bool
    """Whether the operator resolved it. A resolved thread is kept, and asks the planner for nothing."""
    replies: list[PlanReplyView]
    """Its replies, oldest first."""


class TicketPlans(Model):
    """A ticket's plans: whether it needs one, the newest as its file stands, the earlier ones, and the comments."""

    needed: bool
    """Whether its implement waits on an approved plan, by its own setting or `policy.plan`."""
    setting: Literal["plan", "skip"] | None = None
    """The operator's own word for this ticket, which overrides the policy; none to follow it."""
    policy: Literal["off", "approve"]
    """`policy.plan`."""
    planning: int | None = None
    """The plan run writing a plan for it now, if one is: the plan verbs and a save refuse until it ends."""
    changes_asked: datetime | None = None
    """When the operator asked for changes no planner has read yet, as the overseer reads it; none if they have not."""
    newest: PlanFile | None = None
    """The newest plan, as its file stands; none if it has had none."""
    plans: list[PlanSummary]
    """Every plan, oldest first, the newest included."""
    threads: list[PlanThreadView]
    """The operator's comments, oldest first: a thread is the ticket's, not one plan's, so it carries to the next."""


class PlanAction(Model):
    """The operator's word on a ticket's plan: `canopy plan KEY --approve`, `canopy plan KEY`, or `--skip`."""

    action: Literal["approve", "request", "skip"]
    """`approve` the newest plan as its file stands, `request` a new plan, or `skip` the plan."""
    message: Annotated[str, Field(max_length=plans.MAX_NOTE + 1000)] | None = None
    """With `approve`, the operator's note for its implement, written on the ticket with the approval, as `--message`.
    Bounded again in code."""


class PlanChanged(Model):
    """What the operator's word on a plan did."""

    action: Literal["approve", "request", "skip"]
    """What was asked."""
    plan: int | None = None
    """The plan approved, for `approve`."""
    superseded: int | None = None
    """The plan a request or a skip superseded, if the ticket had one."""
    already: bool
    """Whether the ticket's setting already said so, and nothing was superseded."""


class PlanSave(Model):
    """The plan editor's Markdown, to write over the plan's file, and the file's hash as the editor read it."""

    markdown: Annotated[str, Field(max_length=100_000)]
    """The plan as edited. A plan is at most 100,000 characters (DESIGN §25)."""
    read_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    """The file's SHA-256 when the editor read it: a file changed since is refused, never overwritten unseen."""


class PlanSaved(Model):
    """The plan's file as saved."""

    sha256: str
    """Its SHA-256 now: what the next save sends back."""
    size: int
    """Its size in bytes."""


class PlanCommentRequest(Model):
    """A comment on a passage of a ticket's plan: the passage, the text either side of it, and what it says."""

    quote: Annotated[str, Field(min_length=1, max_length=4000)]
    """The passage, whitespace collapsed."""
    prefix: Annotated[str, Field(max_length=32)] = ""
    """Up to 32 characters before it."""
    suffix: Annotated[str, Field(max_length=32)] = ""
    """Up to 32 characters after it."""
    body: Annotated[str, Field(max_length=20_000)]
    """What it says. Bounded again in code at 4000 characters, after stripping."""


class PlanReplyRequest(Model):
    """A reply in a comment thread on a plan."""

    body: Annotated[str, Field(max_length=20_000)]
    """What it says. Bounded again in code at 4000 characters, after stripping."""


class PlanAnchor(Model):
    """A comment's passage, as its words and the text either side of them, each with its whitespace collapsed."""

    quote: Annotated[str, Field(min_length=1, max_length=4000)]
    """The passage."""
    prefix: Annotated[str, Field(max_length=32)] = ""
    """Up to 32 characters before it."""
    suffix: Annotated[str, Field(max_length=32)] = ""
    """Up to 32 characters after it."""


class PlanThreadChange(Model):
    """A change to a comment thread on a plan: its comment's words, a reply's, or whether it is resolved."""

    body: Annotated[str, Field(max_length=20_000)] | None = None
    """New words for the comment, or with `reply` for that reply."""
    reply: int | None = None
    """The reply `body` is for; none for the comment itself."""
    resolved: bool | None = None
    """Resolve the thread, or reopen it; none to leave it."""
    anchor: PlanAnchor | None = None
    """The passage as it now stands, after an edit of the plan moved or changed its words; none to leave it."""


class PlanThreadDeleted(Model):
    """A comment thread on a plan, deleted with its replies."""

    id: int
    """The thread deleted."""
