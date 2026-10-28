"""What an agent run reports, whatever runtime ran it (DESIGN §13): its text, session, cost, and tool calls.

The harness reads these and nothing else of a run's output. The runtime's implementation makes them from what it
printed (`canopy.runtime.stdout`); a template that asks for no events reports text alone. What holds whatever the
runtime is lives here, for the implementation to build on: a session id canopy prints, the sum of the model calls, and
the bounded rollup of the tool calls, and which models served a session, as the runtime's record of it says, and
which models it lists to run an agent on, and what each session the runtime keeps cost, canopy's or not.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import Field, StrictInt

#: Far above anything one model call reports, and low enough that no run's sums overflow a float or SQLite's integers.
MAX_TOKENS = 10**12
MAX_COST_USD = 10**6

#: A count of tokens a runtime reported, within `MAX_TOKENS`.
Count = Annotated[StrictInt, Field(ge=0, le=MAX_TOKENS)]

#: Printed by `canopy status` and pasted into a shell, so nothing a terminal or a shell would read as anything else.
SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,100}")

#: How many distinct tools one run's rollup keeps, and how long a tool's name may be: far more than a runtime offers,
#: and few enough that output no runtime printed cannot fill the journal. The calls of any tool past the first
#: `MAX_TOOLS` count under `OTHER_TOOLS`, which no runtime names a tool.
MAX_TOOLS = 200
MAX_TOOL_NAME = 200
OTHER_TOOLS = "(other tools)"
#: What a call that loaded a skill is counted under, before the skill's name: `skill:tracker-jira`.
SKILL_PREFIX = "skill:"
#: How many models one session's record keeps, and how long a model's name may be: far more than a run uses, and few
#: enough that a record no runtime wrote cannot fill the journal. The replies of any model past the first
#: `MAX_MODELS` count under `OTHER_MODELS`, which no runtime names a model.
MAX_MODELS = 20
MAX_MODEL_NAME = 200
OTHER_MODELS = "(other models)"
#: A message the runtime names in a session's record and on each event of a model call: the reply the call wrote, the
#: key that joins a call in the run's log to the model the record names for it. As a session id is shaped.
MESSAGE_ID_RE = SESSION_ID_RE
#: How many replies' models one session's record keeps, each by its message: far more calls than a transcript shows.
MAX_REPLIES = 10_000

#: How reading a session's models ended: they were read; the runtime keeps no session of that id, which reading again
#: would not change; or the runtime could not be asked, or said what canopy cannot read.
type ModelsRead = Literal["found", "missing", "failed"]


@dataclass(frozen=True)
class ToolUse:
    """What one tool's calls in a run put into its context.

    How many ended, how many of those in an error, and the characters of what they returned, output or error. The
    characters, not tokens: the runtime does not say which of a call's tokens a tool's result was. About four
    characters make a token, so `result_chars / 4` is an estimate, and only that.
    """

    tool: str
    calls: int
    errors: int
    result_chars: int


@dataclass(frozen=True)
class Usage:
    """What a run cost: dollars as the runtime priced them, tokens by kind, and the most one model call was sent.

    `first_call` is what its first model call was sent, from the cache or not, `first_cache_write` what that call wrote
    to the cache, and `first_cache_read` what it read from it. Each of these and the peak context is None for a run
    recorded before canopy kept it; the first call's are None too for a run that made no model call.
    """

    cost_usd: float
    input: int
    output: int
    reasoning: int
    cache_read: int
    cache_write: int
    peak_context: int | None = None
    first_call: int | None = None
    first_cache_write: int | None = None
    first_cache_read: int | None = None

    @property
    def new_tokens(self) -> int:
        """The tokens the model took in or wrote for the first time: every kind but cache reads.

        A cache read is context a call had already been sent, read again by each call after it, so summed over a run's
        calls it grows with their number and outweighs the rest; the peak context says how large that context got.
        """
        return self.input + self.cache_write + self.output + self.reasoning

    def describe(self) -> str:
        """What it cost for a person, as `$0.25, 12.3k tokens, 45.6k peak context`.

        Returns:
            The cost to the cent, the tokens (`new_tokens`), and the peak context when it is known, counts abbreviated
            with `k` or `M` from a thousand up.
        """
        peak = f", {count_text(self.peak_context)} peak context" if self.peak_context is not None else ""
        return f"${self.cost_usd:.2f}, {count_text(self.new_tokens)} tokens{peak}"

    def spent(self) -> dict[str, object]:
        """What it cost as a log line's fields.

        Returns:
            The cost in dollars, the tokens (`new_tokens`), and the peak context.
        """
        return {"cost_usd": self.cost_usd, "new_tokens": self.new_tokens, "peak_context": self.peak_context}


@dataclass(frozen=True)
class AgentOutput:
    """`text` is what a result contract is read from, and `last` the agent's final message, the end of `text`.

    `session_id` and `usage` are None when nothing reported them; `tools` is empty when no tool call was printed.
    """

    text: str
    last: str
    session_id: str | None = None
    usage: Usage | None = None
    tools: tuple[ToolUse, ...] = ()
    #: Each distinct error the runtime reported in the session, on one line, in the order it reported them.
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class Call:
    """One model call, as the runtime reported it: what it cost, and its tokens by kind."""

    cost_usd: float
    input: int
    output: int
    reasoning: int
    cache_read: int
    cache_write: int

    @property
    def sent(self) -> int:
        """What the call was sent: its input, from the cache or not."""
        return self.input + self.cache_read + self.cache_write


@dataclass(frozen=True)
class ModelUse:
    """What one model did in a session: its replies, and what they cost."""

    #: The model, as `provider/model`, printable, with no space, and at most `MAX_MODEL_NAME` characters.
    model: str
    #: How many of the session's replies it wrote.
    replies: int
    #: What those cost, in US dollars, as the runtime priced them.
    cost_usd: float


@dataclass(frozen=True)
class SessionModels:
    """Which models served a session, the most costly first, and how reading it ended."""

    outcome: ModelsRead
    #: Empty unless `found`, and for a session that made no model call.
    models: Sequence[ModelUse] = ()
    #: Why it `failed`, in canopy's words, never what the runtime printed.
    error: str | None = None
    #: The model that wrote each reply, as `models` names it, by the reply's message (`MESSAGE_ID_RE`), in order, at
    #: most `MAX_REPLIES`; empty unless more than one model wrote the session's replies, since one names them all.
    replies: Mapping[str, str] = field(default_factory=dict)


#: Where a read of the runtime's sessions stopped, to start the next after: the last session's update, in
#: milliseconds since the epoch, and its id. Sessions are read in that order, so one updated since is read again.
type SessionCursor = tuple[int, str]
#: How reading the runtime's sessions ended: read; the runtime has kept none yet, which reading again may change; or
#: its record could not be read.
type SessionsRead = Literal["found", "missing", "failed"]
#: How many sessions one read returns at most: a page, so a long history is read a page at a time.
MAX_SESSIONS = 500
#: How long a session's directory may be, as the record keeps it; a longer one is cut.
MAX_DIRECTORY = 4096


@dataclass(frozen=True)
class SessionSpend:
    """What one session the runtime keeps cost, whoever ran it: canopy, the operator, or a session it ran for."""

    session_id: str
    #: The session it ran for, as a subagent; None for a session of its own.
    parent_id: str | None
    #: Where it ran, printable, at most `MAX_DIRECTORY` characters.
    directory: str
    #: When it was made and last updated, in milliseconds since the epoch.
    created_ms: int
    updated_ms: int
    #: What its replies cost, in US dollars, as the runtime priced them, and their tokens by kind.
    cost_usd: float
    input: int
    output: int
    reasoning: int
    cache_read: int
    cache_write: int
    #: Each model's replies and their cost, the most costly first, at most `MAX_MODELS`.
    models: Sequence[ModelUse] = ()


@dataclass(frozen=True)
class SessionPage:
    """The runtime's sessions updated after a cursor, in the order of their update, and how reading them ended."""

    outcome: SessionsRead
    #: At most `MAX_SESSIONS`, and the limit the read was given; empty unless `found`.
    sessions: Sequence[SessionSpend] = ()
    #: Where the next read starts: after the last session read, any skipped among them; None when none was read.
    cursor: SessionCursor | None = None
    #: How many sessions the read passed over as ones canopy cannot read.
    skipped: int = 0
    #: Why it `failed`, in canopy's words, never what the runtime wrote.
    error: str | None = None


@dataclass(frozen=True)
class ModelList:
    """The models the runtime lists to run an agent on, the list it looks a run's model up in, or why it listed none."""

    #: Each model, as `provider/model`; empty when the list could not be read, and when the runtime lists none.
    models: AbstractSet[str] = frozenset()
    #: The variants each model lists, by model, when they were asked for; a model with none maps to an empty set.
    variants: Mapping[str, AbstractSet[str]] = field(default_factory=dict)
    #: Why the list could not be read, in canopy's words, never what the runtime printed; None when it was read.
    error: str | None = None


@dataclass(frozen=True)
class Printed:
    """What one line a running agent printed was, of what a running run's row records (`canopy.runtime.watch`)."""

    #: The line ended a model call, so what the run has spent may have changed.
    ended_call: bool
    #: The tool call the line ended: its tool, and what it did, on one line each.
    did: tuple[str, str] | None


def session_id(value: object) -> str | None:
    """Return `value` if it is a session id canopy prints (`SESSION_ID_RE`), else None."""
    return value if isinstance(value, str) and SESSION_ID_RE.fullmatch(value) else None


def model_uses(replies: Iterable[tuple[str, int, float]]) -> tuple[ModelUse, ...]:
    """Each model's replies and their cost, from rows of a model's name, its replies, and their cost.

    A name is kept printable, with no space, cut to `MAX_MODEL_NAME`, or `?` when nothing is left; past `MAX_MODELS`
    models, a new one counts under `OTHER_MODELS`.

    Returns:
        The models, the most costly first.
    """
    found: dict[str, ModelUse] = {}
    for model, count, cost in replies:
        name = "".join(c for c in model if c.isprintable() and not c.isspace())[:MAX_MODEL_NAME] or "?"
        if name not in found and len(found) >= MAX_MODELS:
            name = OTHER_MODELS
        was = found.get(name, ModelUse(name, 0, 0.0))
        found[name] = ModelUse(name, was.replies + count, was.cost_usd + cost)
    return tuple(sorted(found.values(), key=lambda m: (-m.cost_usd, m.model)))


def total(calls: Sequence[Call]) -> Usage:
    """What a run's model calls cost together.

    Returns:
        Their summed cost and tokens, the most one call was sent as the peak context, and what the first call was sent,
        wrote to the cache, and read from it; those three None when there was no call.
    """
    first = calls[0] if calls else None
    return Usage(
        cost_usd=sum(c.cost_usd for c in calls),
        input=sum(c.input for c in calls),
        output=sum(c.output for c in calls),
        reasoning=sum(c.reasoning for c in calls),
        cache_read=sum(c.cache_read for c in calls),
        cache_write=sum(c.cache_write for c in calls),
        peak_context=max((c.sent for c in calls), default=0),
        first_call=first.sent if first is not None else None,
        first_cache_write=first.cache_write if first is not None else None,
        first_cache_read=first.cache_read if first is not None else None,
    )


class Tools:
    """A run's tool calls rolled up by tool as they end, within `MAX_TOOLS` tools whose names are `MAX_TOOL_NAME`."""

    def __init__(self) -> None:
        """Start with no tool called."""
        self._tools: dict[str, ToolUse] = {}

    def add(self, tool: str, *, error: bool, said: str | None) -> None:
        """Count one call of `tool` that ended, in an error if `error`, having returned `said`, its output or error.

        The tool's name is kept as the runtime gave it but for control characters, on one line and cut to
        `MAX_TOOL_NAME`, or `?` when nothing is left; past `MAX_TOOLS` tools, a new one counts under `OTHER_TOOLS`.
        """
        name = " ".join("".join(c for c in tool if c.isprintable()).split())[:MAX_TOOL_NAME] or "?"
        if name not in self._tools and len(self._tools) >= MAX_TOOLS:
            name = OTHER_TOOLS
        was = self._tools.get(name, ToolUse(name, 0, 0, 0))
        self._tools[name] = ToolUse(
            tool=name,
            calls=was.calls + 1,
            errors=was.errors + int(error),
            result_chars=was.result_chars + len(said or ""),
        )

    @property
    def rolled_up(self) -> tuple[ToolUse, ...]:
        """The calls so far by tool, in the order each tool was first called."""
        return tuple(self._tools.values())


def count_text(n: int) -> str:
    """A count for a person, abbreviated from a thousand up: `950`, `12.3k`, `4.5M`.

    Returns:
        The count, with one decimal and `k` or `M` from a thousand up.
    """
    for size, suffix in ((1_000_000, "M"), (1_000, "k")):
        if n >= size:
            return f"{n / size:.1f}{suffix}"
    return str(n)
