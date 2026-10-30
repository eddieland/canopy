"""Plans in the loop (DESIGN §25, ROADMAP M44): the state block's plan, the planner's question, and `plan.proposed`.

The overseer derives `plan_proposed` and the plan rows of the phase table from each ticket's `plan` in the state block;
the harness raises a blocked planner's question as `awaiting_reply` on a public ticket too, and tells the operator's
sinks a plan waits, without its text.
"""

import json

from canopy.core import db, plans
from canopy.core.config import Policy
from canopy.core.vocab import Phase, PlanStatus, RunKind, RunStatus
from canopy.loop import attention
from canopy.notify import message
from tests.canopy.helpers import (
    KEY,
    LABEL,
    QUESTION,
    READ_PR,
    planner_does,
    present,
    raises,
    waits,
)
from tests.canopy.scenario_helpers import (
    Scenario,
    dispatches,
    pushes,
    sets_phase,
)
from tests.conftest import GitPool

TEXT = "# Plan for PROJ-1\n\n## repo\n\nAdd the button.\n"
PLAN = dispatches(kind=RunKind.PLAN)


def plan_of(scenario: Scenario) -> dict[str, object]:
    found = scenario.ticket_state()["plan"]
    assert isinstance(found, dict)
    return found


def test_under_approve_a_dry_run_tick_dispatches_a_plan_for_a_ready_ticket(scenario: Scenario) -> None:
    scenario.configures("workspace", policy={"plan": "approve"})
    scenario.seen()
    ticked = scenario.tick(PLAN, sets_phase(KEY, Phase.READY), dry_run=True)
    # No plan yet: the block leaves out its null `newest`.
    assert plan_of(scenario) == {"needed": True, "attempts": 0, "limit": 3, "changes_asked": False, "blocked": False}
    assert [(d.action, d.rationale) for d in ticked.decisions[1:]] == [
        ("dispatch:plan", f"dry run: not dispatched; would plan {KEY} over repo; label {LABEL}"),
    ]


def test_a_ticket_plans_do_not_touch_has_no_plan_in_the_state_block(scenario: Scenario) -> None:
    scenario.seen()
    scenario.tick(*waits(KEY), dry_run=True)
    assert "plan" not in scenario.ticket_state()


def test_a_ticket_with_a_branch_has_no_plan_in_the_state_block(scenario: Scenario, git_pool: GitPool) -> None:
    # Started before plans were wanted: a started ticket is never planned, so its plan decides nothing.
    scenario.run(dispatches(), worker=pushes(prs={"repo": READ_PR}))
    scenario.configures("workspace", policy={"plan": "approve"})
    scenario.tick(*waits(KEY), dry_run=True)
    assert "plan" not in scenario.ticket_state()


def test_a_proposed_plan_waits_and_a_reply_asks_for_changes(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy={"plan": "approve"})
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT))
    [plan] = plans.history(scenario.conn, KEY)
    review = raises(KEY, "plan_review", f"plan {plan.id} waits: canopy show {KEY}")
    scenario.tick(review, sets_phase(KEY, Phase.PLAN_PROPOSED), dry_run=True)
    assert plan_of(scenario) == {
        "needed": True,
        "attempts": 1,
        "limit": 3,
        "newest": {"id": plan.id, "status": PlanStatus.PROPOSED, "created_at": plan.created_at},
        "changes_asked": False,
        "blocked": False,
    }
    ticket = present(db.get_ticket(scenario.conn, KEY))
    assert ticket.phase == "plan_proposed"
    assert any(i.reason == "plan_review" for i in attention.current(scenario.conn))
    # The plan's text never reaches the overseer.
    assert "Add the button." not in json.dumps(scenario.state())

    # A reply after the plan asks for changes; the next planner reads it and the plan it replaces.
    scenario.operator("reply", KEY, "Make it blue.")
    scenario.tick(*waits(KEY), dry_run=True)
    assert plan_of(scenario)["changes_asked"] is True
    second = scenario.run(PLAN, worker=planner_does(plan="# Plan, blue\n"))
    assert second.status == RunStatus.DONE
    assert "Make it blue." in second.prompt
    assert [(p.run_id, p.status) for p in plans.history(scenario.conn, KEY)] == [
        (run.id, PlanStatus.SUPERSEDED),
        (second.id, PlanStatus.PROPOSED),
    ]
    scenario.tick(*waits(KEY), dry_run=True)
    assert plan_of(scenario)["changes_asked"] is False


def test_an_approval_after_a_reply_wins(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy={"plan": "approve"})
    scenario.run(PLAN, worker=planner_does(plan=TEXT))
    scenario.operator("reply", KEY, "Make it blue.")
    scenario.operator("plan", KEY, "--approve")
    ticket = present(db.get_ticket(scenario.conn, KEY))
    section = present(plans.state_section(scenario.conn, Policy(plan="approve"), ticket, attempts=1, limit=3))
    newest = present(section["newest"])
    assert newest["status"] == PlanStatus.APPROVED
    # Nor does the reply, or one after it, ask for changes of a plan approved: it rides the implement.
    assert section["changes_asked"] is False
    scenario.operator("reply", KEY, "And bigger.")
    ticket = present(db.get_ticket(scenario.conn, KEY))
    assert plans.changes_asked(scenario.conn, ticket) is None


def test_a_question_keeps_its_line_breaks_where_the_page_shows_them(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy={"plan": "approve"})
    question = "Red or blue?\nRed matches the logo; blue matches the docs."
    scenario.run(
        PLAN,
        worker=planner_does(plan=None, result={"status": "blocked", "summary": "-", "question": question}),
    )
    scenario.tick(*waits(KEY, rationale="the planner asked"))
    [item] = [i for i in attention.current(scenario.conn) if i.reason == "awaiting_reply"]
    # The web UI's detail pane shows the break; attention.md and `canopy status` keep each item to its line.
    assert question in item.detail
    flat = "Red or blue? Red matches the logo; blue matches the docs."
    assert flat in (scenario.env.state_dir / "attention.md").read_text()
    assert flat in scenario.operator("status").out


def test_a_blocked_planner_waits_on_the_operator_on_a_public_ticket(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy={"plan": "approve"})
    blocked = {"status": "blocked", "summary": "unclear", "question": QUESTION}
    run = scenario.run(PLAN, worker=planner_does(plan=None, result=blocked))
    assert run.status == RunStatus.BLOCKED
    asked = present(plans.question(scenario.conn, KEY))
    assert asked.body == QUESTION

    # The harness raises it: the planner wrote nothing to the ticket, so no label or comment says it waits.
    scenario.tick(*waits(KEY, rationale="the planner asked"))
    assert plan_of(scenario)["blocked"] is True
    [item] = [i for i in attention.current(scenario.conn) if i.reason == "awaiting_reply"]
    assert item.ticket_key == KEY
    assert f"answer with `canopy reply {KEY}`" in item.detail
    assert f"waits on your answer: canopy reply {KEY}" in scenario.operator("show", KEY).out

    # The operator's answer ends the wait; the next plan reads it.
    scenario.operator("reply", KEY, "Blue.")
    assert plans.question(scenario.conn, KEY) is None
    assert plans.awaiting(scenario.conn) == []
    scenario.tick(*waits(KEY), dry_run=True)
    assert plan_of(scenario)["blocked"] is False


def test_a_private_tickets_blocked_plan_is_raised_once(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.operator("start", KEY, "--plan")
    blocked = {"status": "blocked", "summary": "unclear", "question": QUESTION}
    scenario.run(dispatches(kind=RunKind.PLAN, label=None), worker=planner_does(plan=None, result=blocked))
    # A started ticket's question is `conversation.awaiting`'s; plans.awaiting leaves it out, so it is raised once.
    assert plans.awaiting(scenario.conn) == []
    assert plans.question(scenario.conn, KEY) is not None


def test_a_proposed_plan_tells_the_sinks_without_its_text(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(notify={"sinks": {"slack": {"cmd": "true", "events": ["runs"]}}})
    run = scenario.run(PLAN, worker=planner_does(plan=TEXT))
    [plan] = plans.history(scenario.conn, KEY)
    rows = scenario.conn.execute("SELECT kind, fields FROM notify_events ORDER BY id").fetchall()
    found = {str(r["kind"]): json.loads(str(r["fields"])) for r in rows}
    assert found["plan.proposed"] == {"ticket": KEY, "run": run.id, "plan": plan.id}
    assert "button" not in json.dumps(found["plan.proposed"])
    line = message.event_line("plan.proposed", found["plan.proposed"])
    assert line == f"? {KEY} plan {plan.id} waits on your approval: canopy show {KEY}"
