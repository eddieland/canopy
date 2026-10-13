"""What an agent run printed (DESIGN §13): the text its result line is read from, and what the runtime reported.

A command template either prints the agent's text on stdout, or, with OpenCode's `--format json`, prints one JSON event
per line. canopy reads two kinds of event and one field of every event, each validated (D026):

- `text`: a finished piece of the agent's text, in `part.text`. Joined one per line they are what stdout holds without
  `--format json`, so every result contract reads the same either way.
- `step_finish`: one model call's `part.cost`, in dollars, and `part.tokens`. Summed, they are what the run cost.
- `sessionID`, on every event: the session OpenCode kept, which the operator opens with OpenCode's own tools.

Any other event, and any line that is not an event, is ignored. Output with no events at all is plain text, as from a
template without `--format json` or another runtime, and reports no session and no cost.
"""

from __future__ import annotations

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
    model_config = ConfigDict(extra="ignore", frozen=True)

    text: StrictStr


class _Cache(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    read: Count
    write: Count


class _Tokens(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    input: Count
    output: Count
    reasoning: Count
    cache: _Cache


class _StepFinish(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    cost: Annotated[StrictFloat | StrictInt, Field(ge=0, le=MAX_COST_USD, allow_inf_nan=False)]
    tokens: _Tokens


@dataclass(frozen=True)
class Usage:
    """What a run cost: dollars as the runtime priced them, and tokens by kind."""

    cost_usd: float
    input: int
    output: int
    reasoning: int
    cache_read: int
    cache_write: int

    @property
    def tokens(self) -> int:
        """Every token the model read or wrote, cache reads and writes included."""
        return self.input + self.output + self.reasoning + self.cache_read + self.cache_write

    def describe(self) -> str:
        """What it cost for a person, as `$0.25, 12.3k tokens`.

        Returns:
            The cost to the cent and the token count, abbreviated with `k` or `M` from a thousand up.
        """
        return f"${self.cost_usd:.2f}, {_count(self.tokens)} tokens"


def _count(n: int) -> str:
    for size, suffix in ((1_000_000, "M"), (1_000, "k")):
        if n >= size:
            return f"{n / size:.1f}{suffix}"
    return str(n)


@dataclass(frozen=True)
class AgentOutput:
    """`text` is what a result contract is read from. `session_id` and `usage` are None when nothing reported them."""

    text: str
    session_id: str | None = None
    usage: Usage | None = None


def read(stdout: str) -> AgentOutput:
    """Read an agent's stdout: plain text, or OpenCode's JSON events.

    Returns:
        `stdout` as it is when it holds no event. Otherwise the events' text parts joined by newlines, the first valid
        session id, and the steps' total usage, or None for usage when a step could not be read.
    """
    texts: list[str] = []
    steps: list[_StepFinish] = []
    session: str | None = None
    events = 0
    complete = True
    for line in stdout.splitlines():
        event = parse_event(line)
        if event is None:
            continue
        events += 1
        session = session or session_of(event)
        try:
            if event["type"] == "text":
                texts.append(_Text.model_validate(event.get("part")).text)
            elif event["type"] == "step_finish":
                steps.append(_StepFinish.model_validate(event.get("part")))
        except ValidationError:
            # A text part canopy cannot read is left out, which at worst makes the result line invalid. A step it
            # cannot read makes the total wrong, so the run reports no cost rather than too little.
            complete = complete and event["type"] != "step_finish"
    if not events:
        return AgentOutput(stdout)
    return AgentOutput("\n".join(texts), session, _total(steps) if complete else None)


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
    return Usage(
        cost_usd=sum(float(s.cost) for s in steps),
        input=sum(s.tokens.input for s in steps),
        output=sum(s.tokens.output for s in steps),
        reasoning=sum(s.tokens.reasoning for s in steps),
        cache_read=sum(s.tokens.cache.read for s in steps),
        cache_write=sum(s.tokens.cache.write for s in steps),
    )
