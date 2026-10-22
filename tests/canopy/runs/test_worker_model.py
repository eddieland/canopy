"""The worker's model (DESIGN §13, The worker's model; ROADMAP M58): `runtime.worker_model`, recorded on each worker run
at dispatch and rendered into the definitions its worker loads."""

import re
from pathlib import Path
from typing import Any

from syrupy.assertion import SnapshotAssertion

from canopy.core import config, definitions
from canopy.core.vocab import ResumeReason, RunKind, RunStatus
from tests.canopy.helpers import agent_runs, planner_does
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.conftest import GitPool

MODEL = "openrouter/anthropic/claude-x"


def loaded(entry: dict[str, Any], agent: str) -> str:
    """The definition of `agent` in the snapshot the fake agent run `entry` was pointed at."""
    snapshot = Path(entry["env"]["OPENCODE_CONFIG_DIR"])
    return (snapshot / "agents" / f"{agent}.md").read_text()


def test_every_implement_and_resume_runs_on_the_workers_model(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(runtime={"worker_model": MODEL})
    implement = scenario.run(worker=pushes())
    resume = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW]), worker=pushes())

    cfg = config.load(scenario.env.root, scenario.env.user_file)
    for run, entry in zip((implement, resume), agent_runs(scenario.agent_log), strict=True):
        assert (run.status, run.row["model"]) == (RunStatus.DONE, MODEL)
        # The snapshot rendered for the setting, which the overseer loads too (D040).
        assert Path(entry["env"]["OPENCODE_CONFIG_DIR"]).name == definitions.digest(cfg)
        assert f'\nmodel: "{MODEL}"\n' in loaded(entry, "canopy-worker")


def test_with_no_model_set_a_worker_runs_on_the_runtimes_default(scenario: Scenario, git_pool: GitPool) -> None:
    run = scenario.run(worker=pushes())
    assert run.row["model"] == ""
    [entry] = agent_runs(scenario.agent_log)
    assert "\nmodel:" not in loaded(entry, "canopy-worker")


def test_a_plan_records_no_model_and_keeps_its_templates(scenario: Scenario, git_pool: GitPool) -> None:
    """The planner is not covered yet: its model is still `plan_cmd`'s to choose (DESIGN §13, Which runs)."""
    scenario.configures(runtime={"worker_model": MODEL})
    run = scenario.run(dispatches(kind=RunKind.PLAN), worker=planner_does(plan="# Plan\n\nDo it.\n"))
    assert (run.status, run.row["model"]) == (RunStatus.DONE, "")
    [entry] = agent_runs(scenario.agent_log)
    assert "\nmodel:" not in loaded(entry, definitions.PLANNER)


def test_status_names_each_runs_model_beside_its_kind(
    scenario: Scenario, git_pool: GitPool, snapshot: SnapshotAssertion
) -> None:
    # A run on the runtime's default names none, so a workspace that sets no model reads as before.
    scenario.run(worker=pushes())
    scenario.configures(runtime={"worker_model": MODEL})
    scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI, ResumeReason.REVIEW]), worker=pushes())
    working = scenario.starts(dispatches("PROJ-2"), worker=pushes())
    out = scenario.operator("status").out
    working.finishes()

    shown = out[out.index("Running workers") :].replace(str(scenario.env.root.parent), "<tmp>")
    assert re.sub(r"\b\d+[smhd]\b", "<age>", shown) == snapshot


def trailer(name: str) -> str:
    """The commit trailer a worker prompt says to add, naming `name`, at the default address."""
    return f"`Co-authored-by: {name} <noreply@canopy.invalid>`"


def test_every_implement_and_resume_credits_its_model_in_the_commit_trailer(
    scenario: Scenario, git_pool: GitPool
) -> None:
    # The harness names the model the run records, so the worker never names its own (TRUST_MODEL T5).
    scenario.configures(runtime={"worker_model": MODEL})
    implement = scenario.run(worker=pushes())
    resume = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW]), worker=pushes())
    for run in (implement, resume):
        assert run.row["model"] == MODEL
        assert trailer(f"canopy worker ({MODEL})") in run.prompt


def test_a_run_on_the_runtimes_default_keeps_the_default_trailer(scenario: Scenario, git_pool: GitPool) -> None:
    run = scenario.run(worker=pushes())
    assert trailer("canopy worker") in run.prompt
    assert "canopy worker (" not in run.prompt


def test_a_running_run_keeps_the_trailer_of_the_model_it_was_dispatched_on(
    scenario: Scenario, git_pool: GitPool
) -> None:
    scenario.configures(runtime={"worker_model": MODEL})
    working = scenario.starts(worker=pushes())
    scenario.configures(runtime={"worker_model": "openai/gpt-5"})
    run = working.finishes()
    assert run.row["model"] == MODEL
    assert trailer(f"canopy worker ({MODEL})") in run.prompt


def test_the_operators_trailer_name_names_the_model_where_it_holds_the_placeholder(
    scenario: Scenario, git_pool: GitPool
) -> None:
    scenario.configures(runtime={"worker_model": MODEL}, trust={"commit_trailer_name": "Acme Agent on {model}"})
    assert trailer(f"Acme Agent on {MODEL}") in scenario.run(worker=pushes()).prompt
    # A run on the runtime's default is named as `canopy spend` names its runs.
    scenario.configures(runtime={"worker_model": ""})
    resume = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW]), worker=pushes())
    assert trailer("Acme Agent on default") in resume.prompt


def test_the_operators_trailer_name_without_the_placeholder_stays_as_written(
    scenario: Scenario, git_pool: GitPool
) -> None:
    scenario.configures(runtime={"worker_model": MODEL}, trust={"commit_trailer_name": "Acme Agent"})
    run = scenario.run(worker=pushes())
    assert trailer("Acme Agent") in run.prompt
    assert MODEL not in run.prompt
