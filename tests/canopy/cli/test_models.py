"""`canopy models` (DESIGN §13, Each agent's model): the models the runtime lists, read from it now in the workspace
root, and the agents `[runtime.models]` gives each; it exits 1 when an agent's runs would be refused their model."""

import json
from pathlib import Path

from tests.canopy.scenario_helpers import Scenario

MODEL = "acme/fake-model-1"
OTHER = "acme/fake-model-2"


def test_canopy_models_lists_each_model_and_the_agents_config_gives_it(
    scenario: Scenario,
    opencode_state: Path,
) -> None:
    opencode_state.write_text(json.dumps({"models": [OTHER, "a plugin says hello", MODEL]}))
    scenario.configures(runtime={"models": {"worker": MODEL, "reviewer": MODEL}})
    assert scenario.operator("models").out == (
        f"OpenCode lists 2 models:\n  {MODEL}  (runtime.models: worker, reviewer)\n  {OTHER}\n"
    )


def test_canopy_models_exits_1_when_an_agents_model_is_not_listed_or_the_list_cannot_be_read(
    scenario: Scenario,
    opencode_state: Path,
) -> None:
    opencode_state.write_text(json.dumps({"models": [OTHER]}))
    scenario.configures(runtime={"models": {"planner": MODEL}})
    assert scenario.operator("models", code=1).out == (
        f"OpenCode lists 1 model:\n  {OTHER}\n"
        f"runtime.models.planner names {MODEL}, which OpenCode does not list: its runs refuse (model_missing).\n"
    )
    opencode_state.write_text(json.dumps({"exit": 1, "stderr": "Error: something broke\n"}))
    assert scenario.operator("models", code=1).out == (
        "could not read the models OpenCode lists (model_list_failed): `opencode models` exited 1\n"
    )
