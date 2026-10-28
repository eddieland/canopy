"""A session's transcript, read from OpenCode 2's JSON events (DESIGN §13, §22), as `canopy.runtime.entries`.

A template with `--format json` prints one event per line, and canopy writes them, as printed, to the run's log or the
tick's output file. This reads the events of one session, in the order they were printed, as entries: the agent's text,
its reasoning, each tool call with its input and output, each model call's cost, and the runtime's errors, each
numbered by the `step_start` event of the model call it came from. A line that is not an event, or is another
session's, is left out, so stderr, a setup command's output, and the harness's own lines never show as the agent's.
Each event is validated (D026), and each text cut to its bound (`canopy.runtime.entries`).

OpenCode 2 titles a tool call with the tool's own name, so a call's title is made here from its input instead: the
command a shell ran, else the path, pattern, address, or skill it was given. The last model call's cost is missing, as
`canopy.runtime.opencode2.events` says why.

`canopy.runtime.transcript` reads the file and bounds the transcript as a whole.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictFloat, StrictInt, StrictStr, ValidationError

from canopy.runtime import entries
from canopy.runtime.entries import MAX_INPUT, MAX_TEXT, Entry, Error, Step, Text, Tokens, ToolCall
from canopy.runtime.opencode2 import events
from canopy.runtime.report import MAX_COST_USD, Count

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

# Milliseconds since the epoch, as OpenCode stamps events: up to the year 9999.
_MAX_MS: Final = 253_402_300_799_999
# The fields of a tool call's input that say what it did, in the order a title takes the first that is a string: a
# shell's command, a file tool's path, a search's pattern, a fetch's address, a search's query, a skill's id.
_SAID_BY: Final = ("command", "path", "pattern", "url", "query", "id")

Millis = Annotated[StrictInt, Field(ge=0, le=_MAX_MS)]


class _Part(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)


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
    time: _Time | None = None


class _Tool(_Part):
    tool: StrictStr
    state: _ToolState


class _Cache(_Part):
    read: Count = 0
    write: Count = 0


class _Tokens(_Part):
    input: Count = 0
    output: Count = 0
    reasoning: Count = 0
    cache: _Cache = Field(default_factory=_Cache)


class _Step(_Part):
    reason: StrictStr | None = None
    cost: Annotated[StrictFloat | StrictInt, Field(ge=0, le=MAX_COST_USD, allow_inf_nan=False)] | None = None
    tokens: _Tokens | None = None


def read(lines: Iterable[str], session_id: str) -> Iterator[Entry | None]:
    """Read `session_id`'s events from `lines`, in order, as entries, each with the model call it came from.

    Yields:
        An entry for each event of the session a transcript shows, and None for each one of a known type that does not
        validate. Events of other types, and lines that are no event of the session, yield nothing.
    """
    call = 0
    for line in lines:
        event = events.parse_event(line)
        if event is None or event["sessionID"] != session_id:
            continue
        if event["type"] == events.STEP_START:
            call += 1
            continue
        try:
            entry = _entry(event)
        except ValidationError:
            yield None
            continue
        if entry is not None:
            yield dataclasses.replace(entry, call=call or None)


def did(event: Mapping[str, object]) -> tuple[str, str] | None:
    """What a `tool_use` event's call did, on one line, for a running run's row (DESIGN §8): its tool, and what it did.

    What it did is the title made from its input (`_said`), or empty. Each is one line as a transcript's tool and title
    are (`entries.line`).

    Returns:
        The tool's name and what it did, or None when `event` is not a `tool_use` event that validates.
    """
    if event["type"] != events.TOOL_USE:
        return None
    try:
        tool = _Tool.model_validate(event.get("part"))
    except ValidationError:
        return None
    return entries.line(tool.tool), entries.line(_said(tool.state.input))


def _entry(event: Mapping[str, object]) -> Entry | None:
    """One event as an entry, or None for a type a transcript leaves out (any it does not know).

    Returns:
        A `Text`, `ToolCall`, `Step`, or `Error` for the event's type, its text cut to the bounds; or None.
    """
    kind = event["type"]
    at = _at(event.get("timestamp"))
    part = event.get("part")
    if kind in {"text", "reasoning"}:
        said = _Text.model_validate(part).text
        # A provider's redacted thinking arrives as reasoning with no text: there is nothing to show.
        if kind == "reasoning" and not said.strip():
            return None
        text, cut = entries.cut(said, MAX_TEXT)
        return Text(at, text, reasoning=kind == "reasoning", cut=cut)
    if kind == events.TOOL_USE:
        tool = _Tool.model_validate(part)
        state = tool.state
        shown, input_cut = entries.cut(json.dumps(state.input, indent=2, ensure_ascii=False), MAX_INPUT)
        said = state.output if state.status == "completed" else state.error
        output, output_cut = entries.cut(said or "", MAX_TEXT)
        time = state.time
        duration = time.end - time.start if time and time.start is not None and time.end is not None else None
        return ToolCall(
            at=at,
            tool=entries.line(tool.tool),
            status=state.status,
            title=entries.line(_said(state.input)) or None,
            input=shown,
            output=output,
            duration_ms=duration if duration is not None and duration >= 0 else None,
            cut=input_cut or output_cut,
        )
    if kind == events.STEP_FINISH:
        step = _Step.model_validate(part)
        t = step.tokens
        tokens = Tokens(t.input, t.output, t.reasoning, t.cache.read, t.cache.write) if t is not None else None
        cost = float(step.cost) if step.cost is not None else None
        return Step(at, entries.line(step.reason or "") or None, cost, tokens)
    if kind == events.ERROR:
        error = events.SessionError.model_validate(event.get("error"))
        return Error(at, entries.line(error.type or "error"), entries.cut(error.message or "", MAX_TEXT)[0])
    return None


# The first of a call's input fields that says what it did, or empty when none does.
def _said(given: Mapping[str, JsonValue]) -> str:
    return next((value for key in _SAID_BY if isinstance(value := given.get(key), str) and value.strip()), "")


def _at(value: object) -> datetime | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= _MAX_MS:
        return datetime.fromtimestamp(value / 1000, UTC)
    return None
