"""The API's types for a run's log or a tick's output (DESIGN §22): its session's transcript, and the file's end.

Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model


class TranscriptText(Model):
    """A finished piece of the agent's text, or of its reasoning."""

    kind: Literal["text"] = "text"
    """What the entry is."""
    at: datetime | None = None
    """When the runtime reported it, if it said."""
    text: str
    """The text: untrusted."""
    reasoning: bool = False
    """Whether it is the model's reasoning rather than its answer."""
    cut: bool = False
    """Cut at the transcript's bound for one text."""
    call: int | None = None
    """The model call it came from, counted from 1, or None before the runtime started the first."""


class TranscriptTool(Model):
    """One tool call, once it ended: its input as indented JSON, and its output, or its error when `error`."""

    kind: Literal["tool"] = "tool"
    """What the entry is."""
    at: datetime | None = None
    """When the runtime reported it, if it said."""
    tool: str
    """The tool's name."""
    status: Literal["completed", "error"]
    """How the call ended."""
    title: str | None = None
    """The runtime's one-line description of the call, such as the command's purpose or the file's path."""
    input: str
    """Its input, as indented JSON: untrusted."""
    output: str
    """Its output, or its error: untrusted."""
    duration_ms: int | None = None
    """How long it took, in milliseconds, if the runtime said."""
    cut: bool = False
    """Its input or output was cut at the transcript's bound for one."""
    call: int | None = None
    """The model call it came from, counted from 1, or None before the runtime started the first."""


class TranscriptTokens(Model):
    """One model call's tokens by kind, as the runtime counted them."""

    input: int
    """Input tokens."""
    output: int
    """Output tokens."""
    reasoning: int
    """Reasoning tokens."""
    cache_read: int
    """Input tokens read from the cache."""
    cache_write: int
    """Input tokens written to the cache."""


class TranscriptStep(Model):
    """One model call ended: why, and what it cost, when the runtime said."""

    kind: Literal["step"] = "step"
    """What the entry is."""
    at: datetime | None = None
    """When the runtime reported it, if it said."""
    reason: str | None = None
    """Why the call ended, in the runtime's word."""
    cost_usd: float | None = None
    """What it cost, in US dollars."""
    tokens: int | None = None
    """Every kind of token together."""
    split: TranscriptTokens | None = None
    """The tokens, each kind apart."""
    call: int | None = None
    """The model call it came from, counted from 1, or None before the runtime started the first."""


class TranscriptError(Model):
    """The runtime reported an error in the session."""

    kind: Literal["error"] = "error"
    """What the entry is."""
    at: datetime | None = None
    """When the runtime reported it, if it said."""
    name: str
    """The error's name, as the runtime gave it."""
    message: str
    """The error's message: untrusted."""
    call: int | None = None
    """The model call it came from, counted from 1, or None before the runtime started the first."""


type TranscriptEntry = Annotated[
    TranscriptText | TranscriptTool | TranscriptStep | TranscriptError,
    Field(discriminator="kind", description="One entry of a transcript, told apart by its `kind`."),
]
type TranscriptStatus = Annotated[
    Literal["read", "no_session", "no_log"],
    Field(
        description="`read`: the log was read, whether or not it held any of the session's events yet (a running "
        "run's reach it when the run ends). `no_session`: the runtime reported no session (a template without "
        "`--format json`). `no_log`: the log is missing, a symlink, or not a regular file.",
    ),
]


class TranscriptPrompt(Model):
    """The message canopy gave the runtime to start the session (DESIGN §22).

    The first model call's input, but for the agent's definition and the runtime's own system prompt and tools, which
    nothing records.
    """

    text: str
    """The prompt as canopy rendered it, control characters dropped: untrusted in part, since it quotes tickets,
    comments, and PRs."""
    truncated: bool = False
    """It holds more than the bound read."""


class Transcript(Model):
    """What a run's log or a tick's output holds of its session, read back from the events as printed (DESIGN §22).

    Agent output: untrusted, rendered as text, and bounded. `truncated` says a bound left something out; `unreadable`
    counts events that did not validate.
    """

    status: TranscriptStatus
    """Whether the log was read, and if not, why."""
    session_id: str | None = None
    """The runtime's session, if it reported one."""
    entries: list[TranscriptEntry] = []
    """The session's events, in order."""
    truncated: bool = False
    """A bound left something out."""
    unreadable: int = 0
    """How many events did not validate."""
    prompt: TranscriptPrompt | None = None
    """The session's prompt, kept beside the log, if canopy kept one and it could be read."""
    removed_after_days: int | None = None
    """Retention removed its log and prompt, this many days after it ended (DESIGN §26); None when it did not."""


class RawOutput(Model):
    """The end of a tick's output or a run's log as written, the lines its transcript leaves out included (DESIGN §22).

    A tick's is its overseer's stdout, a `--- stderr ---` line, and its stderr; a run's, its setup commands' output and
    its worker's stdout, stderr, and exit, each under a `--- ... ---` line canopy writes. Agent output: untrusted,
    rendered as text, its control characters dropped. `truncated` says the file holds more than its last `text`, which
    starts at a whole line; `size` is the whole file's, in bytes.
    """

    status: Literal["read", "no_output"]
    """`read`: the file was read; a running tick's or run's holds what it has printed so far. `no_output`: it is
    missing (none kept, or its agent has not started), a symlink, or not a regular file."""
    text: str = ""
    """The end of the file, starting at a whole line."""
    size: int = 0
    """The whole file's size, in bytes."""
    truncated: bool = False
    """The file holds more than `text`."""
    removed_after_days: int | None = None
    """Retention removed the file, this many days after it ended (DESIGN §26); None when it did not."""
