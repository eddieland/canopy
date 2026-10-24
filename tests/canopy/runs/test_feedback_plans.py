"""Plans before feedback runs (DESIGN §32, ROADMAP M54): the feedback plan run, its gate on `resume`, and approval."""

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.core import conversation, db, drafts, feedback_items, feedback_plans, plans
from canopy.core.config import load
from canopy.core.vocab import (
    DraftStatus,
    PlanEffort,
    PlanItem,
    PlanStatus,
    Proposal,
    ResumeReason,
    RunKind,
    RunStatus,
)
from canopy.infra import resources
from tests.canopy.helpers import (
    DRAFTS_PR,
    KEY,
    agent_runs,
    commands_run,
    comment,
    context,
    github_has,
    personas_dir,
    plan_file,
    planner_does,
    present,
    reads,
    thread,
    waits,
)
from tests.canopy.scenario_helpers import ALICES_COMMENT as ALICE
from tests.canopy.scenario_helpers import (
    BLOCKER_BRANCH,
    BLOCKER_PR,
    Scenario,
    dispatches,
    fails,
    feedback_planned,
    github_shows,
    github_stacked,
    pushes,
    sends_drafts,
    with_a_blocker,
    with_a_pr,
)
from tests.canopy.scenario_helpers import BOBS_COMMENT as BOB
from tests.canopy.scenario_helpers import FEEDBACK_HEAD as HEAD
from tests.canopy.scenario_helpers import FEEDBACK_PLANNED as PLANNED
from tests.canopy.scenario_helpers import FEEDBACK_RED as RED
from tests.canopy.scenario_helpers import FEEDBACK_TEXT as TEXT
from tests.canopy.web_helpers import signed_in_client
from tests.conftest import CanopyEnv

PR = DRAFTS_PR
FEEDBACK_PLAN = dispatches(kind=RunKind.FEEDBACK_PLAN)
RESUME = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW])
#: The reply the planner proposes for bob's comment, as FEEDBACK_PLANNED has it.
PLANNED_REPLY = "Kept, since the API needs it."


@pytest.mark.usefixtures("git_pool")
def test_a_resume_waits_on_a_feedback_plan_the_operator_approved_and_goes_ahead_once(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn, env = scenario.conn, scenario.env
    with_a_pr(scenario)
    scenario.polls()
    assert scenario.refuses(RESUME)[0][0] == "refused:unplanned"

    run_id = feedback_planned(scenario, github_state)
    # The planner read the PR whole first, at its head, in a desk: alice's and bob's comments alike, with their trust.
    assert reads(github_state)[-1] == {"prs": [PR]}
    planner = agent_runs(scenario.agent_log)[-1]
    assert planner["argv"][:3] == ["run", "--agent", "canopy-planner"]
    assert planner["cwd"] == str(env.root / "desks" / KEY)
    [*_, [_, cat]] = commands_run(scenario.agent_log)
    given = json.loads(cat["stdout"])
    assert [(i["id"], i["author"], i["trusted"], i["body"]) for i in given[:2]] == [
        (501, "alice", True, "Rename this."),
        (502, "bob", False, "Drop this argument."),
    ]
    # `build`, red at the head, is an item too, by the id canopy gave it; this planner leaves it for the next plan.
    build = feedback_items.check_id(PR, HEAD, "build")
    assert given[2:] == [
        {
            "id": build,
            "pr": PR,
            "item": "check",
            "head_sha": HEAD,
            "name": "build",
            "conclusion": "failure",
            "url": None,
        },
    ]
    # The id it was never given is refused with a note; the rest are the plan's items.
    [plan] = feedback_plans.history(conn, KEY)
    assert (plan.run_id, plan.status, plan.spent_run_id) == (run_id, PlanStatus.PROPOSED, None)
    assert plan_file(env, run_id).read_text() == TEXT
    assert [(i.number, i.item, i.item_id, i.proposal, i.reply) for i in feedback_plans.items(conn, plan.id)] == [
        (1, PlanItem.COMMENT, 501, Proposal.CHANGE, "Renamed."),
        (2, PlanItem.COMMENT, 502, Proposal.DECLINE, "Kept, since the API needs it."),
    ]
    result = json.loads(present(conn.execute("SELECT result_json FROM runs WHERE id = ?", (run_id,)).fetchone())[0])
    assert result["harness"] == (
        "the plan named items its reader did not give it, left out of the plan: 999, which is no item of its PRs"
    )
    # A plan run pushed nothing and left the ticket's branch and unit as they were.
    assert scenario.refuses(RESUME)[0][0] == "refused:unplanned"

    approved = scenario.operator("plan", KEY, "--approve")
    assert f"Feedback plan {plan.id} of {KEY}, covering 2 items, is approved whole" in approved.out
    # A reply on the ticket after the approval asks for no change of the plan approved.
    scenario.operator("reply", KEY, "Thanks.")
    assert feedback_plans.changes_asked(conn, present(db.get_ticket(conn, KEY))) is None
    resume = scenario.run(RESUME, worker=pushes())
    assert resume.status == RunStatus.DONE
    assert resume.row["feedback_plan_id"] == plan.id
    assert resume.row["plan_id"] is None
    assert "is the feedback plan the operator approved for this round of the PR's feedback" in resume.prompt
    assert f"1. id 501, on {PR}: change\n2. id 502, on {PR}: decline" in resume.prompt
    assert present(feedback_plans.get(conn, plan.id)).spent_run_id == resume.id

    # One approval goes ahead once: the next round waits on a plan of its own, and the items handled leave the next.
    [(action, reason)] = scenario.refuses(RESUME)
    assert action == "refused:unplanned"
    assert f"feedback plan {plan.id} went ahead with run {resume.id} already" in reason
    trust = load(env.root, env.user_file).trust
    assert feedback_items.offered(conn, trust, KEY, [PR]) == []


@pytest.mark.usefixtures("git_pool")
def test_a_resume_that_fails_hands_its_items_back_to_the_next_plan(scenario: Scenario, github_state: Path) -> None:
    # The approval is spent when the resume is recorded, before its worker does anything: a resume that fails has
    # handled nothing, so the next plan is offered its items again rather than none (DESIGN §32).
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    scenario.operator("plan", KEY, "--approve")
    resume = scenario.run(RESUME, worker=fails())
    assert resume.status == RunStatus.FAILED
    trust = load(scenario.env.root, scenario.env.user_file).trust
    assert [o.id for o in feedback_items.offered(conn, trust, KEY, [PR])] == [501, 502]


@pytest.mark.usefixtures("git_pool")
def test_a_resume_starts_its_drafts_from_the_plan_and_canopy_marks_those_that_depart(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    scenario.operator("plan", KEY, "--approve")
    # alice's draft is the plan's reply but for a trailing space, naming a later comment on her thread, which matches
    # it to her item; bob's departs, its text the run's own.
    github_shows(github_state, ALICE, comment(503, author="me", body="On it."), BOB)
    entries = [thread(503, text="Renamed. "), thread(502, did="declined", text="Kept: the CLI needs it.")]
    resume = scenario.run(RESUME, worker=sends_drafts(entries))
    assert resume.status == RunStatus.DONE
    # The prompt gave each approved item's proposed reply, as data, to start its draft from.
    assert "Start the item's draft on its thread from it" in resume.prompt
    assert "Item 1 (id 501):\n\n```text\nRenamed.\n```" in resume.prompt
    assert "Item 2 (id 502):\n\n```text\nKept, since the API needs it.\n```" in resume.prompt
    found = drafts.of_run(conn, resume.id)
    assert [(d.comment_id, d.plan_item, d.status) for d in found] == [
        (503, 1, DraftStatus.WAITING),
        (502, 2, DraftStatus.WAITING),
    ]
    same, departs = (present(drafts.from_plan(conn, d)) for d in found)
    assert (same.number, same.item_id, same.proposal, same.departs) == (1, 501, Proposal.CHANGE, False)
    assert (departs.number, departs.reply, departs.departs) == (2, "Kept, since the API needs it.", True)

    shown = scenario.operator("draft", "show", f"run:{resume.id}").out
    assert "as feedback plan item 1 (id 501), change proposed it" in shown
    assert (
        "changed from the plan: feedback plan item 2 (id 502), decline, proposed this reply:\n"
        "    | Kept, since the API needs it."
    ) in shown
    ctx = context(scenario.env)
    db.migrate(ctx.conn, resources.migrations_dir())
    c, _ = signed_in_client(ctx)
    response = c.get("/api/pull-request/threads", params={"url": PR})
    assert response.status_code == 200, response.text
    plans_of = [[d["from_plan"] for d in t["drafts"]] for t in response.json()["threads"]]
    assert plans_of == [
        [{"number": 1, "item_id": 501, "proposal": "change", "reply": "Renamed.", "left_out": False, "departs": False}],
        [
            {
                "number": 2,
                "item_id": 502,
                "proposal": "decline",
                "reply": "Kept, since the API needs it.",
                "left_out": False,
                "departs": True,
            },
        ],
    ]


@pytest.mark.usefixtures("git_pool")
def test_a_draft_departs_from_the_plan_by_what_it_did_and_for_an_item_the_approval_left_out(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    scenario.operator("plan", KEY, "--approve", "--leave", "2")
    entries = [thread(501, did="declined", text="Renamed."), thread(502, did="declined", text=PLANNED_REPLY)]
    resume = scenario.run(RESUME, worker=sends_drafts(entries))
    # Only the item approved has its reply in the prompt.
    assert "Item 1 (id 501):" in resume.prompt
    assert "Item 2 (id 502):" not in resume.prompt
    said, left = (present(drafts.from_plan(conn, d)) for d in drafts.of_run(conn, resume.id))
    assert (said.departs, left.left_out, left.departs) == (True, True, True)
    shown = scenario.operator("draft", "show", f"run:{resume.id}").out
    assert "feedback plan item 2 (id 502), decline, which your approval left out, proposed this reply:" in shown


@pytest.mark.usefixtures("git_pool")
def test_a_resume_that_posts_its_replies_is_given_none_of_the_plans(scenario: Scenario, github_state: Path) -> None:
    with_a_pr(scenario)
    scenario.configures("private", trust={"review_replies": "post"})
    feedback_planned(scenario, github_state)
    scenario.operator("plan", KEY, "--approve")
    resume = scenario.run(RESUME, worker=pushes())
    assert "1. id 501, on" in resume.prompt
    assert "The plan proposed a reply" not in resume.prompt


@pytest.mark.usefixtures("git_pool")
def test_a_resume_for_no_pr_alone_waits_on_no_plan(scenario: Scenario) -> None:
    scenario.run(dispatches(slug="work"), worker=pushes(prs={"repo": None}))
    scenario.configures("private", policy={"feedback_plan": "approve"})
    run = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.NO_PR]), worker=pushes())
    assert run.status == RunStatus.DONE
    assert run.row["feedback_plan_id"] is None


@pytest.mark.usefixtures("git_pool")
def test_off_plans_no_feedback_and_resumes_as_before(scenario: Scenario, github_state: Path) -> None:
    with_a_pr(scenario, approve=False)
    assert scenario.refuses(FEEDBACK_PLAN) == [
        ("refused:feedback_plan_off", 'policy.feedback_plan is not "approve": a resume goes ahead without a plan'),
    ]
    # A trusted reviewer's comment, observed, is then what authorizes the resume, as before plans (D089).
    scenario.configures("private", trust={"trusted_reviewers": ["alice"]})
    github_has(github_state, comment(501))
    scenario.polls()
    covered = {"review": comment(501)["time"]}
    run = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW], cursors=covered), worker=pushes())
    assert run.status == RunStatus.DONE
    assert run.row["feedback_plan_id"] is None
    assert "feedback plan" not in run.prompt


@pytest.mark.usefixtures("git_pool")
def test_a_waiting_plan_is_planned_again_only_once_the_operator_asks_for_changes(
    scenario: Scenario,
    github_state: Path,
) -> None:
    with_a_pr(scenario)
    first = feedback_planned(scenario, github_state)
    [plan] = feedback_plans.history(scenario.conn, KEY)
    assert scenario.refuses(FEEDBACK_PLAN) == [
        (
            "refused:bad_plan",
            (
                f"feedback plan {plan.id} of {KEY} waits on the operator, who has asked for no change, and nothing "
                "changed on its PRs since it was written"
            ),
        ),
    ]
    scenario.operator("reply", KEY, "Accept bob's point instead.")
    planner = planner_does(["cat", plans.REPLACED], plan="# Feedback plan, again\n", result={"status": "done"})
    again = scenario.run(FEEDBACK_PLAN, worker=planner)
    assert again.status == RunStatus.DONE
    # It read the plan it replaces, and supersedes it.
    [*_, [_, cat]] = commands_run(scenario.agent_log)
    assert cat["stdout"] == TEXT
    assert [(p.run_id, p.status) for p in feedback_plans.history(scenario.conn, KEY)] == [
        (first, PlanStatus.SUPERSEDED),
        (again.id, PlanStatus.PROPOSED),
    ]
    assert "Accept bob's point instead." in again.prompt


@pytest.mark.usefixtures("git_pool")
def test_a_plan_changed_since_its_approval_is_approved_again_before_its_resume(
    scenario: Scenario,
    github_state: Path,
) -> None:
    with_a_pr(scenario)
    run_id = feedback_planned(scenario, github_state)
    scenario.operator("plan", KEY, "--approve")
    assert scenario.refuses(FEEDBACK_PLAN)[0][0] == "refused:bad_plan"
    plan_file(scenario.env, run_id).write_text(TEXT + "\nAnd the docs.\n")
    [(action, reason)] = scenario.refuses(RESUME)
    assert action == "refused:plan_changed"
    assert "is no longer the text the operator approved; they approve it again" in reason
    scenario.operator("plan", KEY, "--approve")
    resume = scenario.run(RESUME, worker=pushes())
    assert resume.status == RunStatus.DONE
    printed = scenario.operator("plan", KEY, "--approve", code=1)
    assert "has no plan waiting to be approved" in printed.err or "went ahead" in printed.err


@pytest.mark.usefixtures("git_pool")
def test_feedback_plans_are_limited_per_unit_and_granted_by_the_operator(
    scenario: Scenario,
    github_state: Path,
) -> None:
    with_a_pr(scenario)
    scenario.configures("workspace", policy={"max_feedback_plan_attempts": 1})
    github_has(github_state, comment(501))
    failed = {"status": "failed", "summary": "cannot plan this"}
    assert scenario.run(FEEDBACK_PLAN, worker=planner_does(plan=None, result=failed)).status == RunStatus.FAILED
    assert scenario.refuses(FEEDBACK_PLAN)[0] == (
        "refused:attempt_limit",
        f"{KEY} in repo has had 1 feedback-plan runs and the limit is 1",
    )
    granted = scenario.operator("grant", KEY, "feedback-plan")
    assert "has had 1 feedback-plan runs, and may now have 2" in granted.out
    assert scenario.run(FEEDBACK_PLAN, worker=planner_does(plan=TEXT)).status == RunStatus.DONE


@pytest.mark.usefixtures("git_pool")
def test_a_feedback_plan_needs_a_pr(scenario: Scenario) -> None:
    scenario.run(dispatches(slug="work"), worker=pushes(prs={"repo": None}))
    scenario.configures("private", policy={"feedback_plan": "approve"})
    assert scenario.refuses(FEEDBACK_PLAN) == [
        ("refused:bad_plan", f"{KEY} has no PR recorded in repo: a feedback plan plans what came back to a PR"),
    ]


def test_a_feedback_plan_needs_a_branch(scenario: Scenario, treehouse_state: Path) -> None:
    scenario.configures("private", policy={"feedback_plan": "approve"})
    assert scenario.refuses(FEEDBACK_PLAN)[0][0] == "refused:no_branch"


@pytest.mark.usefixtures("git_pool")
def test_the_state_block_carries_the_feedback_plan_only_while_feedback_plans_touch_the_ticket(
    scenario: Scenario,
    github_state: Path,
) -> None:
    with_a_pr(scenario, approve=False)
    scenario.seen()
    scenario.tick(*waits(KEY), dry_run=True)
    assert "feedback_plan" not in scenario.ticket_state()

    scenario.configures("private", policy={"feedback_plan": "approve"})
    feedback_planned(scenario, github_state)
    [plan] = feedback_plans.history(scenario.conn, KEY)
    scenario.tick(*waits(KEY), dry_run=True)
    assert scenario.ticket_state()["feedback_plan"] == {
        "needed": True,
        "attempts": {"repo": 1},
        "limits": {"repo": 6},
        "newest": {
            "id": plan.id,
            "status": "proposed",
            "created_at": plan.created_at,
            "repos": ["repo"],
            "spent": False,
            "stale": False,
            "quiet_passed": True,
        },
        "changes_asked": False,
        "blocked": False,
    }


@pytest.mark.usefixtures("git_pool")
def test_a_feedback_plan_takes_no_persona_so_an_unusable_one_refuses_it_not(
    scenario: Scenario,
    github_state: Path,
) -> None:
    # DESIGN §31: a feedback plan's prompt carries no persona, so a `canopy.md` of the operator's that canopy will not
    # use leaves it be, while it refuses a worker's run, whose prompt takes it in.
    with_a_pr(scenario)
    (personas_dir(scenario.env) / "canopy.md").write_text("Be kind.\u200b\n")
    run = present(db.get_run(scenario.conn, feedback_planned(scenario, github_state)))
    assert (run["persona"], run["persona_digest"]) == (None, None)
    [(refused, _), (raised, _)] = scenario.refuses(dispatches("PROJ-2"))
    assert (refused, raised) == ("refused:bad_persona", "attention:bad_persona")


@pytest.mark.usefixtures("git_pool")
def test_the_feedback_planner_prompt(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    github_state: Path,
    markdown_snapshot: SnapshotAssertion,
) -> None:
    """The feedback planner's prompt, whole, so a change to its wording or to what fills it in is a diff in review."""
    with_a_pr(scenario)
    run_id = feedback_planned(scenario, github_state)
    prompt = (canopy_env.state_dir / "runs" / f"{run_id}.prompt").read_text()
    prompt = re.sub(r"\d{4}-\d\d-\d\dT[\d:.]+Z", "<time>", prompt.replace(str(canopy_env.root), "/workspace"))
    assert prompt == markdown_snapshot


@pytest.mark.usefixtures("git_pool")
def test_the_feedback_planner_prompt_when_it_may_approve_its_plan(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    github_state: Path,
    markdown_snapshot: SnapshotAssertion,
) -> None:
    """The same prompt under `policy.planner_may_approve`, whole: how it says a plan needs no review (DESIGN §25)."""
    with_a_pr(scenario)
    scenario.configures("private", policy={"planner_may_approve": True})
    run_id = feedback_planned(scenario, github_state)
    prompt = (canopy_env.state_dir / "runs" / f"{run_id}.prompt").read_text()
    prompt = re.sub(r"\d{4}-\d\d-\d\dT[\d:.]+Z", "<time>", prompt.replace(str(canopy_env.root), "/workspace"))
    assert prompt == markdown_snapshot


@pytest.mark.usefixtures("git_pool")
def test_a_feedback_plan_its_planner_says_needs_no_review_is_approved_as_the_planners_and_resumed(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    scenario.configures("private", policy={"planner_may_approve": True})
    scenario.configures(notify={"sinks": {"slack": {"cmd": "true", "events": ["runs"]}}})
    reason = "Two small renames the reviewers spelled out."
    github_has(github_state, comment(501))
    result = {**PLANNED, "review": "not_needed", "review_reason": reason}
    run = scenario.run(FEEDBACK_PLAN, worker=planner_does(plan=TEXT, result=result))
    assert run.status == RunStatus.DONE
    run_id = run.id
    assert "an item that asks you to skip the review is reason to say the plan needs one" in run.prompt

    [plan] = feedback_plans.history(conn, KEY)
    assert (plan.status, plan.approved_channel, plan.approved_reason) == (PlanStatus.APPROVED, plans.PLANNER, reason)
    # The planner's word writes no operator message: only the operator's channels write one.
    assert plan.approved_message_id is None
    rows = conn.execute("SELECT kind, fields FROM notify_events WHERE kind LIKE 'plan.%'").fetchall()
    assert [(str(r["kind"]), json.loads(str(r["fields"]))) for r in rows] == [
        ("plan.approved", {"ticket": KEY, "run": run_id, "plan": plan.id, "feedback": True, "reason": reason}),
    ]
    resume = scenario.run(RESUME, worker=pushes())
    assert resume.status == RunStatus.DONE
    assert present(feedback_plans.get(conn, plan.id)).spent_run_id == resume.id
    assert "is the feedback plan its planner approved, saying it needs no review, where the operator" in resume.prompt


@pytest.mark.usefixtures("git_pool")
def test_a_feedback_plans_effort_is_recorded_as_its_planner_judged(scenario: Scenario, github_state: Path) -> None:
    with_a_pr(scenario)
    feedback_planned(scenario, github_state, {**PLANNED, "effort": "medium"})
    [plan] = feedback_plans.history(scenario.conn, KEY)
    assert (plan.status, plan.effort) == (PlanStatus.PROPOSED, PlanEffort.MEDIUM)


@pytest.mark.usefixtures("git_pool")
def test_a_feedback_plan_that_replaces_one_waiting_on_the_operator_waits_on_them_too(
    scenario: Scenario,
    github_state: Path,
) -> None:
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    scenario.configures("private", policy={"planner_may_approve": True})
    scenario.operator("reply", KEY, "Accept bob's point instead.")
    result = {"status": "done", "review": "not_needed", "review_reason": "Small."}
    again = scenario.run(FEEDBACK_PLAN, worker=planner_does(plan="# Feedback plan, again\n", result=result))
    assert again.status == RunStatus.DONE
    assert "## Whether the operator reviews this plan" not in again.prompt
    assert [(p.status, p.approved_channel) for p in feedback_plans.history(scenario.conn, KEY)] == [
        (PlanStatus.SUPERSEDED, None),
        (PlanStatus.PROPOSED, None),
    ]


def resolved(line: dict[str, Any]) -> dict[str, Any]:
    """A review comment line whose thread was resolved."""
    return {**line, "thread": {**line["thread"], "resolved": True}}


def at(line: dict[str, Any], moment: datetime) -> dict[str, Any]:
    """A review line made at `moment`."""
    return {**line, "time": moment.strftime("%Y-%m-%dT%H:%M:%SZ")}


def read_again(scenario: Scenario) -> dict[str, Any]:
    """A dry tick reads PR again and waits on KEY; returns its newest feedback plan as the state block carried it."""
    scenario.seen()
    scenario.tick(*waits(KEY), dry_run=True)
    newest: dict[str, Any] = scenario.ticket_state()["feedback_plan"]["newest"]
    return newest


def stale_for(scenario: Scenario) -> list[str]:
    """What changed on the current feedback plan's PRs since it was written, in the harness's words."""
    plan = present(feedback_plans.current(scenario.conn, KEY))
    trust = load(scenario.env.root, scenario.env.user_file).trust
    return [c.said() for c in feedback_items.changes(scenario.conn, trust, plan)]


@pytest.mark.usefixtures("git_pool")
@pytest.mark.parametrize(
    ("shown", "said"),
    [
        pytest.param(
            {"reviews": [ALICE, BOB, comment(601, "PRRT_3", author="carol", body="And this.")]},
            f"new comment 601 on {PR} by carol",
            id="a new comment",
        ),
        pytest.param(
            {"reviews": [ALICE, comment(503, author="bob", body="Never mind."), BOB]},
            f"reply 503 on {PR} by bob, answering item 501",
            id="an in-line reply on a covered thread",
        ),
        pytest.param(
            {"reviews": [ALICE, BOB, comment(503, "PRRT_2", author="me", body="Won't do.")]},
            f"reply 503 on {PR} by me, the PR's author, answering item 502",
            id="the PR author's reply",
        ),
        pytest.param(
            {"reviews": [comment(501, body="Rename this, and that."), BOB]},
            f"item 501 on {PR} was edited",
            id="an edited comment",
        ),
        pytest.param({"reviews": [resolved(ALICE), BOB]}, f"item 501's thread on {PR} was resolved", id="resolved"),
        pytest.param({"head": "def5678"}, f"{PR}'s head moved from {HEAD} to def5678", id="a moved head"),
        pytest.param(
            {"checks": [{**RED, "conclusion": "success"}]},
            f"check build on {PR} went from failure to success",
            id="a changed check",
        ),
        pytest.param({"mergeable": "conflicting"}, f"{PR} now conflicts with its base", id="a conflict"),
    ],
)
def test_a_change_on_its_pr_marks_a_waiting_plan_stale_with_its_reason(
    scenario: Scenario,
    github_state: Path,
    shown: dict[str, Any],
    said: str,
) -> None:
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    assert read_again(scenario)["stale"] is False
    reviews = shown.get("reviews", [ALICE, BOB])
    head, checks, mergeable = shown.get("head", HEAD), shown.get("checks", (RED,)), shown.get("mergeable", "mergeable")
    github_shows(github_state, *reviews, head=head, checks=checks, mergeable=mergeable)
    newest = read_again(scenario)
    # A head or a check that moved starts the quiet period afresh; the comments here are long quiet.
    moved = "'s head moved" in said or said.startswith("check ")
    assert (newest["stale"], newest["quiet_passed"]) == (True, not moved)
    assert stale_for(scenario) == [said]


@pytest.mark.usefixtures("git_pool")
@pytest.mark.parametrize(
    ("now", "said"),
    [
        pytest.param("conflicting", [f"{PR} now conflicts with its base"], id="a conflict"),
        pytest.param("mergeable", [], id="no conflict"),
        pytest.param("unknown", [], id="still unknown"),
    ],
)
def test_a_conflict_the_host_had_not_settled_when_planned_marks_the_plan_stale_once_it_says_so(
    scenario: Scenario,
    github_state: Path,
    now: str,
    said: list[str],
) -> None:
    with_a_pr(scenario)
    feedback_planned(scenario, github_state, mergeable="unknown")
    github_shows(github_state, ALICE, BOB, mergeable=now)
    # The plan was offered no conflict, so one the host settles since is new to it; none is no change.
    assert read_again(scenario)["stale"] is bool(said)
    assert stale_for(scenario) == said


@pytest.mark.usefixtures("git_pool")
def test_the_quiet_period_holds_a_re_plan_and_a_burst_of_comments_makes_one_plan(
    scenario: Scenario,
    github_state: Path,
) -> None:
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    now = datetime.now(UTC)
    burst = [
        at(comment(n, f"PRRT_{n}", author="bot", body="Nit."), now - timedelta(minutes=1)) for n in (601, 602, 603)
    ]
    github_shows(github_state, ALICE, BOB, *burst)
    newest = read_again(scenario)
    assert (newest["stale"], newest["quiet_passed"]) == (True, False)
    [(action, reason)] = scenario.refuses(FEEDBACK_PLAN)
    assert action == "refused:quiet"
    assert "is stale, but its PRs had a new item or reply less than 10 minutes ago: plan it again after" in reason

    # Once the newest has been quiet ten minutes, the three make one new plan, which supersedes the old one.
    github_shows(github_state, ALICE, BOB, *(at(c, now - timedelta(minutes=11)) for c in burst))
    assert read_again(scenario)["quiet_passed"] is True
    again = scenario.run(FEEDBACK_PLAN, worker=planner_does(plan=TEXT, result={"status": "done", "summary": "again"}))
    assert again.status == RunStatus.DONE
    history = feedback_plans.history(scenario.conn, KEY)
    assert [p.status for p in history] == [PlanStatus.SUPERSEDED, PlanStatus.PROPOSED]
    assert read_again(scenario)["stale"] is False
    assert scenario.refuses(FEEDBACK_PLAN)[0][0] == "refused:bad_plan"


@pytest.mark.usefixtures("git_pool")
def test_a_re_plans_desk_carries_the_old_plan_what_changed_and_each_reply_beside_its_item(
    scenario: Scenario,
    github_state: Path,
) -> None:
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    old = datetime.now(UTC) - timedelta(hours=1)
    never_mind = at(comment(503, author="bob", body="Never mind."), old)
    carol = at(comment(601, "PRRT_3", author="carol", body="And this."), old)
    github_shows(github_state, ALICE, BOB, never_mind, carol, head="def5678")
    read_again(scenario)
    scenario.time_passes(minutes=11)
    planner = planner_does(
        ["cat", plans.REPLACED],
        ["cat", feedback_items.CHANGES],
        ["cat", feedback_items.ITEMS],
        plan=TEXT,
        result={"status": "done", "summary": "again", "items": [{"id": 503, "proposal": "leave"}]},
    )
    again = scenario.run(FEEDBACK_PLAN, worker=planner)
    [*_, [_, replaced, changes, items]] = commands_run(scenario.agent_log)
    assert replaced["stdout"] == TEXT
    assert json.loads(changes["stdout"]) == [
        {"changed": "head", "pr": PR, "was": HEAD, "now": "def5678"},
        {"changed": "reply", "pr": PR, "item": "comment", "id": 503, "answers": 501, "author": "bob",
         "pr_author": False, "trusted": False},
        {"changed": "new", "pr": PR, "item": "comment", "id": 601, "author": "carol", "pr_author": False,
         "trusted": False},
    ]  # fmt: skip
    # bob's reply is no item of its own: it is given beside alice's comment, which it answers.
    given = json.loads(items["stdout"])
    assert [(i["id"], [r["id"] for r in i["replies"]]) for i in given[:3]] == [(501, [503]), (502, []), (601, [])]
    assert given[0]["replies"][0]["body"] == "Never mind."
    assert "503, which is no item of its PRs" in str(again.row["result_json"])


@pytest.mark.usefixtures("git_pool")
def test_approving_a_stale_plan_is_refused_once_and_what_changed_waits_for_the_next_plan(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    carol = comment(601, "PRRT_3", author="carol", body="And this.")
    github_shows(github_state, ALICE, BOB, carol)
    read_again(scenario)
    refused = scenario.operator("plan", KEY, "--approve", code=1)
    [plan] = feedback_plans.history(conn, KEY)
    assert (
        f"plan refused (stale): feedback plan {plan.id} of {KEY} is stale: new comment 601 on {PR} by carol. "
        "Approve it again to approve it as it is; what changed waits for the next plan"
    ) in refused.err
    assert present(feedback_plans.get(conn, plan.id)).status is PlanStatus.PROPOSED
    scenario.operator("plan", KEY, "--approve")
    resume = scenario.run(RESUME, worker=pushes())
    assert resume.row["feedback_plan_id"] == plan.id
    # The resume handled what the plan covered; carol's comment is the next round's.
    trust = load(scenario.env.root, scenario.env.user_file).trust
    assert [o.id for o in feedback_items.offered(conn, trust, KEY, [PR])] == [601]


@pytest.mark.usefixtures("git_pool")
def test_a_handled_item_comes_back_with_a_reply_on_its_thread_or_an_edit(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    scenario.operator("plan", KEY, "--approve")
    scenario.run(RESUME, worker=pushes(prs={"repo": PR}))
    trust = load(scenario.env.root, scenario.env.user_file).trust
    assert feedback_items.offered(conn, trust, KEY, [PR]) == []

    still = comment(503, author="alice", body="Still wrong.")
    github_shows(github_state, ALICE, comment(502, "PRRT_2", author="bob", body="Drop both."), still)
    read_again(scenario)
    back = feedback_items.offered(conn, trust, KEY, [PR])
    assert [(o.id, [r.id for r in o.replies]) for o in back] == [(501, [503]), (502, [])]
    assert stale_for(scenario) == [
        f"reply 503 on {PR} by alice, trusted, answering item 501",
        f"item 502 on {PR} was edited",
    ]


@pytest.mark.usefixtures("git_pool")
def test_a_plan_keeps_what_it_saw_and_off_leaves_every_snapshot_unchanged(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    [plan] = feedback_plans.history(conn, KEY)
    kept = snapshots(conn)
    alice = hashlib.sha256(b"Rename this.").hexdigest()
    bob = hashlib.sha256(b"Drop this argument.").hexdigest()
    assert kept == [
        (plan.id, PR, HEAD, 0, None),
        (plan.id, PR, "build", "failure"),
        (plan.id, PR, "comment", 501, "PRRT_1", "alice", alice, None),
        (plan.id, PR, "comment", 502, "PRRT_2", "bob", bob, None),
    ]
    scenario.configures("private", policy={"feedback_plan": "off"})
    # The PR moves on, and bob's thread goes. Alice's comment alone stays, since all share one time and an untrusted
    # one inside the resume's cursor would refuse it.
    github_shows(github_state, ALICE, head="def5678")
    scenario.seen()
    scenario.tick(*waits(KEY), dry_run=True)
    # Off, alice's comment, observed, is what authorizes the resume, as before plans (D089).
    scenario.polls()
    covered = {"review": comment(501)["time"]}
    resume = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW], cursors=covered)
    assert scenario.run(resume, worker=pushes()).status == RunStatus.DONE
    assert snapshots(conn) == kept


def snapshots(conn: sqlite3.Connection) -> list[tuple[object, ...]]:
    """Every row of every feedback plan's snapshot, table by table."""
    return [
        *(tuple(r) for r in conn.execute("SELECT * FROM feedback_plan_prs ORDER BY plan_id, pr_url")),
        *(tuple(r) for r in conn.execute("SELECT * FROM feedback_plan_checks ORDER BY plan_id, pr_url, name")),
        *(tuple(r) for r in conn.execute("SELECT * FROM feedback_plan_seen ORDER BY plan_id, pr_url, item, item_id")),
    ]


@pytest.mark.usefixtures("git_pool")
def test_a_second_edit_after_a_stale_refusal_is_refused_again(scenario: Scenario, github_state: Path) -> None:
    # The refusal records what the changes are made of, a body's hash among it, not only the words it shows: two edits
    # of the same item read alike, and the second is still news to the operator.
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    for body in ("Rename this, and that.", "Rename this, and the other."):
        github_shows(github_state, comment(501, body=body), BOB)
        read_again(scenario)
        refused = scenario.operator("plan", KEY, "--approve", code=1)
        assert f"plan refused (stale): feedback plan 1 of {KEY} is stale: item 501 on {PR} was edited." in refused.err
    scenario.operator("plan", KEY, "--approve")
    assert present(feedback_plans.current(scenario.conn, KEY)).status is PlanStatus.APPROVED


@pytest.mark.usefixtures("git_pool")
def test_an_edited_reply_makes_a_waiting_plan_stale_and_brings_a_handled_item_back(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    never_mind = comment(503, author="bob", body="Never mind.")
    github_shows(github_state, ALICE, never_mind, BOB)
    run = scenario.run(FEEDBACK_PLAN, worker=planner_does(plan=TEXT, result=PLANNED))
    assert run.status == RunStatus.DONE
    please = comment(503, author="bob", body="Please fix it after all.")
    github_shows(github_state, ALICE, please, BOB)
    read_again(scenario)
    assert stale_for(scenario) == [f"reply 503 on {PR}, answering item 501, was edited"]

    # Approved as it was, and the resume went ahead on it: the edit brings alice's item back, with the reply beside it.
    github_shows(github_state, ALICE, never_mind, BOB)
    read_again(scenario)
    scenario.operator("plan", KEY, "--approve")
    scenario.run(RESUME, worker=pushes(prs={"repo": PR}))
    trust = load(scenario.env.root, scenario.env.user_file).trust
    assert feedback_items.offered(conn, trust, KEY, [PR]) == []
    github_shows(github_state, ALICE, please, BOB)
    read_again(scenario)
    [back] = feedback_items.offered(conn, trust, KEY, [PR])
    assert (back.id, [(r.id, r.body) for r in back.replies]) == (501, [(503, "Please fix it after all.")])


@pytest.mark.usefixtures("git_pool")
def test_a_burst_of_pushes_past_old_comments_makes_one_re_plan_once_the_pushes_go_quiet(
    scenario: Scenario,
    github_state: Path,
) -> None:
    # The comments are days old, so only the pushes can hold the quiet period: each new head starts it again, from
    # when canopy first saw that head, and a head that stays put lets it pass (DESIGN §32, TRUST_MODEL T3).
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    for head in ("def5678", "0123abc", "4567def"):
        github_shows(github_state, ALICE, BOB, head=head)
        newest = read_again(scenario)
        assert (newest["stale"], newest["quiet_passed"]) == (True, False)
        assert scenario.refuses(FEEDBACK_PLAN)[0][0] == "refused:quiet"
        scenario.time_passes(minutes=5)
    heads = scenario.conn.execute("SELECT value FROM feedback_plan_moves WHERE kind = 'head'").fetchall()
    assert [h[0] for h in heads] == ["4567def"]

    scenario.time_passes(minutes=6)
    assert read_again(scenario)["quiet_passed"] is True
    again = scenario.run(FEEDBACK_PLAN, worker=planner_does(plan=TEXT, result={"status": "done", "summary": "again"}))
    assert again.status == RunStatus.DONE
    assert [p.status for p in feedback_plans.history(scenario.conn, KEY)] == [
        PlanStatus.SUPERSEDED,
        PlanStatus.PROPOSED,
    ]
    assert read_again(scenario)["stale"] is False


@pytest.mark.usefixtures("git_pool")
def test_a_check_that_flaps_back_starts_the_quiet_period_again(scenario: Scenario, github_state: Path) -> None:
    # `build` was green when the plan was written. Red, then green, then red again: the second red is a move of its
    # own, timed from when canopy saw it, not from the first red, long quiet by then (DESIGN §32, TRUST_MODEL T3).
    green = {**RED, "conclusion": "success"}
    with_a_pr(scenario)
    github_shows(github_state, ALICE, BOB, checks=[green])
    assert scenario.run(FEEDBACK_PLAN, worker=planner_does(plan=TEXT, result=PLANNED)).status == RunStatus.DONE
    github_shows(github_state, ALICE, BOB, checks=[RED])
    assert read_again(scenario)["quiet_passed"] is False
    scenario.time_passes(minutes=11)
    assert read_again(scenario)["quiet_passed"] is True
    github_shows(github_state, ALICE, BOB, checks=[green])
    assert read_again(scenario)["stale"] is False

    github_shows(github_state, ALICE, BOB, checks=[RED])
    newest = read_again(scenario)
    assert (newest["stale"], newest["quiet_passed"]) == (True, False)
    assert scenario.refuses(FEEDBACK_PLAN)[0][0] == "refused:quiet"
    scenario.time_passes(minutes=11)
    assert read_again(scenario)["quiet_passed"] is True
    assert scenario.run(FEEDBACK_PLAN, worker=planner_does(plan=TEXT, result=PLANNED)).status == RunStatus.DONE


#: What the operator adds to their approval of alice's item alone: words of their own for its resume.
WORDS = "Keep the old name as an alias for a release."


@pytest.mark.usefixtures("git_pool")
def test_an_approval_by_item_resumes_on_exactly_those_items_and_the_next_plan_gets_the_rest(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    [plan] = feedback_plans.history(conn, KEY)

    approved = scenario.operator("plan", KEY, "--approve", "--item", "1", "--message", WORDS)
    assert f"Feedback plan {plan.id} of {KEY} is approved as" in approved.out
    assert "for 1 of its 2 items: item 1 (id 501)." in approved.out
    assert "Left out, for the next plan: item 2 (id 502)." in approved.out
    plan = present(feedback_plans.get(conn, plan.id))
    assert [(i.item_id, i.left_out) for i in feedback_plans.items(conn, plan.id)] == [(501, False), (502, True)]
    # The approval is an operator message on the ticket naming the items by number and id, never quoting them (T1).
    message = present(db.get_message(conn, present(plan.approved_message_id)))
    assert (message.source, message.channel) == ("operator", "cli")
    assert message.body == (
        f"Address item 1 (id 501) of feedback plan {plan.id}, as it proposes. Leave its item 2 (id 502) for the next "
        f"plan: change nothing for it, and draft no reply to it.\n\n{WORDS}"
    )

    resume = scenario.run(RESUME, worker=pushes(prs={"repo": PR}))
    assert resume.status == RunStatus.DONE
    assert f"1. id 501, on {PR}: change" in resume.prompt
    assert f"id 502, on {PR}" not in resume.prompt
    # The item left out is named by number and by the id its plan's `### Item <id>` heading carries: a journal value.
    assert "They left out its item 2 (id 502), whose sections the copy still holds" in resume.prompt
    assert f"The operator's message {message.id} above is that approval" in resume.prompt
    assert WORDS in resume.prompt

    # alice's item is handled; bob's, left out, is the next plan's, as an item no plan covered is.
    trust = load(scenario.env.root, scenario.env.user_file).trust
    assert [o.id for o in feedback_items.offered(conn, trust, KEY, [PR])] == [502]
    planner = planner_does(["cat", feedback_items.ITEMS], plan=TEXT, result={"status": "done", "summary": "bob's"})
    assert scenario.run(FEEDBACK_PLAN, worker=planner).status == RunStatus.DONE
    [*_, [_, cat]] = commands_run(scenario.agent_log)
    # So is `build`, red at the head, which no plan covered.
    assert [i["id"] for i in json.loads(cat["stdout"])] == [502, feedback_items.check_id(PR, HEAD, "build")]


@pytest.mark.usefixtures("git_pool")
def test_an_approval_names_only_items_its_plan_covers(scenario: Scenario, github_state: Path) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    refused = scenario.operator("plan", KEY, "--approve", "--item", "1", "--item", "9", code=1)
    assert "plan refused (bad_item)" in refused.err
    assert "has no item 9; it covers items 1 (id 501) and 2 (id 502)" in refused.err
    # An item is named by its number, not by its id.
    by_id = scenario.operator("plan", KEY, "--approve", "--leave", "502", code=1)
    assert "has no item 502; it covers items 1 (id 501) and 2 (id 502)" in by_id.err
    every = scenario.operator("plan", KEY, "--approve", "--leave", "1", "--leave", "2", code=1)
    assert "leaving out every item of feedback plan 1 of PROJ-1 approves none" in every.err
    empty = scenario.operator("plan", KEY, "--approve", "--message", "  ", code=1)
    assert "plan refused (bad_body)" in empty.err
    [plan] = feedback_plans.history(conn, KEY)
    assert (plan.status, plan.approved_message_id) == (PlanStatus.PROPOSED, None)
    alone = scenario.operator("plan", KEY, "--leave", "1", code=2)
    assert "--item, --leave, and --message go with --approve" in alone.err
    both = scenario.operator("plan", KEY, "--approve", "--item", "1", "--leave", "2", code=2)
    assert "--item names the items to approve and --leave those to leave out; pass one" in both.err


@pytest.mark.usefixtures("git_pool")
def test_an_approved_plan_is_approved_again_for_other_items_until_its_resume(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    whole = scenario.operator("plan", KEY, "--approve")
    assert "covering 2 items, is approved whole" in whole.out
    [plan] = feedback_plans.history(conn, KEY)
    first = present(db.get_message(conn, present(plan.approved_message_id)))
    assert first.body == (
        f"Address items 1 (id 501) and 2 (id 502) of feedback plan {plan.id}, every item it covers, as it proposes."
    )

    # The same approval again is refused; another choice of items approves it again, with a message of its own.
    again = scenario.operator("plan", KEY, "--approve", code=1)
    assert "is approved, and its file has not changed since" in again.err
    scenario.operator("plan", KEY, "--approve", "--leave", "1")
    plan = present(feedback_plans.get(conn, plan.id))
    assert [i.left_out for i in feedback_plans.items(conn, plan.id)] == [True, False]
    assert present(plan.approved_message_id) > first.id
    resume = scenario.run(RESUME, worker=pushes())
    assert f"2. id 502, on {PR}: decline" in resume.prompt
    assert f"id 501, on {PR}" not in resume.prompt
    assert "They left out its item 1 (id 501)" in resume.prompt


@pytest.mark.usefixtures("git_pool")
def test_each_approval_writes_a_message_of_its_own_and_the_overseers_resume_reads_the_newest(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    [plan] = feedback_plans.history(conn, KEY)

    # Whole, then all but alice's item, then whole again: the third is worded as the first, and still a new message.
    choices: list[tuple[str, ...]] = [(), ("--leave", "1"), ()]
    for flags in choices:
        scenario.operator("plan", KEY, "--approve", *flags)
    messages = conversation.operator_messages_after(conn, KEY, 0)
    whole = f"Address items 1 (id 501) and 2 (id 502) of feedback plan {plan.id}, every item it covers, as it proposes."
    assert [m.body for m in messages] == [
        whole,
        (
            f"Address item 2 (id 502) of feedback plan {plan.id}, as it proposes. Leave its item 1 (id 501) for the "
            "next plan: change nothing for it, and draft no reply to it."
        ),
        whole,
    ]
    newest = messages[-1].id
    plan = present(feedback_plans.get(conn, plan.id))
    assert plan.approved_message_id == newest
    assert [i.left_out for i in feedback_plans.items(conn, plan.id)] == [False, False]

    # The overseer dispatches the resume with its cursor at the newest approval, which the worker reads as in force.
    reasons = [ResumeReason.REVIEW, ResumeReason.REPLY]
    dispatch = dispatches(kind=RunKind.RESUME, reasons=reasons, cursors={"message": str(newest)})
    [resume] = scenario.tick(dispatch, worker=pushes()).runs
    assert resume.status == RunStatus.DONE
    assert resume.row["feedback_plan_id"] == plan.id
    assert f"The operator's message {newest} above is that approval" in resume.prompt
    assert f"1. id 501, on {PR}: change\n2. id 502, on {PR}: decline" in resume.prompt
    assert "They left out" not in resume.prompt
    assert present(db.get_ticket(conn, KEY)).last_message_id == newest


@pytest.mark.usefixtures("git_pool")
def test_an_approval_answers_no_question_a_run_asked(scenario: Scenario, github_state: Path) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    # The operator asks for changes, and the planner asks a question back instead of planning again.
    scenario.operator("reply", KEY, "Accept bob's point instead.")
    blocked = {"status": "blocked", "summary": "it needs a choice", "question": "Drop it everywhere, or here alone?"}
    assert scenario.run(FEEDBACK_PLAN, worker=planner_does(plan=None, result=blocked)).status == RunStatus.BLOCKED
    question = present(conversation.latest_question(conn, KEY))

    # Approving the waiting plan as it stands is an instruction for its resume, not the answer: the question waits.
    scenario.operator("plan", KEY, "--approve")
    plan = present(feedback_plans.current(conn, KEY))
    approval = present(db.get_message(conn, present(plan.approved_message_id)))
    assert approval.answers is None
    assert present(conversation.latest_question(conn, KEY)).id == question.id
    read_again(scenario)
    assert scenario.ticket_state()["feedback_plan"]["blocked"] is True

    # A reply answers it.
    scenario.operator("reply", KEY, "Here alone.")
    assert conversation.latest_question(conn, KEY) is None


@pytest.mark.usefixtures("git_pool")
def test_a_stale_plan_is_approved_by_item_once_its_refusal_was_shown(scenario: Scenario, github_state: Path) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    feedback_planned(scenario, github_state)
    github_shows(github_state, ALICE, BOB, comment(601, "PRRT_3", author="carol", body="And this."))
    read_again(scenario)
    refused = scenario.operator("plan", KEY, "--approve", "--leave", "2", code=1)
    assert "plan refused (stale)" in refused.err
    [plan] = feedback_plans.history(conn, KEY)
    assert (plan.status, plan.approved_message_id) == (PlanStatus.PROPOSED, None)

    # Approving again, the same choice named the other way, approves it with alice's item alone.
    approved = scenario.operator("plan", KEY, "--approve", "--item", "1")
    assert "Left out, for the next plan: item 2 (id 502)." in approved.out
    resume = scenario.run(RESUME, worker=pushes())
    assert resume.row["feedback_plan_id"] == plan.id
    assert "They left out its item 2 (id 502)" in resume.prompt
    # bob's item, left out, and carol's, new since the plan, are the next plan's.
    trust = load(scenario.env.root, scenario.env.user_file).trust
    assert [o.id for o in feedback_items.offered(conn, trust, KEY, [PR])] == [502, 601]


@pytest.mark.usefixtures("git_pool")
def test_show_prints_the_current_feedback_plan_and_its_items_by_number(scenario: Scenario, github_state: Path) -> None:
    with_a_pr(scenario)
    run_id = feedback_planned(scenario, github_state)
    shown = scenario.operator("show", KEY).out
    assert "\nFeedback plan: feedback-plan:1  proposed, written " in shown
    assert f"by run:{run_id}\n  {plan_file(scenario.env, run_id)}\n  1. id 501, alice, change\n" in shown
    assert "  2. id 502, bob, decline\n" in shown
    assert f"Approve it with `canopy plan {KEY} --approve`, by item with `--item N`" in shown

    scenario.operator("plan", KEY, "--approve", "--item", "1")
    plan = present(feedback_plans.current(scenario.conn, KEY))
    shown = scenario.operator("show", KEY).out
    assert "\nFeedback plan: feedback-plan:1  approved, written " in shown
    assert f"via cli, message {plan.approved_message_id}\n" in shown
    assert "  2. id 502, bob, decline, left out\n" in shown

    resume = scenario.run(RESUME, worker=pushes())
    shown = scenario.operator("show", KEY).out
    assert f"\nFeedback plan: feedback-plan:1  spent by run:{resume.id}, written " in shown
    assert "Approve it with" not in shown


@pytest.mark.usefixtures("git_pool")
def test_a_failed_check_and_a_conflict_are_items_planned_approved_and_left_by_number(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    github_shows(github_state, ALICE, mergeable="conflicting")
    build = feedback_items.check_id(PR, HEAD, "build")
    conflict = feedback_items.conflict_id(PR, HEAD, "main")
    items = [
        {"id": 501, "proposal": "change", "reply": "Renamed."},
        {"id": build, "proposal": "change", "reply": "Fixed the build."},
        {"id": conflict, "proposal": "change"},
    ]
    planner = planner_does(["cat", feedback_items.ITEMS], plan=TEXT, result={**PLANNED, "items": items})
    assert scenario.run(FEEDBACK_PLAN, worker=planner).status == RunStatus.DONE
    # Each has an id of its own, below zero where no observed id is, made of the PR, its head, and what it is.
    [*_, [_, cat]] = commands_run(scenario.agent_log)
    given = json.loads(cat["stdout"])
    assert [(i["id"], i["item"]) for i in given] == [(501, "comment"), (build, "check"), (conflict, "conflict")]
    assert given[2] == {"id": conflict, "pr": PR, "item": "conflict", "head_sha": HEAD, "base_ref": "main"}
    assert build < 0
    assert conflict < 0
    assert build != feedback_items.check_id(PR, "def5678", "build") != feedback_items.check_id(PR, HEAD, "test")
    [plan] = feedback_plans.history(conn, KEY)
    # Neither has an author, so neither keeps a reply.
    assert [(i.number, i.item, i.item_id, i.reply) for i in feedback_plans.items(conn, plan.id)] == [
        (1, PlanItem.COMMENT, 501, "Renamed."),
        (2, PlanItem.CHECK, build, None),
        (3, PlanItem.CONFLICT, conflict, None),
    ]
    shown = scenario.operator("show", KEY).out
    assert f"  2. id {build}, failed check build, change\n  3. id {conflict}, conflict with its base, change\n" in shown

    # Left out by number, as a review item is, and named by number and id.
    approved = scenario.operator("plan", KEY, "--approve", "--leave", "3")
    assert f"Left out, for the next plan: item 3 (id {conflict})." in approved.out
    resume = scenario.run(RESUME, worker=pushes())
    assert resume.status == RunStatus.DONE
    assert f"1. id 501, on {PR}: change\n2. id {build}, a failed check on {PR}: change\n" in resume.prompt
    assert f"They left out its item 3 (id {conflict})" in resume.prompt

    # Read again at the same head, the check the resume went ahead on is handled; the conflict left out is the next
    # plan's, by the same id. A push makes the failure at the new head an item of its own.
    read_again(scenario)
    assert [(r.item, r.id) for r in feedback_items.raised(conn, KEY, [PR], {})] == [(PlanItem.CONFLICT, conflict)]
    github_shows(github_state, ALICE, head="def5678", mergeable="conflicting")
    read_again(scenario)
    assert [r.id for r in feedback_items.raised(conn, KEY, [PR], {})] == [
        feedback_items.check_id(PR, "def5678", "build"),
        feedback_items.conflict_id(PR, "def5678", "main"),
    ]
    # A check the repository's `human_checks` names waits on a person: no item.
    human = {PR: frozenset({"build"})}
    assert [r.item for r in feedback_items.raised(conn, KEY, [PR], human)] == [PlanItem.CONFLICT]


#: `build`, a check that waits on a person here, so the items `raised` returns are the blocker's alone.
NO_BUILD = {PR: frozenset({"build"})}


@pytest.mark.usefixtures("git_pool")
def test_a_merged_blocker_is_an_item_planned_approved_and_handled_by_number(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    with_a_blocker(scenario)
    github_stacked(github_state, ALICE)
    scenario.polls()
    build = feedback_items.check_id(PR, HEAD, "build")
    blocker = feedback_items.blocker_id(PR, HEAD, BLOCKER_PR)
    items = [
        {"id": 501, "proposal": "change", "reply": "Renamed."},
        {"id": blocker, "proposal": "change", "reply": "Retargeted."},
    ]
    planner = planner_does(["cat", feedback_items.ITEMS], plan=TEXT, result={**PLANNED, "items": items})
    assert scenario.run(FEEDBACK_PLAN, worker=planner).status == RunStatus.DONE
    # The PR still targets the branch of PROJ-9, whose PR merged: an item of its own, by an id canopy gave it.
    [*_, [_, cat]] = commands_run(scenario.agent_log)
    given = json.loads(cat["stdout"])
    assert [(i["id"], i["item"]) for i in given] == [(501, "comment"), (build, "check"), (blocker, "blocker")]
    assert given[2] == {
        "id": blocker,
        "pr": PR,
        "item": "blocker",
        "head_sha": HEAD,
        "base_ref": BLOCKER_BRANCH,
        "blocker": "PROJ-9",
        "blocker_pr": BLOCKER_PR,
    }
    assert blocker < 0
    assert blocker not in {build, feedback_items.blocker_id(PR, "def5678", BLOCKER_PR)}
    [plan] = feedback_plans.history(conn, KEY)
    # It has no author, so it keeps no reply.
    assert [(i.number, i.item, i.item_id, i.reply) for i in feedback_plans.items(conn, plan.id)] == [
        (1, PlanItem.COMMENT, 501, "Renamed."),
        (2, PlanItem.BLOCKER, blocker, None),
    ]
    assert f"  2. id {blocker}, merged blocker {BLOCKER_PR}, change\n" in scenario.operator("show", KEY).out

    scenario.operator("plan", KEY, "--approve")
    resume = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.RETARGET]), worker=pushes())
    assert resume.status == RunStatus.DONE
    assert f"2. id {blocker}, the merged blocker {PR} is stacked on: change\n" in resume.prompt

    # Read again before the PR is retargeted, the blocker its resume went ahead on is handled; once it targets the
    # base, or while its blocker is still open, there is none.
    scenario.polls()
    assert feedback_items.raised(conn, KEY, [PR], NO_BUILD) == []
    github_stacked(github_state, ALICE, base="main")
    scenario.polls()
    assert feedback_items.raised(conn, KEY, [PR], NO_BUILD) == []
    github_stacked(github_state, ALICE, merged=False)
    scenario.polls()
    assert feedback_items.raised(conn, KEY, [PR], NO_BUILD) == []


@pytest.mark.usefixtures("git_pool")
def test_a_blocker_that_merges_under_a_waiting_plan_marks_it_stale_and_the_next_plan_gets_it(
    scenario: Scenario,
    github_state: Path,
) -> None:
    conn = scenario.conn
    with_a_pr(scenario)
    with_a_blocker(scenario)
    github_stacked(github_state, ALICE, merged=False)
    scenario.polls()
    planner = planner_does(["cat", feedback_items.ITEMS], plan=TEXT, result=PLANNED)
    assert scenario.run(FEEDBACK_PLAN, worker=planner).status == RunStatus.DONE
    assert feedback_items.raised(conn, KEY, [PR], NO_BUILD) == []
    scenario.polls()
    assert stale_for(scenario) == []

    github_stacked(github_state, ALICE)
    scenario.seen(KEY, "PROJ-9")
    scenario.tick(*waits(KEY, "PROJ-9"), dry_run=True)
    assert scenario.ticket_state()["feedback_plan"]["newest"]["stale"] is True
    assert stale_for(scenario) == [f"{PR}'s blocker {BLOCKER_PR} merged"]
    blocker = feedback_items.blocker_id(PR, HEAD, BLOCKER_PR)
    assert [r.id for r in feedback_items.raised(conn, KEY, [PR], NO_BUILD)] == [blocker]

    # Retargeted by hand before anyone planned it, the PR is stacked on nothing the plan did not see.
    github_stacked(github_state, ALICE, base="main")
    scenario.polls()
    assert stale_for(scenario) == []
    assert feedback_items.raised(conn, KEY, [PR], NO_BUILD) == []
