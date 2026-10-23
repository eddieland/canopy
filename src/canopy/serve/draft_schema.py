"""The API's types for review replies (DESIGN §29): the comments runs drafted in place of posting them.

Also a PR's review threads they answer, and the operator's edits, drops, and sends of them. Built on `schema.Model`,
as every API type is (schema.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.feedback_plan_schema import FeedbackPlan
from canopy.serve.review_schema import ReviewDiff
from canopy.serve.schema import Model

type DraftKindName = Annotated[
    Literal["thread", "pr", "ticket"],
    Field(description="Where a draft goes: a reply on a review thread, its PR's one comment, or the ticket's."),
]
type DraftStatusName = Annotated[
    Literal["unchecked", "waiting", "refused", "superseded", "dropped", "sending", "unconfirmed", "staged", "sent"],
    Field(description="Where a draft stands (DESIGN §29)."),
]
type DraftStanceName = Annotated[
    Literal["changed", "declined", "answered"],
    Field(description="What a thread's draft says the run did: made the change, declined it, or answered a question."),
]
type ReactionName = Annotated[
    Literal["+1", "-1", "laugh", "confused", "heart", "hooray", "rocket", "eyes"],
    Field(description="A reaction a thread's draft stages on the comment it names, by GitHub's name for it."),
]

type ProposalName = Annotated[
    Literal["change", "decline", "ask", "leave"],
    Field(description="What a feedback plan proposes for an item (DESIGN §32)."),
]


class DraftFromPlan(Model):
    """The feedback plan item a thread's draft started from (DESIGN §32), compared in code with what the run wrote."""

    number: int
    """The item's number in its plan, which the operator names it by."""
    item_id: int
    """The review comment's id canopy observed for the item."""
    proposal: ProposalName
    """What the plan proposed for it."""
    reply: str | None = None
    """The reply the plan proposed, model text: plain text, never Markdown, here. None when it proposed none."""
    left_out: bool
    """Whether the operator's approval left the item out."""
    departs: bool
    """Whether the run's own text, or what it says it did, is other than the plan proposed: the operator rereads it."""


class Draft(Model):
    """A comment a run drafted in place of posting it: a worker's text, untrusted until the operator sends it."""

    run: int
    """The run that drafted it."""
    number: int
    """Its number in the run's drafts, from 1: with the run, how the operator names it."""
    ticket_key: str
    """The ticket the run was for."""
    kind: DraftKindName
    """Where it goes."""
    status: DraftStatusName
    """Where it stands."""
    stance: DraftStanceName | None = None
    """For a thread's draft, what the run did about it."""
    comment_id: int | None = None
    """For a thread's draft, the review comment it names."""
    thread_id: str | None = None
    """For a thread's draft, the thread a read found that comment on; None until one did."""
    issue_url: str | None = None
    """For a ticket's draft, the issue it goes to, as the worker named it: shown for the operator to check."""
    why: str | None = None
    """The harness's words for its latest change of status, such as why it was refused."""
    text: str
    """Its text as it stands, the operator's latest edit or the run's own: plain text, never Markdown, here. Empty
    when it sends its reaction alone."""
    reaction: ReactionName | None = None
    """For a thread's draft, the reaction it stages on the comment it names, as it stands."""
    hash: str
    """The name of that text and reaction, which a send carries so what posts is what the operator read."""
    edited: bool
    """Whether the operator edited it."""
    supersedes_edited: bool
    """Whether a draft it superseded carried the operator's edits, which are not carried over."""
    sent_url: str | None = None
    """Once sent, the comment's or the review's URL on GitHub."""
    reacted: ReactionName | None = None
    """The reaction a send added on GitHub, which stays there though the rest of that send posted nothing."""
    created_at: datetime
    """When the run drafted it."""
    from_plan: DraftFromPlan | None = None
    """For a thread's draft whose run followed a feedback plan covering its thread, the item it started from."""


class ThreadComment(Model):
    """One comment on a PR's review thread, as canopy's reader last read it: someone else's text, untrusted."""

    id: int
    """GitHub's id for it."""
    author: str | None = None
    """Its author's login; None for a deleted account."""
    bot: bool
    """Whether GitHub says the author is a bot."""
    created_at: str | None = None
    """When it was posted, as GitHub says it."""
    body: str
    """Its body, cut as a mirrored comment is: plain text here."""
    url: str | None = None
    """Its URL on GitHub."""
    operator_sent: bool
    """Whether the operator sent it through canopy."""


class Thread(Model):
    """A PR's review thread as last read, where it sits on the diff, and the drafts that answer it."""

    id: str
    """GitHub's node id for it."""
    path: str | None = None
    """The file it is on."""
    line: int | None = None
    """The line it is on, on its side; None for an outdated one."""
    side: Literal["left", "right"] | None = None
    """Which side of the diff the line is on."""
    outdated: bool
    """Whether GitHub says the code it is on has changed since."""
    resolved: bool
    """Whether it is resolved: that stays the reviewer's."""
    file: int | None = None
    """The index of its file in the diff, when the diff shows it."""
    diff_line: int | None = None
    """Its line on the diff's new side, when the diff shows it; None puts it under its file."""
    comments: list[ThreadComment]
    """Its comments, oldest first."""
    drafts: list[Draft]
    """The drafts that answer it, the newest run's last."""


class PullRequestThreads(Model):
    """A PR's review threads on the diff of the latest run that kept one, and the drafts waiting to be sent."""

    url: str
    """The PR's URL."""
    review_replies: Literal["approve", "post"]
    """How workers' comments reach GitHub now (DESIGN §29)."""
    read_at: datetime | None = None
    """When canopy's reader last read the PR whole; None when it never has."""
    head_sha: str | None = None
    """The PR's head when it was read."""
    diff_run: int | None = None
    """The run whose diff this is, at its pushed head; None when no run kept one."""
    diff_head: str | None = None
    """The commit the diff was taken at, when it was kept."""
    diff: ReviewDiff | None = None
    """The diff; None when no run kept one."""
    threads: list[Thread]
    """Its review threads, in file order, then by line."""
    pr_drafts: list[Draft]
    """The drafts for the PR's own comment, which goes in the review's body."""
    unplaced: list[Draft]
    """Drafts no read has placed on a thread yet: unchecked, or refused for naming one the PR does not have."""
    feedback_plan: FeedbackPlan | None = None
    """The current feedback plan of the PR's ticket, when it covers the PR's repository (DESIGN §32): each item names
    the thread it is."""


class DraftEditRequest(Model):
    """An edit of a draft's words, as `canopy draft edit run:ID N --text TEXT [--react NAME | --no-react]` takes it."""

    text: Annotated[str, Field(max_length=8000)]
    """The draft's new text, empty beside a reaction to send it alone. Bounded again in code, as a run's draft is."""
    reaction: ReactionName | None
    """The reaction it stages, or None for none: given every time, so an edit never keeps one the page did not show."""


class DraftDropRequest(Model):
    """A drop of a draft, or with `undo` the taking back of one."""

    undo: bool = False
    """Take the drop back, as `--undo` does."""


class DraftRef(Model):
    """A draft the operator sends, and the hash of its text as the page showed it."""

    run: Annotated[int, Field(ge=1)]
    """The run that drafted it."""
    number: Annotated[int, Field(ge=1, le=30)]
    """Its number in the run's drafts."""
    hash: Annotated[str, Field(min_length=12, max_length=12, pattern=r"^[0-9a-f]+$")]
    """The hash of its text as the operator last saw it."""


class DraftSendRequest(Model):
    """Drafts to send or stage together, as `canopy draft send` and `stage` take them: one PR's go as one review."""

    drafts: Annotated[list[DraftRef], Field(min_length=1, max_length=30)]
    """The drafts, each with the hash of the text the page showed."""


class DraftFailure(Model):
    """A draft a send could not post, and why: it waits on the operator again."""

    draft: Draft
    """The draft, as it now stands."""
    why: str
    """Why nothing was posted, in the harness's words."""


class DraftsSent(Model):
    """What a send or a stage did, as `canopy draft send` and `canopy draft stage` report it."""

    posted: list[Draft]
    """The drafts posted now."""
    already: list[Draft]
    """The drafts a send had posted before, which this one left alone."""
    failed: list[DraftFailure]
    """The drafts whose post failed, which wait again."""
    unconfirmed: list[Draft]
    """The drafts whose post ended without saying whether it submitted, until a read of the PR settles them."""
    staged: list[Draft]
    """The drafts a stage put in a pending review, for the operator to submit on GitHub."""
