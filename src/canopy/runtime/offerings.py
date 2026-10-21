"""What the runtime offers each of canopy's agents once it has merged the operator's config into canopy's (DESIGN §13).

canopy's definitions say what each agent may do, and the operator's own runtime config may deny it more: an MCP server
or a skill an agent never uses still costs every model call it is offered to. The runtime is asked, rather than its
config read here, so the answer is the merge the runtime itself makes. Which commands it is asked with, and how its
rules are read, is the implementation's.

Each agent run is asked about too, as it starts (`Probe`): on a thread of its own, so the run waits on it only if it
ends first, and started as the run's own command starts the runtime, so it is asked inside whatever wraps the agent.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from canopy.runtime.agents import AgentOffer
from canopy.runtime.implementation import offerings as implementation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from canopy.infra import procs
    from canopy.runtime.agents import Offerings


def offerings(runner: procs.Runner, *, cwd: Path, definitions_dir: Path, agents: Sequence[str]) -> Offerings:
    """Ask the runtime what it offers each of `agents`, started in `cwd` with canopy's definitions in `definitions_dir`.

    Returns:
        The MCP servers and skills the runtime has, and what each agent is offered of them; `error` set, and nothing
        else, when the runtime could not list them, and an agent's `error` when its rules could not be read.
    """
    return implementation.offerings(runner, cwd=cwd, definitions_dir=definitions_dir, agents=agents)


class Probe:
    """What the runtime offers one agent run, asked on a thread of its own from when the probe is made."""

    def __init__(self, runner: procs.Runner, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> None:
        """Start asking what the agent `argv` runs is offered, started as `argv` starts it, in `cwd` with `env`."""
        self._found = AgentOffer("", error="canopy could not ask the runtime")
        self._thread = threading.Thread(target=self._ask, args=(runner, argv, cwd, env), name="offers", daemon=True)
        self._thread.start()

    def result(self) -> AgentOffer:
        """Wait for the runtime's answer.

        Returns:
            What the agent is offered, as `offered` says it.
        """
        self._thread.join()
        return self._found

    def _ask(self, runner: procs.Runner, argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> None:
        # Only this thread writes it, and `result` reads it once the thread has ended.
        self._found = implementation.offered(runner, argv, cwd=cwd, env=env)
