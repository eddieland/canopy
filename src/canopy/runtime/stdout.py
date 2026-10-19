"""What a finished agent printed on stdout, read into what it reports (DESIGN §13): text, session, cost, and tools.

A template asks the runtime for its events or for plain text; either reads the same way here, so every result contract
reads the agent's text whichever it asked for, and a template that asks for no events records no session and no cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import events

if TYPE_CHECKING:
    from canopy.runtime.report import AgentOutput


def read(stdout: str) -> AgentOutput:
    """Read an agent's stdout, as its runtime prints it.

    Returns:
        Its text and final message, and, from any events, its session, what it spent (None when a model call could not
        be read), and its tool calls rolled up by tool. Output with no events is its own text and final message.
    """
    return events.read(stdout)
