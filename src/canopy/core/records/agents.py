"""What canopy knows of its agent runs as the runtime saw them.

The models that served them, the runtime's sessions, what it offered each run, and the personas and models the
operator chose (DESIGN §13, §31).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    ModelsRead,
    OverrideKind,
    SessionsRead,
)


@dataclass(frozen=True)
class TicketOverride(Row):
    """The operator's choice for one of a ticket's agents, in force until cleared (DESIGN §31, §13)."""

    TABLE: ClassVar[LiteralString] = "ticket_overrides"

    ticket_key: str
    #: `worker`, `planner`, or `reviewer`.
    agent: str
    kind: OverrideKind
    #: What the operator chose: a persona's name.
    value: str
    #: `cli` or `web`: where the operator set it.
    channel: str
    set_at: str


@dataclass(frozen=True)
class NextRunPersona(Row):
    """The persona the operator chose for the next run alone of one of a ticket's agents (DESIGN §31)."""

    TABLE: ClassVar[LiteralString] = "next_run_personas"

    ticket_key: str
    #: `worker` or `planner`.
    agent: str
    #: The persona's name.
    persona: str
    #: `cli` or `web`: where the operator set it.
    channel: str
    set_at: str


@dataclass(frozen=True)
class PersonaText(Row):
    """The text of a persona a run or a review was given, once per digest (DESIGN §31)."""

    TABLE: ClassVar[LiteralString] = "persona_texts"

    #: The sha256 of `text`, in hex, as a run's `persona_digest` names it.
    digest: str
    #: The persona's text as the prompt carried it.
    text: str
    recorded_at: str


@dataclass(frozen=True)
class RunTool(Row):
    """What one tool's calls in an agent run put into its context (DESIGN §13): the run, by its table and id."""

    TABLE: ClassVar[LiteralString] = "run_tools"

    run_table: str
    run_id: int
    tool: str
    calls: int
    errors: int
    result_chars: int


@dataclass(frozen=True)
class RunModelRead(Row):
    """How canopy's last read of an agent run's session for its models ended (DESIGN §13): the run, by table and id."""

    TABLE: ClassVar[LiteralString] = "run_model_reads"

    run_table: str
    run_id: int
    status: ModelsRead
    #: canopy's words for why it failed; None unless `failed`.
    error: str | None
    #: How many times canopy has read it.
    attempts: int
    read_at: str
    #: The runtime's version the session's record names, kept from the last read that found it; None where none did.
    runtime_version: str | None


@dataclass(frozen=True)
class RunModel(Row):
    """One model an agent run's session names as having written its replies (DESIGN §13), and what they cost."""

    TABLE: ClassVar[LiteralString] = "run_models"

    run_table: str
    run_id: int
    #: As `provider/model`.
    model: str
    replies: int
    cost_usd: float


@dataclass(frozen=True)
class RuntimeSession(Row):
    """A session the agent runtime keeps, canopy's or not, as the runtime last recorded it (DESIGN §13)."""

    TABLE: ClassVar[LiteralString] = "runtime_sessions"

    session_id: str
    #: The session it ran for as a subagent; None for a session of its own.
    parent_id: str | None
    directory: str
    started_at: str
    updated_at: str
    #: The runtime's own stamp of the update, in milliseconds since the epoch.
    updated_ms: int
    cost_usd: float
    tokens_input: int
    tokens_output: int
    tokens_reasoning: int
    tokens_cache_read: int
    tokens_cache_write: int
    read_at: str


@dataclass(frozen=True)
class RuntimeSessionModel(Row):
    """One model a runtime session's replies name, and what they cost (DESIGN §13)."""

    TABLE: ClassVar[LiteralString] = "runtime_session_models"

    session_id: str
    #: As `provider/model`.
    model: str
    replies: int
    cost_usd: float


@dataclass(frozen=True)
class RuntimeSessionRead(Row):
    """How reading the runtime's sessions stands (DESIGN §13): where the next read starts, and how the last ended."""

    TABLE: ClassVar[LiteralString] = "runtime_session_reads"

    #: Always 1: the table holds one row.
    id: int
    #: The last session read's update, in the runtime's milliseconds, and its id; both None before the first.
    cursor_updated_ms: int | None
    cursor_session_id: str | None
    status: SessionsRead
    #: canopy's words for why it failed; None unless `failed`.
    error: str | None
    #: How many sessions every read so far passed over as ones canopy cannot read.
    skipped: int
    read_at: str


@dataclass(frozen=True)
class RunReplyModel(Row):
    """The model that wrote one reply of an agent run more than one model served (DESIGN §13)."""

    TABLE: ClassVar[LiteralString] = "run_reply_models"

    run_table: str
    run_id: int
    #: The runtime's id of the reply, which the events of the model call that wrote it name in the run's log.
    message: str
    #: As `run_models.model` names it.
    model: str


@dataclass(frozen=True)
class RunOffer(Row):
    """canopy's ask of the runtime, as an agent run started, of what it offered the run (DESIGN §13)."""

    TABLE: ClassVar[LiteralString] = "run_offers"

    run_table: str
    run_id: int
    #: The agent the run's command runs; None when it names none.
    agent: str | None
    #: canopy's words for why the runtime could not say; None when it said.
    error: str | None
    asked_at: str


@dataclass(frozen=True)
class RunOfferedServer(Row):
    """One MCP server the runtime offered an agent run (DESIGN §13)."""

    TABLE: ClassVar[LiteralString] = "run_offered_servers"

    run_table: str
    run_id: int
    server: str
    #: `all` of its tools, or only `some`.
    reach: str


@dataclass(frozen=True)
class RunOfferedSkill(Row):
    """One skill the runtime offered an agent run (DESIGN §13)."""

    TABLE: ClassVar[LiteralString] = "run_offered_skills"

    run_table: str
    run_id: int
    skill: str


@dataclass(frozen=True)
class RunOfferedTool(Row):
    """One of the runtime's built-in tools it offered an agent run (DESIGN §13)."""

    TABLE: ClassVar[LiteralString] = "run_offered_tools"

    run_table: str
    run_id: int
    tool: str


@dataclass(frozen=True)
class RunOfferedServerRule(Row):
    """One rule that leaves an agent run only some of an MCP server's tools (DESIGN §13)."""

    TABLE: ClassVar[LiteralString] = "run_offered_server_rules"

    run_table: str
    run_id: int
    server: str
    #: Where it applies among the server's rules, from 0: a later one wins where both match a tool.
    position: int
    #: `offer` or `deny`, then the tool names it matches, as the runtime's patterns write them.
    rule: str
