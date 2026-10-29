"""canopy's agents, and what config decides each may do (DESIGN §13), whatever runtime's format they are written in.

The runtime's implementation writes `Rules` into the definitions it ships (`canopy.runtime.definitions`), each in its
own format; these are what canopy decides, and the names it runs each agent by. `Offerings` is what each agent is then
offered once the runtime has merged the operator's own config into canopy's (`canopy.runtime.offerings`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from collections.abc import Set as AbstractSet

WORKER = "canopy-worker"
PRIVATE_WORKER = "canopy-worker-private"
PLANNER = "canopy-planner"
REVIEWER = "canopy-reviewer"
OVERSEER = "canopy-overseer"
CHORE = "canopy-chore"
#: What a chore's own copy of `CHORE` is named after: a chore with a model of its own runs `canopy-chore-<chore>`,
#: rendered as `CHORE` is but for its model (DESIGN §19, §13). No other agent's name starts so.
CHORE_COPY_PREFIX = f"{CHORE}-"


def chore_agent(chore: str) -> str:
    """Return the name of chore `chore`'s own copy of `CHORE`, which runs it on a model of its own."""
    return f"{CHORE_COPY_PREFIX}{chore}"


class DefinitionsError(Exception):
    """canopy's definitions cannot be made, or a snapshot of them is not one canopy made, so no run may load them."""


@dataclass(frozen=True)
class McpTools:
    """An MCP server, and the only tools of it an agent may call: every other one is denied."""

    server: str
    #: Its read tools, which every agent rendered with it may call.
    allowed: Sequence[str]
    #: The tools that create a ticket, which a private worker may call to file its follow-ups (DESIGN §18, §22).
    create: Sequence[str] = ()
    #: The tools that open, update, and reply on a PR, where the server is also the one PRs go through (GitHub's): the
    #: private worker's, for its own PRs. The planner writes nothing, so gets neither these nor `create`, even where
    #: `allowed` names them.
    pr_writes: Sequence[str] = ()


@dataclass(frozen=True)
class Publishing:
    """The artifact store's MCP server (DESIGN §38), the tools of it an agent that publishes may call, and those agents.

    Every other agent of canopy's is denied the server whole, and the planner and the private worker never publish.
    """

    server: str
    tools: Sequence[str]
    #: The agents that publish, by name: each may call `tools`, and no other tool of the server.
    agents: AbstractSet[str]


@dataclass(frozen=True)
class Drafts:
    """Whether a worker drafts its comments rather than posting them (DESIGN §29), and which it still posts."""

    #: The worker drafts its PR replies, so the tools that post them are denied.
    approve: bool
    #: The worker still posts its ticket comments itself, so the tools that comment on an issue stay.
    ticket_comments: bool


@dataclass(frozen=True)
class Model:
    """A model the operator chose for an agent (DESIGN §13): the model, and the variant of it to run at, if any."""

    #: The model as the runtime names it, `provider/model`.
    id: str
    #: The variant, such as a reasoning effort, as the runtime names it; None for the model's default.
    variant: str | None = None

    @property
    def name(self) -> str:
        """The model as canopy's config and journal spell it: `provider/model`, then `@variant` when it has one."""
        return self.id if self.variant is None else f"{self.id}@{self.variant}"


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
    #: The overseer's prompt.
    overseer_prompt: str
    #: The tracker's provider, which says whether GitHub's issue tools are the tracker's.
    tracker_provider: str
    #: The commands config allows each agent beyond its own bash rules, by agent name: each a rule the runtime matches
    #: a command line against (`canopy.runtime.definitions.BASH_ALLOW_RE`). An agent not named gets none.
    bash_allows: Mapping[str, Sequence[str]]
    #: The artifact store's server and who publishes to it; None when no store is configured, and no rule names one.
    artifacts: Publishing | None
    #: Each agent's model by name, chosen by the operator alone (`runtime.models`, a chore's `model`, DESIGN §13). An
    #: agent not named runs on the runtime's default.
    models: Mapping[str, Model]
    #: The chores' own copies of `CHORE` by name (`chore_agent`), each rendered as `CHORE` is, then with its own model.
    chore_agents: Sequence[str]
    #: The tracker's MCP server, as config or the provider's defaults name it, even with no read tools known; None when
    #: neither names one.
    tracker_server: str | None


#: How much of an MCP server's tools an agent is offered: every one, only some, or none.
Reach = Literal["all", "some", "none"]


@dataclass(frozen=True)
class ServerOffer:
    """One MCP server, as one agent is offered it."""

    #: The server, as the runtime's config names it.
    server: str
    reach: Reach
    #: The rules that make the reach `some`, in the order they apply, the last that matches a tool winning: each the
    #: tool names they match, as the runtime's patterns write them, after `offer` or `deny`.
    exceptions: Sequence[str] = ()


@dataclass(frozen=True)
class AgentOffer:
    """What one of canopy's agents is offered, after the operator's config: MCP servers, skills, and built-in tools."""

    agent: str
    servers: Sequence[ServerOffer] = ()
    #: The skills it is offered, and those it is denied, by name.
    skills: Sequence[str] = ()
    denied_skills: Sequence[str] = ()
    #: The runtime's own tools it is offered, by name: its MCP servers' are in `servers`.
    tools: Sequence[str] = ()
    #: Why the runtime could not say what the agent is offered, or None when it said.
    error: str | None = None


@dataclass(frozen=True)
class Offerings:
    """What the runtime offers canopy's agents, where they start."""

    #: Every MCP server the runtime has configured, by name, and those its config turns off for every agent.
    servers: Sequence[str] = ()
    disabled_servers: Sequence[str] = ()
    #: Every skill the runtime finds, by name.
    skills: Sequence[str] = ()
    agents: Sequence[AgentOffer] = ()
    #: Why the runtime could not list its servers or its skills, or None when it did.
    error: str | None = None
