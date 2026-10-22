"""OpenCode 2's JSON events (DESIGN §13), read into what a run reports (`canopy.runtime.report`).

A command template either prints the agent's text on stdout, or, with `opencode run --format json`, prints one JSON
event per line. OpenCode 2 projects its own session events onto the event lines OpenCode 1 printed, so the kinds and
most fields are 1's; canopy reads four kinds of event and one field of every event, each validated (D026):

- `text`: a finished piece of the agent's text, in `part.text`. Joined one per line they are what stdout holds without
  `--format json`, so every result contract reads the same either way. The last one is the agent's final message.
- `step_finish`: one model call's `part.cost`, in dollars, and `part.tokens`. Summed, they are what the run cost; the
  most one call was sent is the run's peak context. The first call's is kept apart: what it was sent, less the
  prompt, is the run's fixed overhead, and its cache write says whether that came from the cache.
- `tool_use`: one tool call, printed once it ended, `completed` or `error`. Rolled up by tool, the calls, the errors,
  and the characters of what they returned are what each tool put into the run's context. A call of the `skill` tool
  is counted under the skill it loaded, `skill:<name>`.
- `error`: the session failed, its `error` a type and a message (OpenCode 1's was a name and `data`). Each distinct one
  is kept, in order; the last is what ended the run.
- `sessionID`, on every event: the session OpenCode kept, which the operator opens with OpenCode's own tools.

OpenCode 2.1.2 prints a model call's `step_finish` only while the session is still running: the last call's is lost to
a race between the run's end and its event stream, and in every run measured it was. So a `step_start` that no
`step_finish` follows is a call canopy could not read, and the run reports no cost rather than too little, as for any
step it cannot read. A run that ended in an error is the exception: its last call failed, and the runtime printed the
error in its place. The session's own record has every call (`canopy.runtime.opencode2.session_models`).

Any other event, and any line that is not an event, is ignored. Output with no events at all is plain text, as from a
template without `--format json`, and reports no session and no cost.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationError

from canopy.runtime import entries, report
from canopy.runtime.opencode2.definitions import MAX_SKILL_NAME, SKILL_NAME_RE
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
    #: What the call was given, and what the runtime said of it besides its output; read only for a skill's name.
    input: object = None
    metadata: object = None


class _Named(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    name: StrictStr


class _Skill(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    #: The skill tool's own metadata, which OpenCode 2 nests under the call's.
    metadata: _Named | None = None


class _Asked(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    id: StrictStr


class _ToolPart(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    tool: StrictStr
    state: _ToolState


class SessionError(BaseModel):
    """An `error` event's `error`: why the session failed, as the runtime names it.

    Not the provider's response, which OpenCode 2 passes on whole: its message says what canopy shows of it.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    #: What kind of failure it was, such as `provider.auth` or `aborted`.
    type: StrictStr | None = None
    message: StrictStr | None = None

    def describe(self) -> str:
        """The error on one line, as a failure names it.

        Returns:
            `type: message`, each part only when given, and `error` when neither is.
        """
        return entries.line(": ".join(part for part in (self.type, self.message) if part) or ERROR)


def read(stdout: str) -> AgentOutput:
    """Read an agent's stdout: plain text, or OpenCode 2's JSON events.

    Returns:
        `stdout` as it is, as both the text and the final message, when it holds no event. Otherwise the events' text
        parts joined by newlines, the last of them, the first valid session id, the steps' total usage, or None for
        usage when a step could not be read or was never finished, the tool calls rolled up by tool, and the errors
        the runtime reported.
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
    usage = tally.usage if tally.settled else None
    return AgentOutput("\n".join(texts), last, tally.session_id, usage, tally.tools, tally.errors)


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
        self._open = False
        self._tools = report.Tools()

    def add(self, event: Mapping[str, object]) -> None:
        """Count `event`: its session, and its model call's cost, its tool call, or its error, if it is one of them.

        The session is the first valid one an event names.
        """
        self.session_id = self.session_id or report.session_id(event["sessionID"])
        kind = event["type"]
        if kind == STEP_START:
            self._open = True
        elif kind == STEP_FINISH:
            self._open = False
            self._add_step(event)
        elif kind == TOOL_USE:
            self._add_tool(event)
        elif kind == ERROR:
            self._add_error(event)

    @property
    def usage(self) -> Usage | None:
        """The finished steps' total usage so far, or None when a step could not be read."""
        return report.total(self._calls) if self._complete else None

    @property
    def settled(self) -> bool:
        """Whether every call started so far has its cost read: none is left open, or the runtime reported an error."""
        return not self._open or bool(self._errors)

    @property
    def errors(self) -> tuple[str, ...]:
        """Each distinct error the runtime reported so far, on one line (`SessionError.describe`), in order."""
        return tuple(self._errors)

    @property
    def tools(self) -> tuple[ToolUse, ...]:
        """The tool calls so far, rolled up by tool, in the order each tool was first called."""
        return self._tools.rolled_up

    def _add_step(self, event: Mapping[str, object]) -> None:
        try:
            step = _StepFinish.model_validate(event.get("part"))
        except ValidationError:
            # A step canopy cannot read makes the total wrong, so the run reports no cost rather than too little.
            self._complete = False
            return
        t = step.tokens
        self._calls.append(Call(float(step.cost), t.input, t.output, t.reasoning, t.cache.read, t.cache.write))

    def _add_error(self, event: Mapping[str, object]) -> None:
        try:
            said = SessionError.model_validate(event.get("error")).describe()
        except ValidationError:
            # One canopy cannot read still says the session failed.
            said = ERROR
        if said not in self._errors:
            self._errors.append(said)

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
    """The skill a `skill` call loaded: the name OpenCode found it under, else the id it was asked for.

    Returns:
        The name, or None when neither is a skill's name by OpenCode's rule, so the call counts as `skill` alone.
    """
    found: list[str] = []
    with contextlib.suppress(ValidationError):
        named = _Skill.model_validate(state.metadata).metadata
        found += [named.name] if named is not None else []
    with contextlib.suppress(ValidationError):
        found.append(_Asked.model_validate(state.input).id)
    return next((name for name in found if len(name) <= MAX_SKILL_NAME and SKILL_NAME_RE.fullmatch(name)), None)
