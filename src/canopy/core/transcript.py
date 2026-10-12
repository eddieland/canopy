"""A session's transcript, read back from the events a run's log holds (DESIGN §13, §22).

A template with OpenCode's `--format json` prints one event per line, and canopy writes them, as printed, to the run's
log or the tick's output file. This reads the events of one session back, in the order they were printed, as entries
a page can show: the agent's text, its reasoning, each tool call with its input and output, each model call's cost,
and the runtime's errors. A line that is not an event, or is another session's, is left out, so stderr, a setup
command's output, and the harness's own lines never show as the agent's.

Everything here is agent output: untrusted, and unbounded until it is read. So the file is read only if it is a
regular file and not a symlink, at most `MAX_BYTES` of it; each event is validated (D026); control characters are
dropped; and each text, the transcript's entries, and their characters altogether are cut at a bound, with
`truncated` saying something was. An event of a known type that does not validate is counted in `unreadable`.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictFloat, StrictInt, StrictStr, ValidationError

from canopy.core import agent_output, conversation

if TYPE_CHECKING:
    from pathlib import Path

# How much of a log is read: far more than a long run prints, and little enough to read on each request.
MAX_BYTES = 32 * 1024 * 1024
# How many entries a transcript holds, and how many characters all of them hold together.
MAX_ENTRIES = 2000
MAX_CHARS = 2_000_000
# Each text: the agent's text or reasoning, a tool's output or error, and a tool's input as indented JSON.
MAX_TEXT = 20_000
MAX_INPUT = 5_000
# A tool's name, a call's title, a step's reason, and an error's name: one line each.
MAX_NAME = 200
# Milliseconds since the epoch, as OpenCode stamps events: up to the year 9999.
_MAX_MS = 253_402_300_799_999

Millis = Annotated[StrictInt, Field(ge=0, le=_MAX_MS)]


class _Part(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class _Text(_Part):
    text: StrictStr


class _Time(_Part):
    start: Millis | None = None
    end: Millis | None = None


class _ToolState(_Part):
    # A tool call is printed once it has ended: `completed`, or `error`.
    status: Literal["completed", "error"]
    input: dict[str, JsonValue] = {}
    output: StrictStr | None = None
    error: StrictStr | None = None
    title: StrictStr | None = None
    time: _Time | None = None


class _Tool(_Part):
    tool: StrictStr
    state: _ToolState


class _Cache(_Part):
    read: agent_output.Count = 0
    write: agent_output.Count = 0


class _Tokens(_Part):
    input: agent_output.Count = 0
    output: agent_output.Count = 0
    reasoning: agent_output.Count = 0
    cache: _Cache = _Cache()


class _Step(_Part):
    reason: StrictStr | None = None
    cost: Annotated[StrictFloat | StrictInt, Field(ge=0, le=agent_output.MAX_COST_USD, allow_inf_nan=False)] | None = (
        None
    )
    tokens: _Tokens | None = None


class _ErrorData(_Part):
    message: StrictStr | None = None


class _Error(_Part):
    name: StrictStr | None = None
    data: _ErrorData | None = None


@dataclass(frozen=True)
class Text:
    """A finished piece of the agent's text, or of its reasoning when `reasoning`."""

    at: datetime | None
    text: str
    reasoning: bool = False
    cut: bool = False


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


@dataclass(frozen=True)
class Step:
    """One model call ended: why, and what it cost, when the runtime said."""

    at: datetime | None
    reason: str | None
    cost_usd: float | None
    tokens: int | None


@dataclass(frozen=True)
class Error:
    """The runtime reported an error in the session."""

    at: datetime | None
    name: str
    message: str


type Entry = Text | ToolCall | Step | Error


@dataclass(frozen=True)
class Transcript:
    """What a log holds of one session. `truncated` when a bound cut anything; `unreadable` events did not validate."""

    entries: list[Entry] = field(default_factory=list[Entry])
    truncated: bool = False
    unreadable: int = 0


def read(path: Path, session_id: str) -> Transcript | None:
    """Read `session_id`'s events from the log at `path`. None when it is missing, a symlink, or not a regular file."""
    try:
        # Non-blocking, so a FIFO in the log's place cannot hold the request open; it is refused below.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    with os.fdopen(fd, "rb") as f:
        data = f.read(MAX_BYTES + 1)
    truncated = len(data) > MAX_BYTES
    if truncated:
        # The last line read may be cut short; it is not an event then.
        data = data[: data.rfind(b"\n", 0, MAX_BYTES) + 1]
    return _parse(data.decode("utf-8", errors="replace").splitlines(), session_id, truncated=truncated)


def _parse(lines: list[str], session_id: str, *, truncated: bool) -> Transcript:
    entries: list[Entry] = []
    chars = 0
    unreadable = 0
    for line in lines:
        event = agent_output.parse_event(line)
        if event is None or event["sessionID"] != session_id:
            continue
        try:
            entry = _entry(event)
        except ValidationError:
            unreadable += 1
            continue
        if entry is None:
            continue
        size = _size(entry)
        if len(entries) == MAX_ENTRIES or chars + size > MAX_CHARS:
            truncated = True
            break
        entries.append(entry)
        chars += size
        truncated = truncated or (isinstance(entry, Text | ToolCall) and entry.cut)
    return Transcript(entries, truncated, unreadable)


def _entry(event: dict[str, object]) -> Entry | None:
    """One event as an entry, or None for a type a transcript leaves out (`step_start`, and any it does not know)."""
    kind = event["type"]
    at = _at(event.get("timestamp"))
    part = event.get("part")
    if kind in {"text", "reasoning"}:
        text, cut = _cut(_Text.model_validate(part).text, MAX_TEXT)
        return Text(at, text, reasoning=kind == "reasoning", cut=cut)
    if kind == "tool_use":
        tool = _Tool.model_validate(part)
        state = tool.state
        shown, input_cut = _cut(json.dumps(state.input, indent=2, ensure_ascii=False), MAX_INPUT)
        said = state.output if state.status == "completed" else state.error
        output, output_cut = _cut(said or "", MAX_TEXT)
        time = state.time
        duration = time.end - time.start if time and time.start is not None and time.end is not None else None
        return ToolCall(
            at=at,
            tool=_line(tool.tool),
            status=state.status,
            title=_line(state.title or "") or None,
            input=shown,
            output=output,
            duration_ms=duration if duration is not None and duration >= 0 else None,
            cut=input_cut or output_cut,
        )
    if kind == "step_finish":
        step = _Step.model_validate(part)
        t = step.tokens
        tokens = t.input + t.output + t.reasoning + t.cache.read + t.cache.write if t is not None else None
        cost = float(step.cost) if step.cost is not None else None
        return Step(at, _line(step.reason or "") or None, cost, tokens)
    if kind == "error":
        error = _Error.model_validate(event.get("error"))
        message = error.data.message if error.data is not None and error.data.message else ""
        return Error(at, _line(error.name or "error"), _cut(message, MAX_TEXT)[0])
    return None


def _at(value: object) -> datetime | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= _MAX_MS:
        return datetime.fromtimestamp(value / 1000, UTC)
    return None


def _cut(text: str, limit: int) -> tuple[str, bool]:
    """`text` without control characters, line breaks kept, and cut to `limit` characters; and whether it was cut."""
    shown = conversation.printable(text)
    return (shown[:limit], True) if len(shown) > limit else (shown, False)


def _line(text: str) -> str:
    return " ".join(_cut(text, MAX_NAME)[0].split())


def _size(entry: Entry) -> int:
    match entry:
        case Text():
            return len(entry.text)
        case ToolCall():
            return len(entry.input) + len(entry.output) + len(entry.title or "")
        case Step():
            return 0
        case Error():
            return len(entry.message)
