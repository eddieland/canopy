"""`runtime.models`: each agent's model, the operator's choice alone, and the templates that would override it."""

import json
import re
from pathlib import Path

import pytest

from canopy.core import agent_models, config
from canopy.core.config import ConfigError
from canopy.infra import procs
from canopy.runtime import agents
from canopy.runtime.agents import Model
from tests.conftest import CanopyEnv

MODEL = "acme/fake-model-1"
OTHER = "acme/fake-model-2"


def test_each_role_chooses_for_its_agents(canopy_env: CanopyEnv) -> None:
    models = {"worker": MODEL, "planner": "acme/plan-2", "reviewer": "other/review-3"}
    canopy_env.configure(canopy_env.user_file, {"runtime": {"models": models}})
    cfg = config.load(canopy_env.root, canopy_env.user_file)
    assert cfg.runtime.models == models
    # A worker is the public or the private one: a task's run is the private one.
    assert agent_models.by_agent(cfg.runtime.models) == {
        agents.WORKER: Model(MODEL),
        agents.PRIVATE_WORKER: Model(MODEL),
        agents.PLANNER: Model("acme/plan-2"),
        agents.REVIEWER: Model("other/review-3"),
    }


@pytest.mark.parametrize(
    ("value", "model"),
    [
        ("acme/model-a", Model("acme/model-a")),
        ("acme/model-a@high", Model("acme/model-a", "high")),
        ("openrouter/vendor/model-a@max", Model("openrouter/vendor/model-a", "max")),
        # A model whose own id holds an `@`, as a dated one does: a variant starts with a letter.
        ("vertex/model-a@20250101", Model("vertex/model-a@20250101")),
        ("vertex/model-a@20250101@low", Model("vertex/model-a@20250101", "low")),
    ],
)
def test_a_variant_is_what_follows_the_last_at_when_it_starts_with_a_letter(value: str, model: Model) -> None:
    assert agent_models.parse(value) == model
    assert model.name == value


def test_a_variant_is_chosen_with_its_model(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.user_file, {"runtime": {"models": {"reviewer": "acme/model-a@high"}}})
    cfg = config.load(canopy_env.root, canopy_env.user_file)
    assert agent_models.by_agent(cfg.runtime.models) == {agents.REVIEWER: Model("acme/model-a", "high")}


@pytest.mark.parametrize(
    ("models", "error"),
    [
        ({"tester": MODEL}, "runtime.models[tester]: Value error, 'tester' is not an agent runtime.models chooses"),
        ({"worker": "claude"}, "runtime.models[worker]: Value error, 'claude' must be a model as OpenCode names it"),
        ({"worker": 'acme/x" injected'}, "runtime.models[worker]: Value error"),
        # Nothing that would end the commit trailer's name, or the backticks a prompt quotes it in.
        ({"worker": "acme/x`y"}, "runtime.models[worker]: Value error"),
        ({"worker": "acme/x <y@z>"}, "runtime.models[worker]: Value error"),
        ({"worker": ""}, "runtime.models[worker]: Value error"),
        ({"worker": "acme@high"}, "runtime.models[worker]: Value error"),
        ({"worker": "acme/x@hi gh"}, "runtime.models[worker]: Value error"),
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
        (
            "review_cmd",
            "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-reviewer --variant high",
            "reviewer",
        ),
        ("worker_cmd_prefix", "wrap --model a/b --", "worker or runtime.models.planner"),
        ("worker_cmd_suffix", "-m a/b", "worker or runtime.models.planner"),
        ("worker_cmd_suffix", "--variant=max", "worker or runtime.models.planner"),
    ],
)
def test_a_template_prefix_or_suffix_that_passes_a_model_is_refused(
    canopy_env: CanopyEnv,
    key: str,
    value: str,
    role: str,
) -> None:
    """A model or variant on the command line beats the one in the agent's definition (DESIGN §13).

    So the run would record one and run on another. The error names the key to set instead.
    """
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
        ("env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-worker {prompt}", Model(MODEL)),
        ("env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-worker-private {prompt}", Model(MODEL)),
        ("env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-planner {prompt}", None),
        # The operator's own agent: its model is the runtime's choice, not canopy's.
        ("env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent my-agent {prompt}", None),
    ],
)
def test_a_template_asks_for_the_model_of_the_agent_it_runs(template: str, model: Model | None) -> None:
    assert agent_models.of_template({"worker": MODEL}, template) == model


def test_a_listed_model_passes_the_check(opencode_state: Path, tmp_path: Path) -> None:
    opencode_state.write_text(json.dumps({"models": [MODEL]}))
    agent_models.check(procs.SubprocessRunner(), tmp_path, Model(MODEL))


def test_a_variant_is_looked_up_among_its_models_variants(opencode_state: Path, tmp_path: Path) -> None:
    """A variant its model lacks would fail the run, or run at the default, so canopy looks it up first (§13)."""
    opencode_state.write_text(
        json.dumps({"models": ["a plugin says hello", MODEL, OTHER], "variants": {MODEL: ["low", "high"]}}),
    )
    agent_models.check(procs.SubprocessRunner(), tmp_path, Model(MODEL, "high"))
    with pytest.raises(agent_models.ModelError) as missing:
        agent_models.check(procs.SubprocessRunner(), tmp_path, Model(MODEL, "max"))
    assert missing.value.guard == agent_models.MISSING
    expected = f"lists the model {MODEL} chosen in runtime.models but not its variant max (it lists high, low)"
    assert expected in missing.value.reason
    with pytest.raises(agent_models.ModelError, match="it lists none for it"):
        agent_models.check(procs.SubprocessRunner(), tmp_path, Model(OTHER, "high"))


def test_a_model_not_listed_or_a_list_not_read_is_refused(opencode_state: Path, tmp_path: Path) -> None:
    opencode_state.write_text(json.dumps({"models": ["acme/other"]}))
    with pytest.raises(agent_models.ModelError) as missing:
        agent_models.check(procs.SubprocessRunner(), tmp_path, Model(MODEL))
    assert missing.value.guard == agent_models.MISSING
    opencode_state.write_text(json.dumps({"exit": 1}))
    with pytest.raises(agent_models.ModelError) as failed:
        agent_models.check(procs.SubprocessRunner(), tmp_path, Model(MODEL))
    assert failed.value.guard == agent_models.LIST_FAILED
    assert "`opencode api model.list` exited 1" in failed.value.reason
    with pytest.raises(agent_models.ModelError) as failed:
        agent_models.check(procs.SubprocessRunner(), tmp_path, Model(MODEL, "high"))
    assert "`opencode api model.list` exited 1" in failed.value.reason


CHORE_CMD = "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-chore --format json {prompt}"
OWN_CMD = "opencode run --agent sentry-triage --format json {prompt}"


def chore(**keys: object) -> dict[str, object]:
    """A `[chores.triage]` table, with `keys` added."""
    return {"triage": {"prompt": "~/triage.md", "every_minutes": 60, **keys}}


def test_a_chore_with_a_model_of_its_own_runs_its_own_copy_of_the_chore_agent(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(
        canopy_env.user_file,
        {"runtime": {"models": {"chore": MODEL}}, "chores": chore(model=f"{OTHER}@low")},
    )
    cfg = config.load(canopy_env.root, canopy_env.user_file)
    assert agent_models.by_agent(cfg.runtime.models, {"triage": f"{OTHER}@low"}) == {
        agents.CHORE: Model(MODEL),
        "canopy-chore-triage": Model(OTHER, "low"),
    }
    template = agent_models.chore_template(cfg.runtime.chore_cmd, "triage", f"{OTHER}@low")
    assert "--agent canopy-chore-triage " in template
    assert template.replace("canopy-chore-triage", "canopy-chore") == cfg.runtime.chore_cmd
    # A chore without one runs the chore's agent, on `runtime.models.chore`.
    assert agent_models.chore_template(cfg.runtime.chore_cmd, "triage", None) == cfg.runtime.chore_cmd


@pytest.mark.parametrize(
    ("keys", "error"),
    [
        ({"model": "claude"}, "chores.triage.model: Value error, 'claude' must be a model"),
        # An agent of the operator's own takes its model in its own definition, which canopy does not write.
        ({"model": MODEL, "cmd": OWN_CMD}, "chores.triage: Value error, model needs cmd to run canopy's chore agent"),
        (
            {"model": MODEL, "cmd": "opencode run --agent canopy-chore {prompt}"},
            "chores.triage: Value error, with model, cmd must contain {definitions_dir}",
        ),
        (
            {"model": MODEL, "cmd": f"{CHORE_CMD} --variant high"},
            "chores.triage: Value error, cmd must not pass a model or a variant ('--variant')",
        ),
        # The chore's agent's model is canopy's to choose, `runtime.models.chore`, whether or not it chooses one.
        ({"cmd": f"{CHORE_CMD} -m {MODEL}"}, "Set model in this table instead"),
    ],
)
def test_a_chore_whose_model_and_command_could_disagree_is_refused(
    canopy_env: CanopyEnv,
    keys: dict[str, object],
    error: str,
) -> None:
    canopy_env.configure(canopy_env.user_file, {"chores": chore(**keys)})
    with pytest.raises(ConfigError, match=re.escape(error)):
        config.load(canopy_env.root, canopy_env.user_file)


def test_an_agent_of_the_operators_own_may_take_a_model_on_its_command_line(canopy_env: CanopyEnv) -> None:
    """No model is chosen for it, and canopy records what served it from the session, as before."""
    canopy_env.configure(canopy_env.user_file, {"chores": chore(cmd=f"{OWN_CMD} --model {MODEL}")})
    assert config.load(canopy_env.root, canopy_env.user_file).chores["triage"].cmd == f"{OWN_CMD} --model {MODEL}"


def test_a_chore_model_with_a_chore_cmd_that_runs_another_agent_is_refused(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(
        canopy_env.user_file,
        {
            "runtime": {"chore_cmd": "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent my-chore"},
            "chores": chore(model=MODEL),
        },
    )
    with pytest.raises(ConfigError, match=re.escape("chores.triage.model needs runtime.chore_cmd to run canopy's")):
        config.load(canopy_env.root, canopy_env.user_file)
