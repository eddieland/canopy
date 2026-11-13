"""A run that ended without a result, asked once more for it in its own session (DESIGN §13).

An agent reports its result with canopy's `result` tool, whose server refuses one that does not validate while the
agent can still send it again. An agent that ends with no call the server took has still done its work, and may have
commented, labeled, or pushed, so a run read as `unknown` would leave the journal at odds with the world. Such a run,
if it exited cleanly, with no error in its session and time left, is sent one more message in that session: canopy's
own words, which name the tool and carry nothing the agent or anyone else wrote (TRUST_MODEL T1). It is asked once, for
the rest of the run's time, and what it then reports is its result; a run that still reports none is `unknown`, as
before.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from canopy.core import run_result
from canopy.core.config import Rendered, render_command
from canopy.runtime import invocation, stdout

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from canopy.infra import procs
    from canopy.runtime.implementation import Version

#: The fewest seconds of its time a run must have left to be asked again: enough for a model call and the tool's.
MIN_SECONDS = 60.0


@dataclass(frozen=True)
class Again:
    """How a run's agent is started again: the message its session is sent, for the rest of the run's time."""

    #: What the session is sent, in place of the run's prompt: canopy's own words.
    message: str
    #: The words that continue the session, for the end of the run's command.
    words: Sequence[str]
    #: The seconds left of the run's time, this start's timeout.
    seconds: float

    def render(self, template: str, definitions_dir: Path, title: str) -> Rendered:
        """Render the run's command `template` to send the message to its session, as its prompt was rendered.

        Returns:
            The argv, with the words that continue the session last, and the message where the prompt went.
        """
        rendered = render_command(template, self.message, definitions_dir, title)
        return Rendered([*rendered.argv, *self.words], rendered.stdin)


class Start(Protocol):
    """Start a run's agent and wait for it: with its prompt for the run's time, or `again`, and return its process."""

    def __call__(self, again: Again | None, /) -> procs.Result:
        """Run the agent once.

        Returns:
            Its process, as the runner returned it.
        """
        ...


def run(
    start: Start,
    asked: run_result.Asked,
    *,
    server: str,
    version: Version,
    seconds: float,
) -> tuple[procs.Result, str]:
    """Run an agent with `start`, which `seconds` bound in all, and once more in its session if it reported no result.

    `asked` is what the run reports with the `result` tool of its server `server`, on the runtime `version` runs.

    Returns:
        The agent's process, its output that of both starts when it was asked again, and the result it reported, as
        one line of JSON; "" when it reported none.
    """
    began = time.monotonic()
    done = start(None)
    found = run_result.reported(done.stdout, asked, server=server, version=version)
    if found:
        return done, found
    again = _again(done, server=server, version=version, seconds=seconds - (time.monotonic() - began))
    if again is None:
        return done, found
    more = start(again)
    # The first start's exit stands, as the second only says what the first left unsaid, but a second that ran out
    # the run's time is the run's timeout. Each output is read whole, so the second starts on a line of its own.
    joined = replace(
        done,
        stdout=_lines(done.stdout) + more.stdout,
        stderr=_lines(done.stderr) + more.stderr,
        timed_out=more.timed_out,
        returncode=more.returncode if more.timed_out else done.returncode,
    )
    return joined, run_result.reported(joined.stdout, asked, server=server, version=version)


def message(server: str) -> str:
    """What a run that reported no result is sent: canopy's own words, which name the tool of its server `server`.

    Returns:
        The message, one paragraph.
    """
    return (
        f"canopy took no call of your `{run_result.tool_name(server)}` tool, so your run has reported no result. "
        "Call it now, once, with your result as your work stands, and then end your run: do no other work."
    )


def _again(done: procs.Result, *, server: str, version: Version, seconds: float) -> Again | None:
    """How the agent that ended as `done`, with no result, is asked again, with `seconds` left of the run's time.

    It is asked only when it exited 0 in time, its session is known and reported no error, and at least `MIN_SECONDS`
    are left: a crash, a kill, or a failed session is not a result left unsaid.

    Returns:
        The message, the words that continue its session, and the seconds left; None when it is not asked.
    """
    if not done.ok or seconds < MIN_SECONDS:
        return None
    output = stdout.read(done.stdout, version=version)
    if output.session_id is None or output.errors:
        return None
    return Again(message(server), invocation.continuing(output.session_id, version=version), seconds)


def _lines(text: str) -> str:
    """Return `text` ending a line, so what is added to it starts a line of its own; "" stays ""."""
    return text if not text or text.endswith("\n") else f"{text}\n"
