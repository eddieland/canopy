"""How the runtime is told of one of canopy's own MCP servers, for one agent's run (DESIGN §27).

The overseer's run is given the server of its tools; a chore's run two, the one that serves it its own history (§19)
and the one of canopy's read-only reports; and a review's or a plan's run one of read-only git: its process's
environment names them, and turns off whatever in the runtime would hide MCP tools. That environment would pass to
every process the run's tree starts, so a run canopy starts removes `VARIABLES` first. The same environment turns off
the operator's own servers that config keeps out of canopy's runs, so every run that is given a server of canopy's,
which is every agent's run, never starts them. Which variables those are, and
the form of the entry, are the implementation's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import one, pick, two

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from canopy.runtime.implementation import Version

#: The variables that give a run a server, removed from every run canopy starts before it sets its own: each version's,
#: so a run started under one never passes on what the other would read.
VARIABLES = one.servers.VARIABLES | two.servers.VARIABLES


def env(
    commands: Mapping[str, Sequence[str]],
    *,
    version: Version,
    cwd: Path,
    disabled: Iterable[str],
    timeout_seconds: int | None = None,
) -> dict[str, str]:
    """The environment that gives a run each of canopy's servers `commands` names, each run as its command in `cwd`.

    The run is of the runtime `version` runs. Each server `disabled` names, of the operator's own runtime config
    (`runtime.disabled_mcp_servers`), is turned off for the run, so it never starts.

    `timeout_seconds`, when given, bounds each request the runtime makes of it, a tool call included; else the
    runtime's default does.

    Returns:
        The variables to set on the run's process.
    """
    implementation = pick(version, one.servers, two.servers)
    return implementation.env(commands, cwd=cwd, disabled=disabled, timeout_seconds=timeout_seconds)


def tool_name(server: str, tool: str) -> str:
    """The name an agent, and the definitions' rules, know tool `tool` of server `server` by.

    Returns:
        The runtime's name for it, such as `canopy_chore_history`.
    """
    # Both versions name a server's tool alike.
    return one.servers.tool_name(server, tool)
