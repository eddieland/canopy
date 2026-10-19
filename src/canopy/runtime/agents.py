"""canopy's agents, and what config decides each may do (DESIGN §13), whatever runtime's format they are written in.

The runtime's implementation writes `Rules` into the definitions it ships (`canopy.runtime.definitions`), each in its
own format; these are what canopy decides, and the names it runs each agent by.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

WORKER = "canopy-worker"
PRIVATE_WORKER = "canopy-worker-private"
PLANNER = "canopy-planner"
#: The triage agent: the planner with nothing to edit (DESIGN §25, Triage before a plan).
PLAN_TRIAGE = "canopy-plan-triage"
REVIEWER = "canopy-reviewer"
OVERSEER = "canopy-overseer"
SPLITTER = "canopy-splitter"
CHORE = "canopy-chore"


class DefinitionsError(Exception):
    """canopy's definitions cannot be made, or a snapshot of them is not one canopy made, so no run may load them."""


@dataclass(frozen=True)
class McpTools:
    """An MCP server, and the only tools of it an agent may call: every other one is denied."""

    server: str
    allowed: Sequence[str]
    #: The tools that create a ticket, which a private worker may call to file its follow-ups (DESIGN §18, §22).
    create: Sequence[str] = ()


@dataclass(frozen=True)
class Drafts:
    """Whether a worker drafts its comments rather than posting them (DESIGN §29), and which it still posts."""

    #: The worker drafts its PR replies, so the tools that post them are denied.
    approve: bool
    #: The worker still posts its ticket comments itself, so the tools that comment on an issue stay.
    ticket_comments: bool


@dataclass(frozen=True)
class Rules:
    """What canopy decided from config that each agent may do, which the definitions are rendered with."""

    #: The tracker's server and its read tools, for the agents that may only read it; None when none is known.
    tracker_tools: McpTools | None
    #: Whether workers may push a rebased branch with a lease.
    rebase: bool
    #: What the public worker and the private one draft.
    worker_drafts: Drafts
    private_drafts: Drafts
    #: Each agent's temperature by name, None to set none and leave the model's own: some models, such as OpenAI's
    #: reasoning models, refuse a request that sets one. An agent not named keeps its file's marked line as it is.
    temperatures: Mapping[str, float | None]
    #: The overseer's prompt, and the tracker's provider, whose shipped skill, if any, follows it.
    overseer_prompt: str
    tracker_provider: str
