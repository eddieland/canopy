"""How OpenCode 2 is given one of canopy's MCP servers for one run: in its inline config, out of code mode."""

import json
from pathlib import Path

from canopy.runtime.opencode2 import servers


def test_a_server_is_given_in_the_inline_config_with_its_tools_offered_by_name() -> None:
    env = servers.env({"canopy": ["canopy", "_mcp", "--run", "7"]}, cwd=Path("/ws"), disabled=())
    assert set(env) == servers.VARIABLES == {"OPENCODE_CONFIG_CONTENT"}
    # OpenCode 2's own shape, `mcp.servers`, which takes `codemode`; out of it, its tools are not behind `execute`.
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"]) == {
        "mcp": {
            "servers": {
                "canopy": {
                    "type": "local",
                    "command": ["canopy", "_mcp", "--run", "7"],
                    "cwd": "/ws",
                    "codemode": False,
                },
            },
        },
    }


def test_a_tool_is_named_as_opencode_sanitizes_its_server_and_tool() -> None:
    assert servers.tool_name("canopy", "chore_history") == "canopy_chore_history"
    assert servers.tool_name("my.srv", "get.issue") == "my_srv_get_issue"
    assert servers.tool_name("café", "x") == "caf__x"


def test_several_servers_are_given_in_one_inline_config() -> None:
    env = servers.env(
        {"canopy_chore": ["canopy", "_mcp", "--chore"], "canopy_reports": ["x"]},
        cwd=Path("/ws"),
        disabled=(),
    )
    given = json.loads(env["OPENCODE_CONFIG_CONTENT"])["mcp"]["servers"]
    assert {name: entry["command"] for name, entry in given.items()} == {
        "canopy_chore": ["canopy", "_mcp", "--chore"],
        "canopy_reports": ["x"],
    }


def test_a_timeout_bounds_each_tool_call_in_milliseconds() -> None:
    env = servers.env({"canopy": ["canopy", "_mcp"]}, cwd=Path("/ws"), disabled=(), timeout_seconds=900)
    given = json.loads(env["OPENCODE_CONFIG_CONTENT"])["mcp"]["servers"]["canopy"]
    assert given["timeout"] == {"execution": 900_000}


def test_a_server_of_the_operators_that_config_turns_off_is_given_enabled_false_alone() -> None:
    """OpenCode 2 takes `enabled` alone in 1's shape and merges it into the operator's entry; `disabled` would not."""
    env = servers.env({"canopy": ["canopy", "_mcp"]}, cwd=Path("/ws"), disabled=("slack", "browser"))
    given = json.loads(env["OPENCODE_CONFIG_CONTENT"])["mcp"]["servers"]
    assert given["slack"] == given["browser"] == {"enabled": False}
    assert given["canopy"]["command"] == ["canopy", "_mcp"]


def test_turning_servers_off_alone_still_gives_an_inline_config() -> None:
    env = servers.env({}, cwd=Path("/ws"), disabled=("slack",))
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"]) == {"mcp": {"servers": {"slack": {"enabled": False}}}}
