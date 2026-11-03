"""A running agent's output, read a line at a time as it prints it (DESIGN §8, §13).

Each line says what it changed of what the run's row records: the session, once it is first named; what the run has
spent, at the end of each model call; and the tool call it ended, with the call as the agent made it, from which the
harness reads an update (§41). A row is written only when a line changed one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.infra import tracing
from canopy.runtime.implementation import one, pick, two

if TYPE_CHECKING:
    from canopy.runtime.implementation import Version
    from canopy.runtime.report import Called, Printed, Usage


@dataclass(frozen=True)
class Change:
    """What one printed line changed of what a running run's row records."""

    #: The run's session: the first one its output named.
    session_id: str
    #: Whether this line named the session first.
    started: bool
    #: What the run has spent so far, when this line ended a model call and every call so far could be read.
    usage: Usage | None
    #: The tool call this line ended: its tool, and what it did, on one line each.
    did: tuple[str, str] | None
    #: The same call as the agent made it, its tool's name and input; None where `did` is.
    called: Called | None = None


class Watch:
    """Reads an agent's output as it prints it, keeping what its lines have reported so far."""

    def __init__(self, *, version: Version, model: str | None = None) -> None:
        """Start with nothing printed by the runtime `version` runs: no session, nothing spent.

        Its model calls and tool calls are traced under the span open now, the run's, named for `model`, the one canopy
        asked the runtime for, when it chose one.
        """
        self._lines = pick(version, one.watch, two.watch).Lines()
        self._under = tracing.here()
        self._model = model
        #: When the model call under way started, as its `step_start` said; None between calls.
        self._call_started_ms: int | None = None

    def read(self, line: str) -> Change | None:
        """Read `line`, the next one the agent printed.

        Returns:
            What it changed, or None when it changed nothing: it is not an event, no session has been named yet, or it
            neither names the session first, ends a model call whose cost can be read, nor ends a tool call.
        """
        seen = self._lines.session_id
        printed = self._lines.read(line)
        session = self._lines.session_id
        if printed is not None and self._under is not None:
            self._trace(printed)
        if printed is None or session is None:
            return None
        usage = self._lines.usage if printed.ended_call else None
        if session == seen and usage is None and printed.did is None:
            return None
        return Change(session, started=seen is None, usage=usage, did=printed.did, called=printed.call)

    def _trace(self, printed: Printed) -> None:
        """Record a span for the model call or the tool call `printed` ended, at the times the runtime printed.

        A span holds the call's tokens and cost, or its tool's name and whether it failed, under OpenTelemetry's
        conventions for generative AI; never what the model was sent or wrote, nor a tool's input or output.
        """
        if printed.started_call:
            self._call_started_ms = printed.at_ms
        step = printed.step
        if step is not None and printed.at_ms is not None:
            start = self._call_started_ms if self._call_started_ms is not None else printed.at_ms
            tracing.interval(
                f"chat {self._model}" if self._model else "chat",
                self._under,
                start_ns=start * _NS_PER_MS,
                end_ns=printed.at_ms * _NS_PER_MS,
                standard={
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": self._model,
                    "gen_ai.usage.input_tokens": step.sent,
                    "gen_ai.usage.output_tokens": step.output,
                    "gen_ai.usage.cache_read.input_tokens": step.cache_read,
                    "gen_ai.usage.cache_creation.input_tokens": step.cache_write,
                },
                reasoning_tokens=step.reasoning,
                cost_usd=step.cost_usd,
            )
            self._call_started_ms = None
        tool = printed.tool
        if tool is not None:
            end = tool.end_ms if tool.end_ms is not None else printed.at_ms
            start = tool.start_ms if tool.start_ms is not None else end
            if start is not None and end is not None:
                tracing.interval(
                    f"execute_tool {tool.tool}",
                    self._under,
                    start_ns=start * _NS_PER_MS,
                    end_ns=end * _NS_PER_MS,
                    failed=tool.failed,
                    standard={"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": tool.tool},
                )


_NS_PER_MS = 1_000_000
