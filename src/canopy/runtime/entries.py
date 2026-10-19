"""A session's transcript as a page shows it, whatever runtime printed it (DESIGN §13, §22): its entries and bounds.

The runtime's implementation reads its own events into these (`canopy.runtime.transcript`), cutting each text with
`cut` and `line`, so that what a page shows of agent output, which is untrusted, is printable and bounded the same way
whatever printed it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from canopy.infra.text import printable

if TYPE_CHECKING:
    from datetime import datetime

#: Each text: the agent's text or reasoning, a tool's output or error, and a tool's input as indented JSON.
MAX_TEXT = 20_000
MAX_INPUT = 5_000
#: A tool's name, a call's title, a step's reason, and an error's name: one line each.
MAX_NAME = 200


@dataclass(frozen=True)
class Text:
    """A finished piece of the agent's text, or of its reasoning when `reasoning`.

    Every entry's `call` is the model call it came from, counted from 1 as the runtime started them; None before the
    first.
    """

    at: datetime | None
    text: str
    reasoning: bool = False
    cut: bool = False
    call: int | None = None


@dataclass(frozen=True)
class ToolCall:
    """One tool call, printed once it ended: its input as indented JSON, and its output or its error."""

    at: datetime | None
    tool: str
    status: Literal["completed", "error"]
    title: str | None
    input: str
    output: str
    duration_ms: int | None
    cut: bool = False
    call: int | None = None


@dataclass(frozen=True)
class Tokens:
    """One model call's tokens by kind, as the runtime counted them."""

    input: int
    output: int
    reasoning: int
    cache_read: int
    cache_write: int

    @property
    def total(self) -> int:
        """Every kind together, as the run's spend counts them."""
        return self.input + self.output + self.reasoning + self.cache_read + self.cache_write


@dataclass(frozen=True)
class Step:
    """One model call ended: why, and what it cost and its tokens by kind, when the runtime said."""

    at: datetime | None
    reason: str | None
    cost_usd: float | None
    tokens: Tokens | None
    call: int | None = None


@dataclass(frozen=True)
class Error:
    """The runtime reported an error in the session."""

    at: datetime | None
    name: str
    message: str
    call: int | None = None


type Entry = Text | ToolCall | Step | Error


def cut(text: str, limit: int) -> tuple[str, bool]:
    """`text` without control characters, line breaks kept, and cut to `limit` characters; and whether it was cut.

    Returns:
        The printable text, at most `limit` characters, and True if it was longer.
    """
    shown = printable(text)
    return (shown[:limit], True) if len(shown) > limit else (shown, False)


def line(text: str) -> str:
    """Return `text` as one line, as a tool's name or a title is shown: printable, `MAX_NAME` long, spaces collapsed."""
    return " ".join(cut(text, MAX_NAME)[0].split())


def size(entry: Entry) -> int:
    """Return the characters `entry` holds, as a transcript's bound on all of them counts them."""
    match entry:
        case Text():
            return len(entry.text)
        case ToolCall():
            return len(entry.input) + len(entry.output) + len(entry.title or "")
        case Step():
            return 0
        case Error():
            return len(entry.message)
