"""`canopy models` (DESIGN §13, Each agent's model): the models the runtime lists, and the agents given each.

The list is read from the runtime now, in the workspace root, and the agents are those `[runtime.models]` gives each
model. It exits 1 when an agent's runs would be refused their model.
"""

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
        "could not read the models OpenCode lists (model_list_failed): `opencode models --verbose` exited 1\n"
    )


def test_canopy_models_reads_a_variant_as_dispatch_does(scenario: Scenario, opencode_state: Path) -> None:
    """A model named at a variant it lists is listed, and one at a variant it does not list is refused."""
    opencode_state.write_text(json.dumps({"models": [OTHER, MODEL], "variants": {MODEL: ["xhigh", "high"]}}))
    scenario.configures(runtime={"models": {"worker": f"{MODEL}@high", "reviewer": f"{MODEL}@xhigh", "chore": OTHER}})
    assert scenario.operator("models").out == (
        f"OpenCode lists 2 models:\n  {MODEL}  variants: high, xhigh  (runtime.models: worker@high, reviewer@xhigh)\n"
        f"  {OTHER}  (runtime.models: chore)\n"
    )
    scenario.configures(runtime={"models": {"reviewer": f"{MODEL}@bogus", "chore": f"{OTHER}@high"}})
    assert scenario.operator("models", code=1).out == (
        f"OpenCode lists 2 models:\n  {MODEL}  variants: high, xhigh  (runtime.models: worker@high, reviewer@bogus)\n"
        f"  {OTHER}  (runtime.models: chore@high)\n"
        f"runtime.models.reviewer names {MODEL}@bogus, whose variant bogus OpenCode does not list (it lists high, "
        "xhigh): its runs refuse (model_missing).\n"
        f"runtime.models.chore names {OTHER}@high, whose variant high OpenCode does not list (it lists none for it): "
        "its runs refuse (model_missing).\n"
    )


def test_canopy_models_asks_opencode_2_its_own_way(scenario: Scenario, opencode_state: Path) -> None:
    # A line that names no model, as OpenCode 1 could print one, is in no list OpenCode 2 answers with.
    opencode_state.write_text(json.dumps({"models": [OTHER, "a plugin says hello", MODEL]}))
    scenario.configures(runtime={"version": 2, "models": {"worker": MODEL}})
    assert scenario.operator("models").out == (
        f"OpenCode lists 2 models:\n  {MODEL}  (runtime.models: worker)\n  {OTHER}\n"
    )
    opencode_state.write_text(json.dumps({"exit": 1, "stderr": "Error: something broke\n"}))
    assert scenario.operator("models", code=1).out == (
        "could not read the models OpenCode lists (model_list_failed): `opencode api model.list` exited 1\n"
    )
