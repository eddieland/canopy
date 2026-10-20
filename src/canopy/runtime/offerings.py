"""What the runtime offers each of canopy's agents once it has merged the operator's config into canopy's (DESIGN §13).

canopy's definitions say what each agent may do, and the operator's own runtime config may deny it more: an MCP server
or a skill an agent never uses still costs every model call it is offered to. The runtime is asked, rather than its
config read here, so the answer is the merge the runtime itself makes. Which commands it is asked with, and how its
rules are read, is the implementation's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import offerings as implementation

if TYPE_CHECKING:
    from collections.abc import Sequence
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
