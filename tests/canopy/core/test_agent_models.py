"""`runtime.models`: each agent's model, the operator's choice alone, and the templates that would override it."""

import json
import re
from pathlib import Path

import pytest

from canopy.core import agent_models, config
from canopy.core.config import ConfigError
from canopy.infra import procs
from canopy.runtime import agents
from tests.conftest import CanopyEnv

MODEL = "acme/fake-model-1"


def test_each_role_chooses_for_its_agents(canopy_env: CanopyEnv) -> None:
    models = {"worker": MODEL, "planner": "acme/plan-2", "reviewer": "other/review-3"}
    canopy_env.configure(canopy_env.user_file, {"runtime": {"models": models}})
    cfg = config.load(canopy_env.root, canopy_env.user_file)
    assert cfg.runtime.models == models
    # A worker is the public or the private one: a task's run is the private one.
    assert agent_models.by_agent(cfg.runtime.models) == {
        agents.WORKER: MODEL,
        agents.PRIVATE_WORKER: MODEL,
        agents.PLANNER: "acme/plan-2",
        agents.REVIEWER: "other/review-3",
    }


@pytest.mark.parametrize(
    ("models", "error"),
    [
        ({"tester": MODEL}, "runtime.models[tester]: Value error, 'tester' is not an agent runtime.models chooses"),
        ({"worker": "claude"}, "runtime.models[worker]: Value error, 'claude' must be a model as OpenCode names it"),
        ({"worker": 'acme/x" injected'}, "runtime.models[worker]: Value error"),
        ({"worker": ""}, "runtime.models[worker]: Value error"),
    ],
)
def test_an_unknown_agent_or_a_model_canopy_cannot_render_is_refused(
    canopy_env: CanopyEnv,
    models: dict[str, str],
    error: str,
) -> None:
    canopy_env.configure(canopy_env.user_file, {"runtime": {"models": models}})
    with pytest.raises(ConfigError, match=re.escape(error)):
        config.load(canopy_env.root, canopy_env.user_file)


def test_the_models_are_private(canopy_env: CanopyEnv) -> None:
    """A shared workspace file cannot choose what the operator's spend buys (TRUST_MODEL T7)."""
    canopy_env.configure(canopy_env.shared_file, {"runtime": {"models": {"worker": MODEL}}})
    with pytest.raises(ConfigError, match=r"runtime\.models is private and cannot be set in the workspace file"):
        config.load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize(
    ("key", "value", "role"),
    [
        (
            "overseer_cmd",
            "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-overseer -m a/b",
            "overseer",
        ),
        (
            "worker_cmd",
            "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker --model a/b",
            "worker",
        ),
        (
            "private_worker_cmd",
            "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker-private --model=a/b",
            "worker",
        ),
        ("plan_cmd", "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-planner -m a/b", "planner"),
        (
            "review_cmd",
            "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-reviewer -m a/b",
            "reviewer",
        ),
        (
            "chore_cmd",
            "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-chore --model a/b",
            "chore",
        ),
        ("worker_cmd_prefix", "wrap --model a/b --", "worker or runtime.models.planner"),
        ("worker_cmd_suffix", "-m a/b", "worker or runtime.models.planner"),
    ],
)
def test_a_template_prefix_or_suffix_that_passes_a_model_is_refused(
    canopy_env: CanopyEnv,
    key: str,
    value: str,
    role: str,
) -> None:
    """A model on the command line beats the one in the agent's definition, so the run would record one and run on
    another (DESIGN §13). The error names the key to set instead."""
    canopy_env.configure(canopy_env.user_file, {"runtime": {key: value}})
    with pytest.raises(ConfigError) as e:
        config.load(canopy_env.root, canopy_env.user_file)
    assert f"runtime.{key}: Value error, must not pass a model" in str(e.value)
    assert f"Set runtime.models.{role} instead" in str(e.value)


def test_a_wrapper_may_take_a_short_option_of_its_own(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.user_file, {"runtime": {"worker_cmd_prefix": "python3 -m mywrapper --"}})
    assert config.load(canopy_env.root, canopy_env.user_file).runtime.worker_cmd_prefix == "python3 -m mywrapper --"


@pytest.mark.parametrize(
    ("template", "model"),
    [
        ("env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-worker {prompt}", MODEL),
        ("env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-worker-private {prompt}", MODEL),
        ("env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-planner {prompt}", None),
        # The operator's own agent: its model is the runtime's choice, not canopy's.
        ("env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent my-agent {prompt}", None),
    ],
)
def test_a_template_asks_for_the_model_of_the_agent_it_runs(template: str, model: str | None) -> None:
    assert agent_models.of_template({"worker": MODEL}, template) == model


def test_a_listed_model_passes_the_check(opencode_state: Path, tmp_path: Path) -> None:
    opencode_state.write_text(json.dumps({"models": [MODEL]}))
    agent_models.check(procs.SubprocessRunner(), tmp_path, MODEL)


def test_a_model_not_listed_or_a_list_not_read_is_refused(opencode_state: Path, tmp_path: Path) -> None:
    opencode_state.write_text(json.dumps({"models": ["acme/other"]}))
    with pytest.raises(agent_models.ModelError) as missing:
        agent_models.check(procs.SubprocessRunner(), tmp_path, MODEL)
    assert missing.value.guard == agent_models.MISSING
    opencode_state.write_text(json.dumps({"exit": 1}))
    with pytest.raises(agent_models.ModelError) as failed:
        agent_models.check(procs.SubprocessRunner(), tmp_path, MODEL)
    assert failed.value.guard == agent_models.LIST_FAILED
    assert "`opencode models` exited 1" in failed.value.reason
