"""OpenCode's JSON events (DESIGN §13), read into what a run reports (`canopy.runtime.report`).

A command template either prints the agent's text on stdout, or, with OpenCode's `--format json`, prints one JSON event
per line. canopy reads three kinds of event and one field of every event, each validated (D026):

- `text`: a finished piece of the agent's text, in `part.text`. Joined one per line they are what stdout holds without
  `--format json`, so every result contract reads the same either way. The last one is the agent's final message.
- `step_finish`: one model call's `part.cost`, in dollars, and `part.tokens`. Summed, they are what the run cost; the
  most one call was sent is the run's peak context. The first call's is kept apart: what it was sent, less the
  prompt, is the run's fixed overhead, and its cache write says whether that came from the cache.
- `tool_use`: one tool call, printed once it ended, `completed` or `error`. Rolled up by tool, the calls, the errors,
  and the characters of what they returned are what each tool put into the run's context.
- `sessionID`, on every event: the session OpenCode kept, which the operator opens with OpenCode's own tools.

Any other event, and any line that is not an event, is ignored. Output with no events at all is plain text, as from a
template without `--format json` or another runtime, and reports no session and no cost. Its final message is all of
it: plain text does not say where one message ends.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationError

from canopy.runtime.report import MAX_COST_USD, AgentOutput, Count, ToolUse, Usage

#: Printed by `canopy status` and pasted into a shell, so nothing a terminal or a shell would read as anything else.
SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,100}")

#: How many distinct tools one run's rollup keeps, and how long a tool's name may be: far more than a runtime offers,
#: and few enough that output no runtime printed cannot fill the journal. The calls of any tool past the first
#: `MAX_TOOLS` count under `OTHER_TOOLS`, which no runtime names a tool.
MAX_TOOLS = 200
MAX_TOOL_NAME = 200
OTHER_TOOLS = "(other tools)"

#: The event that ends a model call, and the one that ends a tool call.
STEP_FINISH = "step_finish"
TOOL_USE = "tool_use"


class _Text(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    text: StrictStr


class _Cache(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    read: Count
    write: Count


class _Tokens(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    input: Count
    output: Count
    reasoning: Count
    cache: _Cache


class _StepFinish(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    cost: Annotated[StrictFloat | StrictInt, Field(ge=0, le=MAX_COST_USD, allow_inf_nan=False)]
    tokens: _Tokens


class _ToolState(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    # A tool call is printed once it has ended.
    status: Literal["completed", "error"]
    output: StrictStr | None = None
    error: StrictStr | None = None


class _ToolPart(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    tool: StrictStr
    state: _ToolState


def read(stdout: str) -> AgentOutput:
    """Read an agent's stdout: plain text, or OpenCode's JSON events.

    Returns:
        `stdout` as it is, as both the text and the final message, when it holds no event. Otherwise the events' text
        parts joined by newlines, the last of them, the first valid session id, the steps' total usage, or None for
        usage when a step could not be read, and the tool calls rolled up by tool.
    """
    texts: list[str] = []
    tally = Tally()
    events = 0
    for line in stdout.splitlines():
        event = parse_event(line)
        if event is None:
            continue
        events += 1
        tally.add(event)
        if event["type"] == "text":
            # A text part canopy cannot read is left out, which at worst makes the result line invalid.
            with contextlib.suppress(ValidationError):
                texts.append(_Text.model_validate(event.get("part")).text)
    if not events:
        return AgentOutput(stdout, stdout)
    last = texts[-1] if texts else ""
    return AgentOutput("\n".join(texts), last, tally.session_id, tally.usage, tally.tools)


class Tally:
    """The session, usage, and tools of an agent's events, added one at a time as it prints them, as `read` reports.

    So a running agent's session and what it has spent so far are what `read` would say of what it printed so far.
    """

    def __init__(self) -> None:
        """Start with no event: no session, nothing spent, and no tool called."""
        self.session_id: str | None = None
        self._steps: list[_StepFinish] = []
        self._complete = True
        self._tools: dict[str, ToolUse] = {}

    def add(self, event: Mapping[str, object]) -> None:
        """Count `event`: its session, and its model call's cost or its tool call, if it is either.

        The session is the first valid one an event names.
        """
        self.session_id = self.session_id or session_of(event)
        if event["type"] == TOOL_USE:
            self._add_tool(event)
            return
        if event["type"] != STEP_FINISH:
            return
        try:
            self._steps.append(_StepFinish.model_validate(event.get("part")))
        except ValidationError:
            # A step canopy cannot read makes the total wrong, so the run reports no cost rather than too little.
            self._complete = False

    @property
    def usage(self) -> Usage | None:
        """The steps' total usage so far, or None when a step could not be read."""
        return _total(self._steps) if self._complete else None

    @property
    def tools(self) -> tuple[ToolUse, ...]:
        """The tool calls so far, rolled up by tool, in the order each tool was first called."""
        return tuple(self._tools.values())

    # A call canopy cannot read is left out: it says nothing of which tool it was, or what it returned.
    def _add_tool(self, event: Mapping[str, object]) -> None:
        try:
            part = _ToolPart.model_validate(event.get("part"))
        except ValidationError:
            return
        name = _tool_name(part.tool)
        if name not in self._tools and len(self._tools) >= MAX_TOOLS:
            name = OTHER_TOOLS
        state = part.state
        said = state.output if state.status == "completed" else state.error
        was = self._tools.get(name, ToolUse(name, 0, 0, 0))
        self._tools[name] = ToolUse(
            tool=name,
            calls=was.calls + 1,
            errors=was.errors + int(state.status == "error"),
            result_chars=was.result_chars + len(said or ""),
        )


def session_of(event: Mapping[str, object]) -> str | None:
    """Return the session `event` names, or None when its `sessionID` is not one canopy prints (`SESSION_ID_RE`)."""
    found = event["sessionID"]
    return found if isinstance(found, str) and SESSION_ID_RE.fullmatch(found) else None


def parse_event(line: str) -> dict[str, object] | None:
    """Return `line` as an event: a JSON object with a string `type` and a `sessionID`. None if it is not one."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        parsed: object = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    event = cast("dict[str, object]", parsed)
    if not isinstance(event.get("type"), str) or "sessionID" not in event:
        return None
    return event


def _total(steps: Sequence[_StepFinish]) -> Usage:
    first = steps[0].tokens if steps else None
    return Usage(
        cost_usd=sum(float(s.cost) for s in steps),
        input=sum(s.tokens.input for s in steps),
        output=sum(s.tokens.output for s in steps),
        reasoning=sum(s.tokens.reasoning for s in steps),
        cache_read=sum(s.tokens.cache.read for s in steps),
        cache_write=sum(s.tokens.cache.write for s in steps),
        peak_context=max((_sent(s.tokens) for s in steps), default=0),
        first_call=_sent(first) if first is not None else None,
        first_cache_write=first.cache.write if first is not None else None,
    )


# A tool's name on one line, as the runtime gave it but for control characters, cut to `MAX_TOOL_NAME`; `?` for one
# with nothing left.
def _tool_name(name: str) -> str:
    return " ".join("".join(c for c in name if c.isprintable()).split())[:MAX_TOOL_NAME] or "?"


# What one model call was sent: its input, from the cache or not.
def _sent(tokens: _Tokens) -> int:
    return tokens.input + tokens.cache.read + tokens.cache.write
