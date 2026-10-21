"""OpenCode's JSON events (DESIGN §13), read into what a run reports (`canopy.runtime.report`).

A command template either prints the agent's text on stdout, or, with OpenCode's `--format json`, prints one JSON event
per line. canopy reads four kinds of event and one field of every event, each validated (D026):

- `text`: a finished piece of the agent's text, in `part.text`. Joined one per line they are what stdout holds without
  `--format json`, so every result contract reads the same either way. The last one is the agent's final message.
- `step_finish`: one model call's `part.cost`, in dollars, and `part.tokens`. Summed, they are what the run cost; the
  most one call was sent is the run's peak context. The first call's is kept apart: what it was sent, less the
  prompt, is the run's fixed overhead, and its cache write says whether that came from the cache.
- `tool_use`: one tool call, printed once it ended, `completed` or `error`. Rolled up by tool, the calls, the errors,
  and the characters of what they returned are what each tool put into the run's context. A call of the `skill` tool
  is counted under the skill it loaded, `skill:<name>`, so spend says which skills an agent uses, not only that it
  used one.
- `error`: the session failed, its `error` a name and a message. Each distinct one is kept, in order: OpenCode prints
  one when it gives up after its own retries, and one for a context overflow it then compacts and goes on from, so the
  last is what ended the run and an earlier one may be its cause. OpenCode's own log has the detail of one it did not
  expect, under its `ref`.
- `sessionID`, on every event: the session OpenCode kept, which the operator opens with OpenCode's own tools.

Any other event, and any line that is not an event, is ignored. Output with no events at all is plain text, as from a
template without `--format json`, and reports no session and no cost. Its final message is all of it: plain text does
not say where one message ends.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationError

from canopy.runtime import entries, report
from canopy.runtime.opencode.definitions import MAX_SKILL_NAME, SKILL_NAME_RE
from canopy.runtime.report import MAX_COST_USD, SKILL_PREFIX, AgentOutput, Call, Count, ToolUse, Usage

#: The event that starts a model call, the one that ends it, and the one that ends a tool call.
STEP_START = "step_start"
STEP_FINISH = "step_finish"
TOOL_USE = "tool_use"
#: The event that says the session failed.
ERROR = "error"
#: OpenCode's tool that loads a skill.
SKILL_TOOL = "skill"


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
    #: What the call was given, and what the tool said of it besides its output; read only for a skill's name.
    input: object = None
    metadata: object = None


class _Named(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    name: StrictStr


class _ToolPart(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    tool: StrictStr
    state: _ToolState


class ErrorData(BaseModel):
    """What an `error` event says of the error besides its name."""

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    message: StrictStr | None = None
    #: Where OpenCode's own log has the detail, for an error it did not expect.
    ref: StrictStr | None = None


class SessionError(BaseModel):
    """An `error` event's `error`: why the session failed, as the runtime names it."""

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    name: StrictStr | None = None
    data: ErrorData | None = None

    def describe(self) -> str:
        """The error on one line, as a failure names it.

        Returns:
            `Name: message (ref)`, each part only when given, and `error` when none is.
        """
        data = self.data or ErrorData()
        said = ": ".join(part for part in (self.name, data.message) if part) or ERROR
        return entries.line(f"{said} ({data.ref})" if data.ref else said)


def read(stdout: str) -> AgentOutput:
    """Read an agent's stdout: plain text, or OpenCode's JSON events.

    Returns:
        `stdout` as it is, as both the text and the final message, when it holds no event. Otherwise the events' text
        parts joined by newlines, the last of them, the first valid session id, the steps' total usage, or None for
        usage when a step could not be read, the tool calls rolled up by tool, and the errors the runtime reported.
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
    return AgentOutput("\n".join(texts), last, tally.session_id, tally.usage, tally.tools, tally.errors)


class Tally:
    """An agent's session, usage, tools, and errors, added one event at a time as it prints them, as `read` reports.

    So a running agent's session and what it has spent so far are what `read` would say of what it printed so far.
    """

    def __init__(self) -> None:
        """Start with no event: no session, nothing spent, no tool called, and no error."""
        self.session_id: str | None = None
        self._calls: list[Call] = []
        self._errors: list[str] = []
        self._complete = True
        self._tools = report.Tools()

    def add(self, event: Mapping[str, object]) -> None:
        """Count `event`: its session, and its model call's cost, its tool call, or its error, if it is one of them.

        The session is the first valid one an event names.
        """
        self.session_id = self.session_id or report.session_id(event["sessionID"])
        if event["type"] == TOOL_USE:
            self._add_tool(event)
            return
        if event["type"] == ERROR:
            try:
                said = SessionError.model_validate(event.get("error")).describe()
            except ValidationError:
                # One canopy cannot read still says the session failed.
                said = ERROR
            if said not in self._errors:
                self._errors.append(said)
            return
        if event["type"] != STEP_FINISH:
            return
        try:
            step = _StepFinish.model_validate(event.get("part"))
        except ValidationError:
            # A step canopy cannot read makes the total wrong, so the run reports no cost rather than too little.
            self._complete = False
            return
        t = step.tokens
        self._calls.append(Call(float(step.cost), t.input, t.output, t.reasoning, t.cache.read, t.cache.write))

    @property
    def usage(self) -> Usage | None:
        """The steps' total usage so far, or None when a step could not be read."""
        return report.total(self._calls) if self._complete else None

    @property
    def errors(self) -> tuple[str, ...]:
        """Each distinct error the runtime reported so far, on one line (`SessionError.describe`), in order."""
        return tuple(self._errors)

    @property
    def tools(self) -> tuple[ToolUse, ...]:
        """The tool calls so far, rolled up by tool, in the order each tool was first called."""
        return self._tools.rolled_up

    # A call canopy cannot read is left out: it says nothing of which tool it was, or what it returned.
    def _add_tool(self, event: Mapping[str, object]) -> None:
        try:
            part = _ToolPart.model_validate(event.get("part"))
        except ValidationError:
            return
        state = part.state
        error = state.status == "error"
        tool = part.tool
        if tool == SKILL_TOOL:
            skill = _skill_name(state)
            tool = f"{SKILL_PREFIX}{skill}" if skill is not None else tool
        self._tools.add(tool, error=error, said=state.error if error else state.output)


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


def _skill_name(state: _ToolState) -> str | None:
    """The skill a `skill` call loaded: the name OpenCode found it under, else the one it was asked for.

    Returns:
        The name, or None when neither is a skill's name by OpenCode's rule, so the call counts as `skill` alone.
    """
    for said in (state.metadata, state.input):
        try:
            name = _Named.model_validate(said).name
        except ValidationError:
            continue
        if len(name) <= MAX_SKILL_NAME and SKILL_NAME_RE.fullmatch(name):
            return name
    return None
