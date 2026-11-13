"""How OpenCode 2 is given one of canopy's own MCP servers, for one agent's run only (DESIGN §27).

The server is a local one in the run's inline config, `OPENCODE_CONFIG_CONTENT`, which OpenCode merges after every
config file but those managed for the operator, a project's included, and a later definition of a server replaces an
earlier one whole: canopy's command replaces any a workspace sets. A spawn passes its environment on, inline config
included, so a run canopy starts drops `VARIABLES` before giving its agent its own.

OpenCode 2 puts every MCP tool behind its code mode, one `execute` tool that runs code calling them, unless the server
says otherwise; there is no variable that turns code mode off. So canopy's server sets `codemode` false, in OpenCode 2's
own shape of the entry (`mcp.servers`), and its tools are offered by name, `<server>_<tool>`, as the definitions'
rules name them.

A server of the operator's own that config turns off for canopy's runs is given an entry of `enabled` false alone,
which OpenCode 2 takes as its first's shape of the entry and merges deep into the operator's own, so the server never
starts. A `disabled` entry would be checked whole against 2's own shape, which wants its type and command, and dropped.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

#: The variable OpenCode reads inline config from, merged after every config file but those managed for the operator.
INLINE_CONFIG_ENV = "OPENCODE_CONFIG_CONTENT"
#: The variables canopy sets to give a run a server, which no run started below it may inherit.
VARIABLES = frozenset({INLINE_CONFIG_ENV})


def env(
    commands: Mapping[str, Sequence[str]],
    *,
    cwd: Path,
    disabled: Iterable[str],
    timeout_seconds: int | None = None,
) -> dict[str, str]:
    """The environment that gives a run each local MCP server `commands` names, each run as its command in `cwd`.

    Each server `disabled` names, of the operator's own config, is turned off for the run, and never starts.

    `timeout_seconds`, when given, bounds each tool call OpenCode makes of it (`timeout.execution`, in milliseconds);
    OpenCode 2.1.4's own default is twelve hours, and its 30 seconds to start the server and list its tools stay.

    Returns:
        The variables to set on the run's process: the servers in its inline config, outside code mode, and the
        operator's servers turned off.
    """
    limit = {} if timeout_seconds is None else {"timeout": {"execution": timeout_seconds * 1000}}
    # canopy's own come last, so a name in both is canopy's server, never one turned off.
    turned_off = {server: {"enabled": False} for server in disabled}
    entries = {
        server: {"type": "local", "command": list(command), "cwd": str(cwd), "codemode": False, **limit}
        for server, command in commands.items()
    }
    return {INLINE_CONFIG_ENV: json.dumps({"mcp": {"servers": {**turned_off, **entries}}})}


def tool_name(server: str, tool: str) -> str:
    """The name OpenCode gives tool `tool` of MCP server `server`, as permission rules name it.

    Returns:
        `<server>_<tool>`, every character outside `[A-Za-z0-9_-]` made `_`, as OpenCode sanitizes them.
    """
    return "".join(c if c.isascii() and (c.isalnum() or c in "_-") else "_" for c in f"{server}_{tool}")
