"""The API's types for one ticket's page (DESIGN §22), and the operator's start, stop, forget, and grant of it.

Built on `schema.Model`, as every API type is; the ticket as the tickets list shows it is shared (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Attachments, CostTotal, Decision, Limit, Message, Model, Run, TicketSummary
from canopy.serve.schema.draft import Draft
from canopy.serve.schema.model import AgentModel
from canopy.serve.schema.persona import AgentPersona
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
