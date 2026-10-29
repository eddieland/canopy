"""OpenCode's JSON events read a line at a time as a running agent prints them (DESIGN §8, §13).

Each line is an event or not; an event may name the session, end a model call (`step_finish`), or end a tool call
(`tool_use`). `canopy.runtime.watch` decides from that what a line changed of what the run's row records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.opencode import events, transcript
from canopy.runtime.report import Printed

if TYPE_CHECKING:
    from canopy.runtime.report import Usage


class Lines:
    """An agent's printed lines read one at a time, with the session and what was spent of those read so far."""

    def __init__(self) -> None:
        """Start with nothing read: no session, nothing spent."""
        self._tally = events.Tally()

    def read(self, line: str) -> Printed | None:
        """Read `line`, the next one the agent printed.

        Returns:
            What it was: whether it ended a model call, and the tool call it ended, with its input when it
            completed; or None when it is not an event.
        """
        event = events.parse_event(line)
        if event is None:
            return None
        self._tally.add(event)
        return Printed(
            ended_call=event["type"] == events.STEP_FINISH,
            did=transcript.did(event),
            called=transcript.called(event),
        )

    @property
    def session_id(self) -> str | None:
        """The session: the first valid one a line read so far named."""
        return self._tally.session_id

    @property
    def usage(self) -> Usage | None:
        """What the lines read so far spent, or None when a model call among them could not be read."""
        return self._tally.usage
