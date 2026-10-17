"""Plans in the loop (DESIGN §25, ROADMAP M44): the state block's plan, the planner's question, and `plan.proposed`.

The overseer derives `plan_proposed` and the plan rows of the phase table from each ticket's `plan` in the state block;
the harness raises a blocked planner's question as `awaiting_reply` on a public ticket too, and tells the operator's
sinks a plan waits, without its text.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db, plans
from canopy.core.vocab import PlanStatus, RunStatus
from canopy.loop import attention
from canopy.notify import message
from tests.canopy.helpers import (
    KEY,
    LABEL,
    QUESTION,
    approve_policy,
    canopy,
    decisions,
    dispatch_and_run,
    operator,
    overseer_does,
    planner_does,
    present,
    state_block,
)
from tests.conftest import CanopyEnv, GitPool

PLAN = ("--label", LABEL, "--kind", "plan")
TEXT = "# Plan for PROJ-1\n\n## repo\n\nAdd the button.\n"


def ticket_state(agent_log: Path, key: str = KEY) -> dict[str, object]:
    """The ticket `key` as the latest overseer's state block carried it."""
    [found] = [t for t in state_block(agent_log)["tickets"] if t["key"] == key]
    return found


def plan_of(agent_log: Path) -> dict[str, object]:
    found = ticket_state(agent_log)["plan"]
    assert isinstance(found, dict)
    return found


def test_under_approve_a_dry_run_tick_dispatches_a_plan_for_a_ready_ticket(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, conn: sqlite3.Connection
) -> None:
    approve_policy(canopy_env)
    db.touch_ticket(conn, KEY, str(canopy_env.root))
    with overseer_does(
        canopy("dispatch", KEY, "--repo", "repo", *PLAN),
        canopy("ticket", "set", KEY, "--phase", "ready"),
    ):
        assert main(["tick", "--dry-run"]) == 0
    assert plan_of(agent_log) == {
        "needed": True,
        "attempts": 0,
        "limit": 3,
        "newest": None,
        "changes_asked": False,
        "blocked": False,
    }
    assert decisions(conn, 1)[1:] == [
        ("dispatch:plan", f"dry run: not dispatched; would plan {KEY} over repo; label {LABEL}")
    ]


def test_a_ticket_plans_do_not_touch_has_no_plan_in_the_state_block(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, conn: sqlite3.Connection
) -> None:
    db.touch_ticket(conn, KEY, str(canopy_env.root))
    with overseer_does(canopy("decide", KEY, "wait", "--rationale", "nothing yet")):
        assert main(["tick", "--dry-run"]) == 0
    assert "plan" not in ticket_state(agent_log)


def test_a_proposed_plan_waits_and_a_reply_asks_for_changes(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    approve_policy(canopy_env)
    with planner_does(plan=TEXT):
        run = dispatch_and_run(conn, *PLAN)
    [plan] = plans.history(conn, KEY)
    review = canopy("attention", KEY, "plan_review", "--detail", f"plan {plan.id} waits: canopy show {KEY}")
    with overseer_does(review, canopy("ticket", "set", KEY, "--phase", "plan_proposed")):
        assert main(["tick", "--dry-run"]) == 0
    assert plan_of(agent_log) == {
        "needed": True,
        "attempts": 1,
        "limit": 3,
        "newest": {"id": plan.id, "status": PlanStatus.PROPOSED, "created_at": plan.created_at},
        "changes_asked": False,
        "blocked": False,
    }
    ticket = present(db.get_ticket(conn, KEY))
    assert ticket.phase == "plan_proposed"
    assert any(i.reason == "plan_review" for i in attention.current(conn))
    # The plan's text never reaches the overseer.
    assert "Add the button." not in json.dumps(state_block(agent_log))

    # A reply after the plan asks for changes; the next planner reads it and the plan it replaces.
    assert operator("reply", KEY, "Make it blue.") == 0
    with overseer_does(canopy("decide", KEY, "wait", "--rationale", "x")):
        assert main(["tick", "--dry-run"]) == 0
    assert plan_of(agent_log)["changes_asked"] is True
    with planner_does(plan="# Plan, blue\n"):
        second = dispatch_and_run(conn, *PLAN)
    assert second["status"] == RunStatus.DONE
    assert "Make it blue." in (canopy_env.state_dir / "runs" / f"{second['id']}.prompt").read_text()
    assert [(p.run_id, p.status) for p in plans.history(conn, KEY)] == [
        (run["id"], PlanStatus.SUPERSEDED),
        (second["id"], PlanStatus.PROPOSED),
    ]
    with overseer_does(canopy("decide", KEY, "wait", "--rationale", "x")):
        assert main(["tick", "--dry-run"]) == 0
    assert plan_of(agent_log)["changes_asked"] is False


def test_an_approval_after_a_reply_wins(canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection) -> None:
    approve_policy(canopy_env)
    with planner_does(plan=TEXT):
        dispatch_and_run(conn, *PLAN)
    assert operator("reply", KEY, "Make it blue.") == 0
    assert operator("plan", KEY, "--approve") == 0
    ticket = present(db.get_ticket(conn, KEY))
    section = present(plans.state_section(conn, "approve", ticket, attempts=1, limit=3))
    newest = present(section["newest"])
    assert newest["status"] == PlanStatus.APPROVED


def test_a_blocked_planner_waits_on_the_operator_on_a_public_ticket(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    approve_policy(canopy_env)
    with planner_does(plan=None, result={"status": "blocked", "summary": "unclear", "question": QUESTION}):
        run = dispatch_and_run(conn, *PLAN)
    assert run["status"] == RunStatus.BLOCKED
    asked = present(plans.question(conn, KEY))
    assert str(asked["body"]) == QUESTION

    # The harness raises it: the planner wrote nothing to the ticket, so no label or comment says it waits.
    with overseer_does(canopy("decide", KEY, "wait", "--rationale", "the planner asked")):
        assert main(["tick"]) == 0
    assert plan_of(agent_log)["blocked"] is True
    [item] = [i for i in attention.current(conn) if i.reason == "awaiting_reply"]
    assert item.ticket_key == KEY
    assert f"answer with `canopy reply {KEY}`" in item.detail
    capsys.readouterr()
    assert operator("show", KEY) == 0
    assert f"waits on your answer: canopy reply {KEY}" in capsys.readouterr().out

    # The operator's answer ends the wait; the next plan reads it.
    assert operator("reply", KEY, "Blue.") == 0
    assert plans.question(conn, KEY) is None
    assert plans.awaiting(conn) == []
    with overseer_does(canopy("decide", KEY, "wait", "--rationale", "x")):
        assert main(["tick", "--dry-run"]) == 0
    assert plan_of(agent_log)["blocked"] is False


def test_a_private_tickets_blocked_plan_is_raised_once(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    assert operator("start", KEY, "--plan") == 0
    with planner_does(plan=None, result={"status": "blocked", "summary": "unclear", "question": QUESTION}):
        dispatch_and_run(conn, "--kind", "plan")
    # A started ticket's question is `conversation.awaiting`'s; plans.awaiting leaves it out, so it is raised once.
    assert plans.awaiting(conn) == []
    assert plans.question(conn, KEY) is not None


def test_a_proposed_plan_tells_the_sinks_without_its_text(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    canopy_env.append_user("\n[notify.sinks.slack]\ncmd = 'true'\nevents = ['runs']\n")
    with planner_does(plan=TEXT):
        run = dispatch_and_run(conn, *PLAN)
    [plan] = plans.history(conn, KEY)
    rows = conn.execute("SELECT kind, fields FROM notify_events ORDER BY id").fetchall()
    found = {str(r["kind"]): json.loads(str(r["fields"])) for r in rows}
    assert found["plan.proposed"] == {"ticket": KEY, "run": run["id"], "plan": plan.id}
    assert "button" not in json.dumps(found["plan.proposed"])
    line = message.event_line("plan.proposed", found["plan.proposed"])
    assert line == f"? {KEY} plan {plan.id} waits on your approval: canopy show {KEY}"
