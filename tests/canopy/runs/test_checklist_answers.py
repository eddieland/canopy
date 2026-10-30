"""What a worker run given its repositories' checklists answered of each item (DESIGN §42), as `_run` records it.

Every item of every list the run was given gets a row: the worker's answer, or `unanswered` for one its result answers
nothing canopy can record. An answer under a repository or an item the lists do not hold is dropped, and one canopy
refuses costs the run nothing but that answer. A run given no list records nothing, whatever its result says.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from canopy.core import checklist_answers, records
from tests.canopy.helpers import WORKER_DONE, checklists_dir, worker_does, worker_result
from tests.canopy.scenario_helpers import dispatches

if TYPE_CHECKING:
    from tests.canopy.scenario_helpers import Ran, Scenario
    from tests.conftest import GitPool

#: A list of three items, as the operator writes them.
THREE = (
    "## general-types\nA parameter takes the most general type its body needs.\n\n"
    "## newspaper\nA module reads top-down.\n\n"
    "## doc-comments\nA name's comment is a `#:` doc comment.\n"
)
#: What the prompt of a run given `repo`'s list tells its worker of a held push.
TOLD = "canopy may hold your first push in `repo` for that repository's checklist, which it prints"


def answered(scenario: Scenario, run_id: int) -> dict[tuple[str, str], tuple[str, str | None]]:
    """What run `run_id` answered of each item it was given, by repository and item."""
    rows = records.select(records.ChecklistAnswer).where("run_id = ?", run_id).all(scenario.conn)
    return {(row.repo, row.item): (row.answer, row.reason) for row in rows}


def harness_note(run: Ran) -> str:
    """The harness's note on how `run` ended."""
    return str(json.loads(run.row["result_json"]).get("harness", ""))


def test_a_workers_answers_to_its_list_are_recorded(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(THREE)
    checklist = {
        "repo": {
            "general-types": "fixed",
            "newspaper": {"answer": "held", "reason": "The module is old;\nreordering it is a PR of its own."},
            "doc-comments": {"answer": "n/a"},
        },
    }
    run = scenario.run(worker=worker_does(result=worker_result(checklist=checklist)))
    assert run.status == "done"
    assert TOLD in run.prompt
    assert answered(scenario, run.id) == {
        ("repo", "general-types"): ("fixed", None),
        ("repo", "newspaper"): ("held", "The module is old; reordering it is a PR of its own."),
        ("repo", "doc-comments"): ("n/a", None),
    }
    assert harness_note(run) == ""
    # Kept beside the result, not in it, so nothing that reads the result, the overseer's state among it, reads them.
    assert "checklist" not in json.loads(run.row["result_json"])


def test_an_answer_the_lists_do_not_hold_is_dropped_and_a_bad_one_left_unanswered(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(THREE)
    checklist = {
        "repo": {
            "general-types": {"answer": "held", "reason": "x" * 2000},
            "newspaper": "maybe",
            "doc-comments": "held",
            "made-up": "pass",
        },
        "elsewhere": {"general-types": "pass"},
    }
    run = scenario.run(worker=worker_does(result=worker_result(checklist=checklist)))
    # A bad answer costs the run nothing but that answer: its push is already made.
    assert run.status == "done"
    answers = answered(scenario, run.id)
    assert set(answers) == {("repo", "general-types"), ("repo", "newspaper"), ("repo", "doc-comments")}
    held, reason = answers["repo", "general-types"]
    assert held == "held"
    assert reason is not None
    assert len(reason) == checklist_answers.MAX_REASON
    assert reason.endswith("...")
    assert answers["repo", "newspaper"] == ("unanswered", None)
    assert answers["repo", "doc-comments"] == ("unanswered", None)
    note = harness_note(run)
    assert note == (
        "checklist answers not recorded: item newspaper of repo: not pass, fixed, held with a reason, or n/a; "
        "item doc-comments of repo: held, with no reason; "
        "answers under a repository or an item the run's lists do not hold: 2"
    )
    # The names the worker made up are its own text, which the note does not repeat.
    assert "made-up" not in note
    assert "elsewhere" not in note


@pytest.mark.parametrize("result", [WORKER_DONE, "not a result"], ids=["no checklist", "no result"])
def test_a_reminded_run_that_answers_nothing_is_recorded_unanswered(
    scenario: Scenario,
    git_pool: GitPool,
    result: str,
) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(THREE)
    run = scenario.run(worker=worker_does(result=result))
    answers = answered(scenario, run.id)
    assert len(answers) == len(["general-types", "newspaper", "doc-comments"])
    assert set(answers.values()) == {("unanswered", None)}
    assert "checklist" not in harness_note(run)


def test_a_checklist_that_is_not_answers_by_repository_leaves_every_item_unanswered(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(THREE)
    run = scenario.run(worker=worker_does(result=worker_result(checklist=["pass", "pass", "pass"])))
    assert run.status == "done"
    assert set(answered(scenario, run.id).values()) == {("unanswered", None)}
    assert harness_note(run) == "checklist answers not recorded: checklist is not an object"


def test_a_run_without_a_list_ignores_the_answers(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "other.md").write_text(THREE)
    run = scenario.run(worker=worker_does(result=worker_result(checklist={"repo": {"general-types": "pass"}})))
    assert run.status == "done"
    assert "canopy may hold your first push" not in run.prompt
    assert answered(scenario, run.id) == {}
    assert harness_note(run) == ""


def test_a_joint_runs_answers_are_kept_under_each_repository(ws_scenario: Scenario) -> None:
    yours = checklists_dir(ws_scenario.env)
    (yours / "api.md").write_text("## api-rule\nThe api's rule.\n")
    (yours / "web.md").write_text("## web-rule\nThe web's rule.\n")
    checklist = {"api": {"api-rule": "pass", "web-rule": "pass"}, "web": {"web-rule": "fixed"}}
    run = ws_scenario.run(
        dispatches(repo=("api", "web")),
        worker=worker_does(result=json.dumps({"status": "done", "summary": "did it", "checklist": checklist})),
    )
    assert "canopy may hold your first push in `api` and `web` for that repository's checklist" in run.prompt
    assert answered(ws_scenario, run.id) == {("api", "api-rule"): ("pass", None), ("web", "web-rule"): ("fixed", None)}
    # `web-rule` is web's, not api's.
    assert harness_note(run).endswith("answers under a repository or an item the run's lists do not hold: 1")
