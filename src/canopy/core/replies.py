"""How a worker's comments reach GitHub (`trust.review_replies`, DESIGN §29): posted by the worker, or drafted.

Under `post` a worker posts its replies and comments itself, each marked (D069). Under `approve` it posts none and puts
each in its result's `drafts`, for the operator to send. The prompts of the kinds that comment carry the sentences that
say which as placeholders, and this module renders them: under `post`, each is exactly the text it replaced, so every
prompt is the same bytes as before the setting existed. Dispatch asks for a run's part (`render`) and records what it
was rendered under (`record_rendered`), in the transaction that inserts the run, so `_run` reads the drafts under the
setting the prompt asked for, whatever the config says by the time it ends.

It is core, since dispatch and `_run` write it and the CLI and the web UI read it (DESIGN §5).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from canopy.core import records
from canopy.core.prompts import mark_comments
from canopy.core.vocab import Reaction, ReplyMode, RunKind

if TYPE_CHECKING:
    from canopy.core.config import Config

# The kinds whose workers comment, and so whose prompts say how (DESIGN §29).
COMMENTING_KINDS = frozenset({RunKind.IMPLEMENT, RunKind.RESUME})
# The result's field and the placeholder that asks for it, which every prompt that drafts must carry under `approve`:
# an override written before drafts existed would have its worker post in the operator's name.
DRAFTS = "DRAFTS"
REQUIRED_APPROVE = (DRAFTS,)
MAX_DRAFTS = 30
MAX_DRAFT_CHARS = 4000
# Where a mark goes once a worker posts only on the ticket.
_ON_TICKET = "on the ticket"


@dataclass(frozen=True)
class Rendered:
    """A run's part of its prompt for comments: the setting, whether it may draft for the ticket, and the values."""

    mode: ReplyMode
    ticket_drafts: bool
    values: Mapping[str, str]
    required: tuple[str, ...]


def render(
    config: Config,
    kind: str,
    *,
    private: bool,
    sent: Mapping[str, Mapping[str, Sequence[int]]] | None = None,
) -> Rendered | None:
    """Return how a `kind` run's prompt says its comments reach GitHub, or None for a kind that comments nowhere.

    A ticket's draft is asked for only under `approve`, on a public ticket, with a `tracker` source that posts: the
    harness never branches on the tracker's name (DESIGN §17), so the operator's source is what says canopy can post
    there. Without one, the worker posts its ticket comments itself, marked, under either setting. `sent` holds what
    the operator sent through canopy on the run's PRs (`drafts.sent_by_pr`), which an `approve` prompt names so the
    worker never takes it for review feedback.

    Returns:
        The setting, whether a ticket's draft is asked for, the placeholders' values, and the placeholders the prompt
        must carry; None for a kind other than `implement` and `resume`.
    """
    if kind not in COMMENTING_KINDS:
        return None
    trust = config.trust
    mode = trust.review_replies
    tracker = config.connect.tracker()
    ticket = mode is ReplyMode.APPROVE and not private and bool(tracker.post_cmd.strip())
    marks = mark_comments(trust.comment_prefix, trust.comment_suffix)
    label = config.tracker.needs_human_label
    if mode is ReplyMode.POST:
        return Rendered(mode=mode, ticket_drafts=False, values=posted_values(marks, label), required=())
    ticket_marks = mark_comments(trust.comment_prefix, trust.comment_suffix, where=_ON_TICKET)
    values = _drafted_values(ticket_marks, label, ticket=ticket)
    told = _sent_note(sent or {})
    for name in ("PR_REPLIES", "PRIVATE_PR_REPLIES"):
        values[name] += told
    # A private ticket's implement posts nothing anywhere, so its prompt has no comments to draft.
    required = () if kind == RunKind.IMPLEMENT and private else REQUIRED_APPROVE
    return Rendered(mode=mode, ticket_drafts=ticket, values=values, required=required)


def record_rendered(conn: sqlite3.Connection, run_id: int, rendered: Rendered) -> None:
    """Record what run `run_id`'s prompt was rendered under. Call inside the transaction that inserts the run."""
    records.insert(
        records.RunReplies,
        run_id=run_id,
        mode=rendered.mode,
        ticket_drafts=rendered.ticket_drafts,
    ).run(conn)


def run_replies(conn: sqlite3.Connection, run_id: int) -> records.RunReplies | None:
    """Return what run `run_id`'s prompt was rendered under, or None for a run of a kind that comments nowhere."""
    return records.select(records.RunReplies).where("run_id = ?", run_id).one(conn)


def posted_values(marks: str, label: str) -> dict[str, str]:
    """Each placeholder's text under `post`: what the prompts said before the setting existed, but for their voice.

    The voice, such as how briefly a worker replies, is the persona's now (DESIGN §31). `marks` is the instruction to
    mark each comment (`prompts.mark_comments`), and `label` the needs-human label.

    Returns:
        The values, by placeholder; `{{DRAFTS}}` is empty.
    """
    posts = "You post as the operator, so that is how canopy knows the comment is yours and never reads it"
    return {
        DRAFTS: "",
        # worker-implement.md
        "TICKET_REPORT": (
            "- Comment on the ticket: what you did, every PR link, anything a reviewer should look at first.\n"
            f"- {marks} {posts}\n  back as review feedback or as a reply."
        ),
        "ASK_QUESTION": "Post your question as a ticket comment. One question, concrete, with the\n   options you see.",
        # worker-resume.md
        "CI_NOTE": "Comment on each PR whose checks you fixed, describing the fix.",
        "PR_REPLIES": (
            f"Reply on the PR to each comment you addressed. {marks} You post as the\noperator, so that is "
            "how canopy knows the comment is yours and never reads it back as review feedback or as a reply."
        ),
        "DECLINE": (
            "If a review comment asks for a change you believe is wrong, make the case in a\n"
            "PR reply and do not make the change; report `blocked` with the disagreement as\n"
            "the question so a human can settle it."
        ),
        "ASK_AGAIN": (
            f"If you are blocked again, post your question as a ticket comment, add the label `{label}` the same "
            "way,\nand report `blocked`. If you cannot set the label, say so in the comment."
        ),
        # worker-resume-private.md
        "PRIVATE_PR_REPLIES": (
            "Reply on the PR to each review comment you addressed, and post nothing else\n"
            "but the edit to a PR's body below, when one is needed.\n"
            f"{marks} You post as the operator, so that is how canopy knows the reply is yours and never reads it "
            "back as\nreview feedback."
        ),
        "PRIVATE_DECLINE": (
            "If a review comment asks for a change you believe is wrong, make the case in a PR reply and do not make "
            "the change;\nreport `blocked` with the disagreement as the question so the operator can settle it."
        ),
    }


def _drafted_values(ticket_marks: str, label: str, *, ticket: bool) -> dict[str, str]:
    """Each placeholder's text under `approve`: no comment on a PR, and on the ticket only without a ticket's draft.

    Returns:
        The values, by placeholder.
    """
    on_ticket = (
        f"{ticket_marks} You post as the operator, so that is how canopy knows the comment is yours and never reads "
        "it back as a reply."
    )
    replies = (
        "Post no comment, reply, or reaction on a PR: put your reply to each review comment you addressed in a\n"
        "`thread` draft (Result, below), for the operator to send as their own."
    )
    decline = (
        "If a review comment asks for a change you believe is wrong, make the case in a\n"
        '`thread` draft with `"did":"declined"` and do not make the change; report `blocked` with the disagreement '
        "as\nthe question so {who} can settle it."
    )
    values = {
        DRAFTS: _contract(ticket=ticket),
        "CI_NOTE": "Describe the fix in a `pr` draft for that PR (Result, below), not in a comment.",
        "PR_REPLIES": replies if ticket else f"{replies} {on_ticket}",
        "DECLINE": decline.format(who="a human"),
        "PRIVATE_PR_REPLIES": f"{replies} Change nothing on a PR but the edit to its body below, when one is needed.",
        "PRIVATE_DECLINE": decline.format(who="the operator"),
    }
    if ticket:
        values["TICKET_REPORT"] = (
            "- Post no comment, on the ticket or a PR: put what you did, every PR link, and anything a reviewer "
            "should\n  look at first in a `ticket` draft (Result, below), for the operator to send as their own."
        )
        values["ASK_QUESTION"] = (
            "Put your question in a `ticket` draft (Result, below), not a comment. One question, concrete, with the\n"
            "   options you see."
        )
        values["ASK_AGAIN"] = (
            f"If you are blocked again, put your question in a `ticket` draft, add the label `{label}` the same way,\n"
            "and report `blocked`. If you cannot set the label, say so in the draft."
        )
        return values
    posted = posted_values(ticket_marks, label)
    values["TICKET_REPORT"] = (
        "- Comment on the ticket: what you did, every PR link, anything a reviewer should look at first. Post no "
        f"comment\n  on a PR.\n- {on_ticket}"
    )
    values["ASK_QUESTION"] = posted["ASK_QUESTION"]
    values["ASK_AGAIN"] = posted["ASK_AGAIN"]
    return values


def _sent_note(sent: Mapping[str, Mapping[str, Sequence[int]]]) -> str:
    """The sentence naming what the operator sent through canopy on the run's PRs, or "" when nothing.

    Returns:
        The sentence, starting with a space.
    """
    named = [
        f"{pr}: comments {_ids(ids['comments'])}, reviews {_ids(ids['reviews'])}"
        for pr, ids in sorted(sent.items())
        if ids["comments"] or ids["reviews"]
    ]
    if not named:
        return ""
    return (
        " The operator already sent these through canopy, unmarked, as their own: "
        f"{'; '.join(named)}. They are the operator's answers to reviewers, not review feedback to address."
    )


def _ids(ids: Sequence[int]) -> str:
    return ", ".join(map(str, ids)) or "none"


#: What the tool says of every draft's text.
_TEXT = (
    f"At most {MAX_DRAFT_CHARS:,} characters of GitHub Markdown, written as the operator would say it, with no secret "
    "and no hidden characters."
)


class ThreadDraft(BaseModel):
    """A reply on a review thread, as a run's `result` call drafts it."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    on: Literal["thread"] = Field(description="`thread`: a reply on a review thread.")
    pr: StrictStr = Field(description="The PR's URL, one of this run's PRs.")
    comment: StrictInt = Field(
        description="The id of any review comment on the thread: the number in its URL after `#discussion_r`.",
    )
    did: Literal["changed", "declined", "answered"] = Field(
        description="Whether you made the change it asked for, declined it, or answered a question.",
    )
    text: StrictStr | None = Field(default=None, description=f"The reply. {_TEXT} Leave it out with `react` alone.")
    react: Reaction | None = Field(
        default=None,
        description="A reaction on the comment `comment` names, where one says what a reply would, such as `+1` on a "
        "nit you fixed: give it and leave `text` out.",
    )


class PrDraft(BaseModel):
    """A comment on a PR, as a run's `result` call drafts it."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    on: Literal["pr"] = Field(
        description="`pr`: a comment on the PR, at most one a PR, for what is no reply on a thread, such as an answer "
        "to a review's own text, or what you fixed in CI.",
    )
    pr: StrictStr = Field(description="The PR's URL, one of this run's PRs.")
    text: StrictStr = Field(description=f"The comment. {_TEXT}")


class TicketDraft(BaseModel):
    """A comment on the ticket, as a run's `result` call drafts it."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    on: Literal["ticket"] = Field(
        description="`ticket`: a comment on the ticket, at most one: your question when you are blocked, and otherwise "
        "what you did, every PR link, and anything a reviewer should look at first.",
    )
    url: StrictStr = Field(description="The ticket's URL.")
    text: StrictStr = Field(description=f"The comment. {_TEXT}")


#: What the tool says of the drafts as a whole.
_DRAFTS = (
    "Each comment you would otherwise have posted, which canopy keeps for the operator. They read each one where it "
    "goes, may edit or drop it, and send it as their own words, so post none of them yourself and mark none. Nobody "
    f"but the operator sees a draft until they send it. At most {MAX_DRAFTS}."
)


class DraftsGroup(BaseModel):
    """The comments a run drafts on its PRs, a group of its result's fields (`core.run_result`) under `approve`."""

    drafts: list[Annotated[ThreadDraft | PrDraft, Field(discriminator="on")]] = Field(
        default_factory=list,
        description=_DRAFTS,
    )


class TicketDraftsGroup(BaseModel):
    """The comments a run drafts on its PRs and its ticket, where canopy can post the ticket's for the operator."""

    drafts: list[Annotated[ThreadDraft | PrDraft | TicketDraft, Field(discriminator="on")]] = Field(
        default_factory=list,
        description=_DRAFTS,
    )


#: The groups' names: the drafts of a run that drafts for its PRs alone, and of one that drafts for its ticket too.
DRAFTS_GROUP = "drafts"
TICKET_DRAFTS_GROUP = "ticket_drafts"
GROUPS: Mapping[str, type[BaseModel]] = {DRAFTS_GROUP: DraftsGroup, TICKET_DRAFTS_GROUP: TicketDraftsGroup}


def asked_group(rendered: records.RunReplies | None) -> list[str]:
    """The group of `GROUPS` a run whose prompt was rendered under `rendered` is asked for (DESIGN §29).

    Returns:
        The group's name, in a list; none for a run that posts its own comments, or comments nowhere.
    """
    if rendered is None or rendered.mode is not ReplyMode.APPROVE:
        return []
    return [TICKET_DRAFTS_GROUP if rendered.ticket_drafts else DRAFTS_GROUP]


def _contract(*, ticket: bool) -> str:
    """Return `{{DRAFTS}}`: where every comment the run would have posted goes instead (DESIGN §29).

    The run's `result` tool says what a draft holds; this says only that the run writes them, so a prompt that drops
    it, as an override written before drafts existed would, fails to render rather than have its worker post.

    Returns:
        The sentence, starting with the blank line before it.
    """
    where = "its PRs and its ticket" if ticket else "its PRs"
    return (
        "\n\nEach comment you would otherwise have posted on "
        f"{where} goes in your result's `drafts`, which canopy keeps for the operator to send as their own: post "
        "none of them yourself and mark none."
    )
