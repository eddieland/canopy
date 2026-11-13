"""The API's types for one ticket's page (DESIGN §22), and the operator's start, stop, forget, and grant of it.

Built on `schema.Model`, as every API type is; the ticket as the tickets list shows it is shared (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from canopy.serve.schema import Attachments, CostTotal, Decision, Limit, Message, Model, Run, TicketSummary
from canopy.serve.schema.desk import TicketDesk
from canopy.serve.schema.draft import Draft
from canopy.serve.schema.model import AgentModel, ModelRequest
from canopy.serve.schema.persona import AgentPersona, PersonaRequest
from canopy.serve.schema.spend import SpendModel

type GrantKind = Annotated[
    Literal["implement", "resume"],
    Field(description="A kind of run a ticket's unit is limited in, which `canopy grant` raises (DESIGN §8, §22)."),
]


class Unit(Model):
    """A ticket's work in one repository: its PR and phase (DESIGN §18)."""

    repo: str | None = None
    """The repository, as the workspace names it."""
    pr_url: str | None = None
    """The URL of its PR, once it has one."""
    phase: str | None = None
    """The overseer's last derived phase for this unit, for display; never read as truth."""


class LeftFeedback(Model):
    """Feedback on a ticket's PR its `review` cursor passed with no worker, still left (DESIGN §7), and why."""

    number: int
    """Its journal number, what `canopy send KEY N` names it by."""
    repo: str | None = None
    """The repository of the unit whose PR it is on."""
    pr_url: str
    """The PR it is on."""
    item: Literal["review", "comment", "pr_comment"]
    """A review comment, a review with something to say, or a comment on the PR's conversation."""
    id: int
    """GitHub's id for it."""
    author: str | None = None
    """Who wrote it, as the reader saw them."""
    path: str | None = None
    """The file a review comment is on; None for a review."""
    line: int | None = None
    """Its line in that file."""
    url: str | None = None
    """Its link on GitHub."""
    body: str
    """What it says, as the reader last saw it: the reviewer's text, shown, never acted on."""
    reason: Literal[
        "optional",
        "would_reset_approval",
        "question",
        "already_done",
        "out_of_scope",
        "operator_said",
        "resolved",
    ]
    """Why it was left (`vocab.PassReason`)."""
    decider: Literal["overseer", "harness"]
    """The overseer, who named it, or the harness, for one on a resolved thread."""
    tick_id: int
    """The tick whose cursor move passed it."""


class LeftSendRequest(Model):
    """Feedback a ticket left with no worker to send to one, by number, with the submission id the form drew."""

    numbers: Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=1, max_length=20)]
    """The items' journal numbers, as `left_feedback` lists them."""
    submission: Annotated[str, Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
    """The id the form drew when the items were picked, sent again unchanged on a retry."""


class LeftSent(Model):
    """What sending left feedback recorded: the operator message on the ticket that names it."""

    numbers: list[int]
    """The items sent, by number."""
    message_id: int
    """The message, the operator's go-ahead on them."""
    new: bool
    """Whether it was recorded now, rather than by an earlier submission with the same id."""


class TicketForget(Model):
    """One time the operator forgot a ticket's work (DESIGN §22), and what it dropped."""

    at: datetime
    """When."""
    channel: str | None = None
    """How: `cli` or `web`. None, with `prs`, for a forget made before canopy recorded them."""
    run_id: int | None = None
    """The ticket's newest run then, if it had one."""
    message_id: int | None = None
    """The ticket's newest message then, if it had one: the messages up to it are from before the forget."""
    branch: str | None = None
    """The branch it dropped, the operator's to delete."""
    prs: list[str] | None = None
    """The URLs of the PRs it dropped, the operator's to close; None when not recorded."""


class TicketMembership(Model):
    """The epic a ticket is a member of (DESIGN §43), and the entries of its breakdown it fulfils."""

    epic_id: int
    """The epic, `epic:N`."""
    entries: list[str]
    """The breakdown's entries it fulfils that the epic's approved plan holds, `B<n>`, by number; empty for a member of
    no entry. While no approved plan can be read, every entry it was registered against."""
    dropped: list[str] = []
    """Entries it was registered against that a later approved plan dropped."""
    added_at: datetime
    """When the operator made it a member."""


class TicketDetail(Model):
    """One ticket: what `canopy show` prints, and the latest decisions about it."""

    ticket: TicketSummary
    """The ticket, as the tickets list shows it."""
    units: list[Unit]
    """Its work in each repository."""
    limits: list[Limit] = []
    """Each kind's limit in each repository it has had runs in, then the review limit of each of its units' PRs canopy
    has reviewed."""
    runs: list[Run]
    """Its latest runs, newest first."""
    messages: list[Message]
    """Its conversation: the latest 100 messages, oldest first."""
    forgets: list[TicketForget] = []
    """Each time the operator forgot its work (DESIGN §22), oldest first. The messages up to the latest one's are
    history the loop no longer reads, kept for the operator."""
    decisions: list[Decision]
    """The latest 20 decisions about it across ticks, newest first: why the loop did, or did not, work it."""
    cost: CostTotal
    """What every run of it and every review run naming it cost; not the overseer, whose ticks serve the workspace."""
    drafts: list[Draft] = []
    """Its own drafts (DESIGN §29), the comments its runs would have posted on it, the newest run's first; at most
    10."""
    personas: list[AgentPersona] = []
    """The persona each of its agents writes in at its next run (DESIGN §31): its workers', its planner's, and its
    reviewer's, in that order."""
    persona_names: list[str] = []
    """Every persona a run could get, by name, as `canopy personas` lists them: what the operator may choose from."""
    models: list[AgentModel] = []
    """The model each of its agents runs on at its next run (DESIGN §13): its workers', its planner's, and its
    reviewer's, in that order. What the operator may choose from is `GET /models`', read when they ask."""
    worker_models: list[SpendModel] = []
    """What its worker runs that started in the last 30 local days spent on each model, each beside the workspace's
    worker runs on the same model: Spend's By model for it, at 30 days, narrowed to workers."""
    attachments: Attachments
    """The files the operator attached to it, which its runs read (DESIGN §22)."""
    left_feedback: list[LeftFeedback] = []
    """The feedback on its PRs its `review` cursors passed with no worker that is still left, oldest first: unanswered
    on its thread, on a thread not resolved. `canopy send KEY N` sends one to a worker."""
    desk: TicketDesk
    """The operator's own checkout of its branch (DESIGN §18): what a desk would cover, and the desk while open."""
    membership: TicketMembership | None = None
    """The epic it is a member of, and the entries it fulfils; none for a ticket of no epic."""


class StartRequest(Model):
    """A start, whether the ticket is planned first, and the persona and model each of its agents takes from it.

    Each persona and model is the ticket page's choice (`PersonaRequest`, `ModelRequest`), its override. All of it is
    set with the start or not at all: one refused starts nothing.
    """

    plan: bool | None = None
    """Whether its implement waits on a plan the operator approves: True as `canopy start --plan` asks, False as
    `canopy plan KEY --skip` waives it, whatever `policy.plan` says; None leaves the ticket's own setting as it is."""
    personas: Annotated[list[PersonaRequest], Field(max_length=3)] = []
    """A persona for each agent named, at most one each; none leaves the ticket's overrides as they are."""
    models: Annotated[list[ModelRequest], Field(max_length=3)] = []
    """A model for each agent named, at most one each; none leaves the ticket's overrides as they are."""

    @model_validator(mode="after")
    def _one_each(self) -> Self:
        for kind, agents in (
            ("persona", [p.agent for p in self.personas]),
            ("model", [m.agent for m in self.models]),
        ):
            if len(set(agents)) < len(agents):
                msg = f"one {kind} per agent"
                raise ValueError(msg)
        return self


class Started(Model):
    """What a start did: whether it was already started, and a run already working it."""

    already: bool
    """Whether the ticket was already started, so nothing changed."""
    running_run: int | None = None
    """A run already working the ticket, if one is."""
    running_private: bool | None = None
    """Whether that run is private; a public one may still write to the ticket."""


class StopRequest(Model):
    """A stop, and whether to end the running run now, as `canopy stop --now` does."""

    now: bool = False
    """End the run working the ticket now, rather than let it finish."""


class Stopped(Model):
    """What a stop did: whether it was already stopped, the run still working it, and whether `now` ended that run."""

    already: bool
    """Whether the ticket was already stopped, so nothing changed."""
    running_run: int | None = None
    """A run still working the ticket, if one is."""
    ended: bool = False
    """Whether `now` ended that run."""


class ForgetRequest(Model):
    """A forget, and the ticket's key as the operator typed it: the challenge, checked again in code (DESIGN §22)."""

    confirm: Annotated[str, Field(max_length=200)]
    """The ticket's key, typed by the operator; anything else is refused `not_confirmed`."""


class Forgot(Model):
    """What a forget cleared: the ticket's branch and its units' PRs, which are the operator's to close and delete."""

    branch: str | None = None
    """The branch the ticket's work was on."""
    prs: list[str]
    """The URLs of its units' PRs."""


class GrantRequest(Model):
    """A grant of one more run of a kind to one of a ticket's units, as `canopy grant KEY KIND --repo NAME` does."""

    kind: GrantKind
    """The kind of run to allow one more of."""
    repo: Annotated[str | None, Field(max_length=200)] = None
    """The unit's repository; may be left out when the ticket has had runs in one repository only."""
