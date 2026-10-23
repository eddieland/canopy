"""How a command template starts one of the runtime's agents: the defaults, and the config directory (D040)."""

import shlex

import pytest

from canopy.runtime.opencode import invocation


def test_the_default_template_points_the_runtime_at_the_definitions_and_asks_for_events() -> None:
    template = invocation.default_template("canopy-worker", definitions_dir="{d}", title="{t}")
    assert shlex.split(template) == [
        "env",
        f"{invocation.CONFIG_DIR_ENV}={{d}}",
        "opencode",
        "run",
        "--agent",
        "canopy-worker",
        "--format",
        "json",
        "--thinking",
        "--title={t}",
    ]
    assert invocation.agent_of(template) == "canopy-worker"


def test_with_config_dir_runs_the_command_with_the_directory_set() -> None:
    command = invocation.with_config_dir(shlex.quote("/state/my dir"), "opencode run --agent x {prompt}")
    assert shlex.split(command)[:2] == ["env", f"{invocation.CONFIG_DIR_ENV}=/state/my dir"]


@pytest.mark.parametrize(
    ("command", "agent"),
    [
        ("opencode run --agent=canopy-chore {prompt}", "canopy-chore"),
        ("opencode run --agent canopy-chore", "canopy-chore"),
        ("opencode run --agent ../escape {prompt}", None),
        ("opencode run --agent Canopy {prompt}", None),
        ("opencode run {prompt}", None),
    ],
)
def test_agent_of_names_only_an_agent_a_path_component_can_hold(command: str, agent: str | None) -> None:
    assert invocation.agent_of(command) == agent


@pytest.mark.parametrize(
    ("command", "run_args", "found"),
    [
        ("env X=1 opencode run --agent canopy-worker --model acme/x {prompt}", False, "--model"),
        ("env X=1 opencode run --agent canopy-worker --model=acme/x {prompt}", False, "--model=acme/x"),
        ("env X=1 /usr/bin/opencode run --agent canopy-worker -m acme/x", False, "-m"),
        ("env X=1 opencode run --agent canopy-worker -m=acme/x", False, "-m=acme/x"),
        ("env X=1 opencode run --agent canopy-worker -macme/x", False, "-macme/x"),
        # A wrapper may hand `--model` on, but `-m` before the run is the wrapper's own.
        ("wrap --model acme/x --", False, "--model"),
        ("python -m wrap --", False, None),
        # A variant beats the definition's as a model does, and has no short form.
        ("env X=1 opencode run --agent canopy-worker --variant high {prompt}", False, "--variant"),
        ("wrap --variant=max --", False, "--variant=max"),
        ("--variant=max", True, "--variant=max"),
        ("env X=1 opencode run --agent canopy-worker -v {prompt}", False, None),
        # A suffix's words are the run's own.
        ("-m acme/x", True, "-m"),
        ("-macme/x", True, "-macme/x"),
        ("--log-level DEBUG", True, None),
    ],
)
def test_model_option_finds_a_model_or_variant_passed_on_the_command_line(
    command: str,
    found: str | None,
    *,
    run_args: bool,
) -> None:
    assert invocation.model_option(shlex.split(command), run_args=run_args) == found


@pytest.mark.parametrize(
    ("command", "replaced"),
    [
        (
            "env X=1 opencode run --agent canopy-chore --format json {prompt}",
            "env X=1 opencode run --agent canopy-chore-triage --format json {prompt}",
        ),
        ("opencode run --agent=canopy-chore", "opencode run --agent=canopy-chore-triage"),
        ("opencode run {prompt}", "opencode run {prompt}"),
    ],
)
def test_with_agent_runs_another_agent_in_place_of_the_one_named(command: str, replaced: str) -> None:
    assert invocation.with_agent(command, "canopy-chore-triage") == replaced
    assert invocation.agent_of(replaced) == ("canopy-chore-triage" if "--agent" in command else None)
