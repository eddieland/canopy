"""A running agent's output, read a line at a time as it prints it (DESIGN §8, §13).

Each line says what it changed of what the run's row records: the session, once it is first named; what the run has
spent, at the end of each model call; and the tool call it ended. A row is written only when a line changed one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.runtime import events, transcript

if TYPE_CHECKING:
    from canopy.runtime.report import Usage


@dataclass(frozen=True)
class Change:
    """What one printed line changed of what a running run's row records."""

    #: The run's session: the first one its output named.
    session_id: str
    #: Whether this line named the session first.
    started: bool
    #: What the run has spent so far, when this line ended a model call and every call so far could be read.
    usage: Usage | None
    #: The tool call this line ended: its tool, and what it did (`transcript.did`).
    did: tuple[str, str] | None


class Watch:
    """Reads an agent's output as it prints it, keeping what its lines have reported so far."""

    def __init__(self) -> None:
        """Start with nothing printed: no session, nothing spent."""
        self._tally = events.Tally()

    def read(self, line: str) -> Change | None:
        """Read `line`, the next one the agent printed.

        Returns:
            What it changed, or None when it changed nothing: it is not an event, no session has been named yet, or it
            neither names the session first, ends a model call whose cost can be read, nor ends a tool call.
        """
        event = events.parse_event(line)
        if event is None:
            return None
        seen = self._tally.session_id
        self._tally.add(event)
        session = self._tally.session_id
        if session is None:
            return None
        usage = self._tally.usage if event["type"] == events.STEP_FINISH else None
        did = transcript.did(event)
        if session == seen and usage is None and did is None:
            return None
        return Change(session, started=seen is None, usage=usage, did=did)
