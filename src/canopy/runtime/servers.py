"""How the runtime is told of one of canopy's own MCP servers, for one agent's run (DESIGN §27).

A chore's run is given two, the one that serves it its own history (§19) and the one of canopy's read-only reports, and
a review's or a plan's run one of read-only git: its process's environment names them, and turns off whatever in the
runtime would hide MCP tools. That environment would pass to every process the
run's tree starts, so a run canopy starts removes `VARIABLES` first. Which variables those are, and the form of the
entry, are the implementation's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import servers

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

#: The variables that give a run a server, removed from every run canopy starts before it sets its own.
VARIABLES = servers.VARIABLES


def env(commands: Mapping[str, Sequence[str]], *, cwd: Path) -> dict[str, str]:
    """The environment that gives a run each of canopy's servers `commands` names, each run as its command in `cwd`.

    Returns:
        The variables to set on the run's process.
    """
    return servers.env(commands, cwd=cwd)


def tool_name(server: str, tool: str) -> str:
    """The name an agent, and the definitions' rules, know tool `tool` of server `server` by.

    Returns:
        The runtime's name for it, such as `canopy_chore_history`.
    """
    return servers.tool_name(server, tool)
