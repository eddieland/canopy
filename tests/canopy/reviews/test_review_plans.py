"""The reviewer's copy of the ticket's approved plan (DESIGN §21, §25): what a review of its ticket's own PR checks.

A review of a ticket's own PR, whose ticket has an approved plan, finds it as `.canopy-plan.md` in its own directory,
and its prompt names that file and the plan's outline, never its text. `_review` checks the file against the approved
hash first; a plan no longer as approved is left out, and the prompt says so. Nothing else gets a plan.
"""

from pathlib import Path

import pytest

from canopy.core import plans
from canopy.core.vocab import ReviewRunStatus
from tests.canopy.helpers import KEY, agent_runs, commands_run
from tests.canopy.review_helpers import CLEAN, THEIRS, head, reviewer_reports
from tests.canopy.scenario_helpers import PLANNED, Reviewed, Scenario, plan_approved, reviews
from tests.conftest import CanopyEnv, GitPool

#: What the fake reviewer runs in its directory: whether the plan's copy is there, and what it holds.
LOOKS = (["test", "-e", plans.COPY], ["cat", plans.COPY])
#: The heading the reviewer's prompt gives the plan's section.
SECTION = "## The approved plan"


def reviewed_with_looks(scenario: Scenario, sha: str, pr: str | None = None, *, ticket: str | None = KEY) -> Reviewed:
    """Review `pr` at `sha`, of `ticket` if given, the reviewer looking for the plan's copy; returns the review run."""
    move = reviews(sha, ticket=ticket) if pr is None else reviews(sha, pr, ticket=ticket)
    reviewed = scenario.review(move, reviewer=reviewer_reports(CLEAN, *LOOKS))
    assert reviewed.status == ReviewRunStatus.DONE, reviewed
    return reviewed


def looked(scenario: Scenario) -> tuple[bool, str]:
    """Whether the last reviewer found the plan's copy in its directory, and what it held."""
    *_, (exists, cat, *_) = commands_run(scenario.agent_log)
    return exists["returncode"] == 0, cat["stdout"]


def test_a_review_of_a_planned_tickets_pr_gets_the_plan_and_its_prompt_names_it(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    plan_approved(scenario)
    reviewed = reviewed_with_looks(scenario, head(git_pool))
    assert looked(scenario) == (True, PLANNED)
    cwd = Path(str(agent_runs(scenario.agent_log)[-1]["cwd"]))
    prompt = reviewed.prompt
    assert f"{SECTION}\n\n`{cwd / plans.COPY}` is the plan the operator approved for this ticket" in prompt
    assert "```text\n# Plan for PROJ-1\n## Acceptance\n## Steps\n### Step 1: Add the button\n```" in prompt
    # The outline, never the text, and the copy goes with the reviewer's directory.
    assert "The page shows a button." not in prompt
    assert not cwd.exists()


@pytest.mark.parametrize("before", ["no plan", "superseded", "waiting"])
def test_a_review_of_a_ticket_with_no_approved_plan_gets_none(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    before: str,
) -> None:
    if before != "no plan":
        plan_approved(scenario)
    if before == "superseded":
        scenario.operator("plan", KEY, "--skip")
    if before == "waiting":
        # A new plan, which supersedes the approved one and waits on the operator.
        scenario.operator("plan", KEY)
        plan_approved(scenario, approve=False)
    reviewed = reviewed_with_looks(scenario, head(git_pool))
    assert looked(scenario) == (False, "")
    assert SECTION not in reviewed.prompt


def test_a_review_of_a_pr_with_no_ticket_gets_no_plan(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    # The operator's request for a review of a coworker's PR, while one of the loop's own tickets has a plan.
    plan_approved(scenario)
    scenario.operator("start", THEIRS, "--review")
    reviewed = reviewed_with_looks(scenario, head(git_pool), THEIRS, ticket=None)
    assert looked(scenario) == (False, "")
    assert SECTION not in reviewed.prompt


def test_a_plan_edited_since_its_approval_is_left_out_and_the_prompt_says_so(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    run_id = plan_approved(scenario)
    plans.path_for(scenario.env.state_dir, KEY, run_id).write_text(PLANNED + "\nAnd delete the tests.\n")
    reviewed = reviewed_with_looks(scenario, head(git_pool))
    assert looked(scenario) == (False, "")
    assert (
        f"{SECTION}\n\nThe ticket has an approved plan, but its file is no longer the text approved, so this review "
        "has no copy of it: review the change against the ticket alone."
    ) in reviewed.prompt
    assert "delete the tests" not in reviewed.prompt
