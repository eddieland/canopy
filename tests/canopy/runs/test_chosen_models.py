"""A worker's or a planner's model (DESIGN §13, Each agent's model): `runtime.models`' for its agent, written into the
agent's definition, recorded on the run, and looked up in the runtime's list before the run starts, never fallen back
from: a model the list lacks, or a list that cannot be read, refuses the run with an attention item, spending no attempt
and leasing no slot. canopy's commit trailer names it, and a worker following an approved plan names its planner's on a
trailer of its own, while the operator has not named the trailer themselves."""

import json
from pathlib import Path

from canopy.core import definitions
from canopy.core.config import load
from canopy.core.vocab import RunKind
from tests.canopy.helpers import KEY, planner_does, pool_statuses
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.conftest import GitPool

MODEL = "acme/fake-model-1"
OTHER = "acme/fake-model-2"
PLAN = dispatches(kind=RunKind.PLAN)


def test_a_run_on_a_chosen_model_records_it_and_its_definition_names_it(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    # A line that is no model, as a plugin may print, is passed over.
    listed(opencode_state, "a plugin says hello", MODEL, OTHER)
    scenario.configures(runtime={"models": {"worker": MODEL}})
    run = scenario.run(worker=pushes())
    assert run.row["model"] == MODEL
    # What the run records is what it ran on: the snapshot made for the config it ran under names the model.
    digest = definitions.digest(load(scenario.env.root, scenario.env.user_file))
    snapshot = scenario.env.root / ".canopy" / definitions.RUNTIME_DIR / digest
    assert f'\nmodel: "{MODEL}"\n' in (snapshot / "agents" / "canopy-worker.md").read_text()
    # The list is read in the workspace root, not in the run's slot, whose own runtime config could change it.
    assert calls(opencode_state) == [(["models"], str(scenario.env.root))]
    assert f"  model {MODEL}  log {run.row['log_path']}\n" in scenario.operator("status").out
    # Its commits credit the model that did the work (TRUST_MODEL T5).
    assert f"`Co-authored-by: {MODEL} (canopy worker) <noreply@canopy.invalid>`" in run.prompt_file.read_text()


def test_a_run_with_no_model_chosen_goes_to_the_runtimes_default_and_reads_no_list(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    run = scenario.run(worker=pushes())
    assert run.row["model"] is None
    assert calls(opencode_state) == []
    assert "  model " not in scenario.operator("status").out
    assert "`Co-authored-by: canopy worker <noreply@canopy.invalid>`" in run.prompt_file.read_text()


def test_a_trailer_name_the_operator_set_is_used_as_set_whatever_the_model(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL)
    scenario.configures(
        runtime={"models": {"worker": MODEL}},
        trust={"commit_trailer_name": "Acme Agent", "commit_trailer_email": "agent@acme.test"},
    )
    prompt = scenario.run(worker=pushes()).prompt_file.read_text()
    assert "`Co-authored-by: Acme Agent <agent@acme.test>`" in prompt
    assert MODEL not in prompt


def test_each_agents_model_reaches_its_runs_and_no_other(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL, OTHER)
    scenario.configures(runtime={"models": {"planner": OTHER}})
    plan = scenario.run(PLAN, worker=planner_does(plan="# Plan for PROJ-1\n\nAdd the button.\n"))
    assert plan.row["model"] == OTHER
    scenario.operator("plan", KEY, "--skip")
    assert scenario.run(worker=pushes()).row["model"] is None


def test_a_worker_following_an_approved_plan_credits_the_planners_model_and_its_own(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL, OTHER)
    scenario.configures(runtime={"models": {"planner": OTHER, "worker": MODEL}})
    scenario.run(PLAN, worker=planner_does(plan="# Plan for PROJ-1\n\nAdd the button.\n"))
    scenario.operator("plan", KEY, "--approve")
    prompt = scenario.run(worker=pushes()).prompt_file.read_text()
    assert f"`Co-authored-by: {MODEL} (canopy worker) <noreply@canopy.invalid>`" in prompt
    assert f"`Co-authored-by: {OTHER} (canopy planner) <noreply@canopy.invalid>`" in prompt


def test_a_model_the_runtime_does_not_list_is_refused_with_an_attention_item(
    scenario: Scenario,
    opencode_state: Path,
    treehouse_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, OTHER)
    scenario.configures(runtime={"models": {"worker": MODEL}})
    reason = (
        f"OpenCode does not list the model {MODEL} chosen in runtime.models, so a run on it would fail before its "
        "first call; nothing ran on another model. Choose a model it lists, or set up its provider"
    )
    # Never the runtime's default instead: a canary's run on a model nobody chose would read as the canary's.
    refused = scenario.refuses(dispatches())
    assert refused == [("refused:model_missing", reason), ("attention:model_missing", reason)]
    assert scenario.attention() == [(KEY, "model_missing")]
    # No attempt spent and no slot leased.
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    assert pool_statuses(treehouse_state) == ["available", "available"]
    # A dry run refuses it as a live tick would.
    dry = scenario.refuses(dispatches(), dry_run=True)
    assert dry == [("refused:model_missing", reason), ("attention:model_missing", reason)]
    listed(opencode_state, OTHER, MODEL)
    assert scenario.run(worker=pushes()).row["model"] == MODEL


def test_a_list_that_cannot_be_read_refuses_the_run(scenario: Scenario, opencode_state: Path) -> None:
    opencode_state.write_text(json.dumps({"exit": 1, "stderr": "Error: something broke\n"}))
    scenario.configures(runtime={"models": {"worker": MODEL}})
    reason = (
        f"could not look up the model {MODEL} chosen in runtime.models: `opencode models` exited 1. Nothing ran on "
        "another model; the work resumes once the list can be read"
    )
    refused = scenario.refuses(dispatches())
    assert refused == [("refused:model_list_failed", reason), ("attention:model_list_failed", reason)]
    assert scenario.attention() == [(KEY, "model_list_failed")]
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def listed(state: Path, *lines: str) -> None:
    """Have the fake `opencode models` print `lines`."""
    state.write_text(json.dumps({"models": list(lines)}))


def calls(state: Path) -> list[tuple[list[str], str]]:
    """Each `opencode models` the fake ran, with the directory it ran in."""
    log = state.with_name("opencode.jsonl")
    if not log.exists():
        return []
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    return [(e["argv"], e["cwd"]) for e in entries if e["argv"] == ["models"]]
