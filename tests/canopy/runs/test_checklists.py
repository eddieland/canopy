"""The lists a worker run that may push hears (DESIGN §42): its repositories', written to its answers directory.

A run in a repository without a list, or of a kind that pushes nothing, gets no file; a list canopy cannot use refuses
the run, leasing no slot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from canopy.core import cards, checklists
from canopy.core.vocab import ResumeReason, RunKind
from tests.canopy.helpers import agent_runs, checklists_dir, planner_does, pool_statuses, worker_does
from tests.canopy.scenario_helpers import dispatches

if TYPE_CHECKING:
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import GitPool

#: What the fake agent runs to show the lists it was handed, as canopy's plugin reads them.
SHOW = ["sh", "-c", f'cat "${cards.ANSWERS_ENV}/{checklists.FILE}"']
#: A list of one item.
LIST = "## general-types\npaths: src/\n\nA parameter takes the most general type its body needs.\n"


def shown(agent_log: Path, agent: str = "canopy-worker") -> str | None:
    """What the latest run of `agent` read from its answers directory's lists; None when it had none."""
    [*_, run] = [r for r in agent_runs(agent_log) if agent in cast("list[str]", r["argv"])]
    # Its last command: a planner first writes its plan with one of its own.
    [*_, command] = cast("list[dict[str, object]]", run["commands"])
    return str(command["stdout"]) if command["returncode"] == 0 else None


def test_a_worker_run_hears_its_repositorys_list(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(f"\n{LIST}\n")
    run = scenario.run(worker=worker_does(SHOW))
    assert shown(scenario.agent_log) == f"# repo\n\n{LIST}"
    # The file goes with the run's answers directory.
    assert not cards.answers_dir(scenario.env.state_dir, str(run.id)).exists()


def test_a_run_in_a_repository_without_a_list_gets_no_file(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.run(worker=worker_does(SHOW))
    assert shown(scenario.agent_log) is None
    (checklists_dir(scenario.env) / "other.md").write_text(LIST)
    scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CONFLICT]), worker=worker_does(SHOW))
    assert shown(scenario.agent_log) is None


def test_a_plan_pushes_nothing_and_hears_no_list(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    scenario.run(dispatches(kind=RunKind.PLAN), worker=planner_does(SHOW, plan="# Plan\n\nAdd the button.\n"))
    assert shown(scenario.agent_log, "canopy-planner") is None


def test_a_run_whose_list_canopy_cannot_use_is_refused(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    path = checklists_dir(scenario.env) / "repo.md"
    path.write_text("Our rules.\n\n" + LIST)
    reason = f"the checklist of repo at {path}: line 1: each item opens with a '## <id>' heading"
    # Never run without it: the list is the operator's, and only they can mend it.
    assert scenario.refuses(dispatches()) == [("refused:bad_prompt", reason)]
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    assert pool_statuses(treehouse_state) == ["available", "available"]
    path.write_text(LIST)
    scenario.run(worker=worker_does(SHOW))
    assert shown(scenario.agent_log) == f"# repo\n\n{LIST}"


def test_a_joint_run_hears_each_list_under_its_repository(ws_scenario: Scenario) -> None:
    yours = checklists_dir(ws_scenario.env)
    (yours / "api.md").write_text("## api-rule\nThe api's rule.\n")
    (yours / "web.md").write_text("## web-rule\nThe web's rule.\n")
    ws_scenario.run(dispatches(repo=("api", "web")), worker=worker_does(SHOW))
    assert (
        shown(ws_scenario.agent_log)
        == "# api\n\n## api-rule\nThe api's rule.\n\n# web\n\n## web-rule\nThe web's rule.\n"
    )
