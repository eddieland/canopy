"""How OpenCode is given one of canopy's own MCP servers, for one agent's run only (DESIGN §27).

The server is a local one in the run's inline config, `OPENCODE_CONFIG_CONTENT`, which OpenCode merges after the
workspace's config and before only what the operator or their organization manages, so canopy's command replaces any a
workspace sets. A spawn passes its environment on, inline config included, so a run canopy starts drops these variables
(`VARIABLES`) before giving its agent its own.

OpenCode 1.19.3 turns its code mode on with `OPENCODE_EXPERIMENTAL_CODE_MODE`, or, when that is unset, with
`OPENCODE_EXPERIMENTAL`; in code mode it offers no MCP tool. Setting the first to false turns code mode off whatever
the second says, and leaves the operator's other experiments as they are.

A server of the operator's own that config turns off for canopy's runs is given an entry of `enabled` false alone,
which OpenCode merges deep into the operator's own, so the server never starts.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

#: The variable OpenCode reads inline config from, merged after every config file but those managed for the operator.
INLINE_CONFIG_ENV = "OPENCODE_CONFIG_CONTENT"
#: The variable that turns OpenCode's code mode on or off, over `OPENCODE_EXPERIMENTAL`.
CODE_MODE_ENV = "OPENCODE_EXPERIMENTAL_CODE_MODE"
#: The variables canopy sets to give a run a server, which no run started below it may inherit.
VARIABLES = frozenset({INLINE_CONFIG_ENV, CODE_MODE_ENV})


def env(
    commands: Mapping[str, Sequence[str]],
    *,
    cwd: Path,
    disabled: Iterable[str],
    timeout_seconds: int | None = None,
) -> dict[str, str]:
    """The environment that gives a run each local MCP server `commands` names, each run as its command in `cwd`.

    Each server `disabled` names, of the operator's own config, is turned off for the run, and never starts.

    `timeout_seconds`, when given, bounds each request OpenCode makes of it, a tool call included; OpenCode's own
    default is a minute, and an overseer's dispatch can wait longer than that on a lease.

    Returns:
        The variables to set on the run's process: the servers in its inline config, the operator's servers turned
        off, and code mode off.
    """
    limit = {} if timeout_seconds is None else {"timeout": timeout_seconds * 1000}
    # canopy's own come last, so a name in both is canopy's server, never one turned off.
    turned_off = {server: {"enabled": False} for server in disabled}
    entries = {
        server: {"type": "local", "command": list(command), "cwd": str(cwd), "enabled": True, **limit}
        for server, command in commands.items()
    }
    return {INLINE_CONFIG_ENV: json.dumps({"mcp": {**turned_off, **entries}}), CODE_MODE_ENV: "false"}


def tool_name(server: str, tool: str) -> str:
    """The name OpenCode gives tool `tool` of MCP server `server`, as permission rules name it.

    Returns:
        `<server>_<tool>`, every character outside `[A-Za-z0-9_-]` made `_`, as OpenCode sanitizes them.
    """
    return "".join(c if c.isascii() and (c.isalnum() or c in "_-") else "_" for c in f"{server}_{tool}")
