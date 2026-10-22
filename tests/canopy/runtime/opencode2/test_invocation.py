"""How a command template starts one of OpenCode 2's agents: the defaults, on a private server, with config (D040)."""

import shlex

import pytest

from canopy.runtime.opencode2 import invocation


def test_the_default_template_runs_a_private_server_pointed_at_the_definitions_and_asks_for_events() -> None:
    template = invocation.default_template("canopy-worker", definitions_dir="{d}", title="{t}", prompt="{p}")
    assert shlex.split(template) == [
        "env",
        f"{invocation.CONFIG_DIR_ENV}={{d}}",
        "opencode",
        "run",
        "--standalone",
        "--agent",
        "canopy-worker",
        "--format",
        "json",
        "--thinking",
        "--title={t}",
        "{p}",
    ]
    assert invocation.agent_of(template) == "canopy-worker"


def test_with_config_dir_runs_the_command_with_the_directory_set() -> None:
    command = invocation.with_config_dir(shlex.quote("/state/my dir"), "opencode run --agent x {prompt}")
    assert shlex.split(command)[:2] == ["env", f"{invocation.CONFIG_DIR_ENV}=/state/my dir"]


@pytest.mark.parametrize(
    ("command", "agent"),
    [
        ("opencode run --standalone --agent=canopy-chore {prompt}", "canopy-chore"),
        ("opencode run --agent canopy-chore", "canopy-chore"),
        ("opencode run --agent ../escape {prompt}", None),
        ("opencode run {prompt}", None),
    ],
)
def test_agent_of_names_only_an_agent_a_path_component_can_hold(command: str, agent: str | None) -> None:
    assert invocation.agent_of(command) == agent
