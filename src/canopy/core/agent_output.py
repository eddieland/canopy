"""What an agent run printed (DESIGN §13): the text its result line is read from, and what the runtime reported.

A command template either prints the agent's text on stdout, or, with OpenCode's `--format json`, prints one JSON event
per line. canopy reads two kinds of event and one field of every event, each validated (D026):

- `text`: a finished piece of the agent's text, in `part.text`. Joined one per line they are what stdout holds without
  `--format json`, so every result contract reads the same either way. The last one is the agent's final message.
- `step_finish`: one model call's `part.cost`, in dollars, and `part.tokens`. Summed, they are what the run cost; the
  most one call was sent is the run's peak context. The first call's is kept apart: what it was sent, less the
  prompt, is the run's fixed overhead, and its cache write says whether that came from the cache.
- `sessionID`, on every event: the session OpenCode kept, which the operator opens with OpenCode's own tools.

Any other event, and any line that is not an event, is ignored. Output with no events at all is plain text, as from a
template without `--format json` or another runtime, and reports no session and no cost. Its final message is all of
it: plain text does not say where one message ends.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from typing import Annotated, cast

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationError

# Printed by `canopy status` and pasted into a shell, so nothing a terminal or a shell would read as anything else.
SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,100}")

# Far above anything one model call reports, and low enough that no run's sums overflow a float or SQLite's integers.
MAX_TOKENS = 10**12
MAX_COST_USD = 10**6

Count = Annotated[StrictInt, Field(ge=0, le=MAX_TOKENS)]


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
        peak = f", {_count(self.peak_context)} peak context" if self.peak_context is not None else ""
        return f"${self.cost_usd:.2f}, {_count(self.new_tokens)} tokens{peak}"

    def spent(self) -> dict[str, object]:
        """What it cost as a log line's fields.

        Returns:
            The cost in dollars, the tokens (`new_tokens`), and the peak context.
        """
        return {"cost_usd": self.cost_usd, "new_tokens": self.new_tokens, "peak_context": self.peak_context}


def _count(n: int) -> str:
    for size, suffix in ((1_000_000, "M"), (1_000, "k")):
        if n >= size:
            return f"{n / size:.1f}{suffix}"
    return str(n)


@dataclass(frozen=True)
class AgentOutput:
    """`text` is what a result contract is read from, and `last` the agent's final message, the end of `text`.

    `session_id` and `usage` are None when nothing reported them.
    """

    text: str
    last: str
    session_id: str | None = None
    usage: Usage | None = None


def read(stdout: str) -> AgentOutput:
    """Read an agent's stdout: plain text, or OpenCode's JSON events.

    Returns:
        `stdout` as it is, as both the text and the final message, when it holds no event. Otherwise the events' text
        parts joined by newlines, the last of them, the first valid session id, and the steps' total usage, or None for
        usage when a step could not be read.
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
    return AgentOutput("\n".join(texts), last, tally.session_id, tally.usage)


class Tally:
    """The session and usage of an agent's events, added one at a time as it prints them, as `read` reports them.

    So a running agent's session and what it has spent so far are what `read` would say of what it printed so far.
    """

    def __init__(self) -> None:
        """Start with no event: no session, and nothing spent."""
        self.session_id: str | None = None
        self._steps: list[_StepFinish] = []
        self._complete = True

    def add(self, event: dict[str, object]) -> None:
        """Count `event`: the first valid session it names, and its model call's cost if it is a `step_finish`."""
        self.session_id = self.session_id or session_of(event)
        if event["type"] != "step_finish":
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


def session_of(event: dict[str, object]) -> str | None:
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


def _total(steps: list[_StepFinish]) -> Usage:
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


# What one model call was sent: its input, from the cache or not.
def _sent(tokens: _Tokens) -> int:
    return tokens.input + tokens.cache.read + tokens.cache.write
