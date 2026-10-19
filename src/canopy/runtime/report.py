"""What an agent run reports, whatever runtime ran it (DESIGN §13): its text, session, cost, and tool calls.

The harness reads these and nothing else of a run's output. `canopy.runtime.events` makes them from what the runtime
printed; a runtime that prints no events reports text alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from pydantic import Field, StrictInt

#: Far above anything one model call reports, and low enough that no run's sums overflow a float or SQLite's integers.
MAX_TOKENS = 10**12
MAX_COST_USD = 10**6

#: A count of tokens a runtime reported, within `MAX_TOKENS`.
Count = Annotated[StrictInt, Field(ge=0, le=MAX_TOKENS)]


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

    `first_call` is what its first model call was sent, from the cache or not, and `first_cache_write` what that call
    wrote to the cache. Each of the three is None for a run recorded before canopy kept it; the first call's are None
    too for a run that made no model call.
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


def count_text(n: int) -> str:
    """A count for a person, abbreviated from a thousand up: `950`, `12.3k`, `4.5M`.

    Returns:
        The count, with one decimal and `k` or `M` from a thousand up.
    """
    for size, suffix in ((1_000_000, "M"), (1_000, "k")):
        if n >= size:
            return f"{n / size:.1f}{suffix}"
    return str(n)
