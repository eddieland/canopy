"""The lists a worker run that may push hears (DESIGN §42): its repositories', each written to its answers directory.

A run in a repository without a list, or of a kind that pushes nothing, gets no file; a list canopy cannot use refuses
the run, leasing no slot. What the run answered of each item is recorded with it, and `canopy show run:ID` shows it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from canopy.core import cards, checklist_answers, checklists, contract, records
from canopy.core.vocab import ItemAnswer, ResumeReason, RunKind, RunStatus
from tests.canopy.helpers import (
    agent_runs,
    checklists_dir,
    planner_does,
    pool_statuses,
    worker_does,
    worker_result,
)
from tests.canopy.scenario_helpers import dispatches

if TYPE_CHECKING:
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import GitPool

#: What the fake agent runs to show the lists it was handed, as canopy's hook reads them, each repository's in turn.
SHOW = ["sh", "-c", f'cat "${cards.ANSWERS_ENV}/{checklists.DIR}"/*{checklists.SUFFIX}']
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
    assert shown(scenario.agent_log) == LIST
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
    assert shown(scenario.agent_log) == LIST


def test_a_joint_run_hears_each_list_under_its_repository(ws_scenario: Scenario) -> None:
    yours = checklists_dir(ws_scenario.env)
    (yours / "api.md").write_text("## api-rule\nThe api's rule.\n")
    (yours / "web.md").write_text("## web-rule\nThe web's rule.\n")
    ws_scenario.run(dispatches(repo=("api", "web")), worker=worker_does(SHOW))
    assert shown(ws_scenario.agent_log) == "## api-rule\nThe api's rule.\n## web-rule\nThe web's rule.\n"


def test_a_runs_answers_are_recorded_and_shown(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(f"{LIST}\n## newspaper\n\nPublic names first.\n")
    held = {"answer": "held", "reason": "The helper\u202e stays where it is."}
    answered = {"repo": {"general-types": "fixed", "newspaper": held, "made-up": "pass"}, "other": {"x": "pass"}}
    run = scenario.run(worker=worker_does(result=worker_result(checklist=answered)))
    # An answer to an item or a repository its lists do not hold is dropped, and the run's result kept.
    assert run.status == RunStatus.DONE
    assert checklist_answers.of_run(scenario.conn, run.id) == [
        records.ChecklistAnswer(run.id, "repo", "general-types", ItemAnswer.FIXED, None, None),
        records.ChecklistAnswer(
            run.id,
            "repo",
            "newspaper",
            ItemAnswer.HELD,
            "The helper\u202e stays where it is.",
            None,
        ),
    ]
    note = contract.stored_note(contract.stored_object(run.row["result_json"]))
    assert note == "checklist answers dropped: 'other': no list of the run's; repo 'made-up': not an item of its list"
    shown = scenario.operator("show", f"run:{run.id}").out
    # The reason is the worker's text: printed under its item, made printable as a message is.
    assert "\nChecklist:\n  repo  general-types  fixed\n  repo  newspaper  held\n    The helper  stays" in shown


def test_the_prompt_says_a_push_may_be_held_only_with_a_list(scenario: Scenario, git_pool: GitPool) -> None:
    run = scenario.run()
    assert "Push held" not in run.prompt
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    run = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CONFLICT]))
    assert "The operator keeps a checklist for `repo`" in run.prompt
    assert '"checklist":{"<repository>":' in run.prompt


def test_a_run_that_answers_nothing_is_recorded_unanswered(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    run = scenario.run(worker=worker_does(result="not a result"))
    # Its push, if it made one, is made: never refused for want of answers, and counted against the item.
    assert [(a.item, a.answer) for a in checklist_answers.of_run(scenario.conn, run.id)] == [
        ("general-types", ItemAnswer.UNANSWERED),
    ]
    # A run given no list records none.
    (checklists_dir(scenario.env) / "repo.md").unlink()
    run = scenario.run(worker=worker_does(result=worker_result(checklist={"repo": {"general-types": "pass"}})))
    assert checklist_answers.of_run(scenario.conn, run.id) == []


def test_canopy_checklist_counts_what_the_runs_answered(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(f"{LIST}\n## newspaper\n\nPublic names first.\n")
    held = {"answer": "held", "reason": "The helper stays where it is."}
    scenario.run(worker=worker_does(result=worker_result(checklist={"repo": {"general-types": "fixed"}})))
    scenario.run(worker=worker_does(result=worker_result(checklist={"repo": {"newspaper": held}})))
    found = json.loads(scenario.operator("checklist", "--json").out)
    # A run's reason for holding an item is its own, on its run: the counts say only how many.
    assert found["items"] == [
        {
            "repo": "repo",
            "item": "general-types",
            "reminded": 2,
            "pass": 0,
            "fixed": 1,
            "held": 0,
            "n/a": 0,
            "unanswered": 1,
        },
        {
            "repo": "repo",
            "item": "newspaper",
            "reminded": 2,
            "pass": 0,
            "fixed": 0,
            "held": 1,
            "n/a": 0,
            "unanswered": 1,
        },
    ]
    assert scenario.operator("checklist", "--repo", "other").out.endswith(
        "\n\nNo worker run of the window was given a list.\n",
    )
