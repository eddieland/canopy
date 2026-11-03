"""The plan gate (DESIGN §25, ROADMAP M44): which tickets wait on a plan, and the operator's verbs that decide it.

`canopy plan KEY` asks for a plan, `--skip` waives it, `--approve` approves the newest as its file stands, and
`canopy start KEY --plan` starts a private ticket planned. An `implement` waits on an approved plan when the ticket
needs one (`unplanned`), and neither an `implement` nor a `resume` follows a plan whose file changed (`plan_changed`).
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db, plans, records
from canopy.core.vocab import PlanSetting, PlanStatus, ResumeReason, RunKind, RunStatus
from canopy.loop import harness_items, phases
from tests.canopy.helpers import (
    KEY,
    approve_policy,
    context,
    in_run,
    operator,
    plan_file,
    planner_does,
    present,
    seen,
)
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import TRACKER_SOURCE, CanopyEnv, GitPool

TEXT = "# Plan for PROJ-1\n\n## repo\n\nAdd the button.\n"
# `canopy plan KEY`, asking for a plan, and its two flags.
VERBS: tuple[tuple[str, ...], ...] = ((), ("--skip",), ("--approve",))
UNPLANNED = "PROJ-1 needs a plan before its implement, and {}; dispatch `plan` or wait for it"
#: The workspace's policy, asking for a plan the operator approves before any `implement` (DESIGN §25).
APPROVE = {"plan": "approve"}
#: The overseer dispatches KEY's implement on its `work` branch.
IMPLEMENT = dispatches(slug="work")
#: The overseer dispatches a resume of KEY for review.
RESUME = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW])
#: KEY's title and description as the tests' tracker first holds them.
TITLE = "Retry flaky uploads"
BODY = "Retry each upload three times.\n\nAcceptance: a third failure is reported."


def tracker_reads(state: Path, *, title: str = TITLE, body: str = BODY) -> None:
    """The tests' tracker holds KEY, open and labeled, titled `title` with description `body`, from its next read."""
    labels = [{"name": "agent-ready-tester"}]
    ticket = {"kind": "ticket", "key": KEY, "title": title, "body": body, "state": "open", "labels": labels}
    state.write_text(json.dumps({TRACKER_SOURCE: {"lines": [ticket]}}))


def raised(scenario: Scenario) -> dict[str, str]:
    """The items the harness would raise now, each reason's detail by its reason."""
    ctx = context(scenario.env)
    now = datetime.now(UTC)
    return {i.reason: i.detail for i in harness_items.raised(ctx, phases.derive(ctx, now), now)}


def planned(scenario: Scenario) -> int:
    """Run a planner that writes TEXT; returns the plan's run id."""
    run = scenario.run(dispatches(kind=RunKind.PLAN), worker=planner_does(plan=TEXT))
    assert run.status == RunStatus.DONE, Path(run.row["log_path"]).read_text()
    return run.id


def test_with_plans_off_nothing_waits_on_one(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.run(IMPLEMENT)


def test_under_approve_an_implement_waits_on_an_approved_plan(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy=APPROVE)
    assert scenario.refuses(IMPLEMENT) == [("refused:unplanned", UNPLANNED.format("it has no plan approved"))]
    run_id = planned(scenario)
    waiting = UNPLANNED.format("its plan waits on the operator's approval")
    assert scenario.refuses(IMPLEMENT) == [("refused:unplanned", waiting)]

    # The operator's edit before approving is what is approved.
    plan_file(scenario.env, run_id).write_text(TEXT + "\nRed, not blue.\n")
    approved = scenario.operator("plan", KEY, "--approve")
    path = plan_file(scenario.env, run_id)
    assert f"Plan 1 of {KEY} is approved as {path} stands now." in approved.out
    plan = present(plans.current(scenario.conn, KEY))
    assert (plan.status, plan.approved_channel) == (PlanStatus.APPROVED, "cli")
    assert plans.approved_text(scenario.env.state_dir, plan) == TEXT + "\nRed, not blue.\n"
    scenario.run(IMPLEMENT)


def test_skip_lets_the_implement_through_and_supersedes_the_plan(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy=APPROVE)
    run_id = planned(scenario)
    out = scenario.operator("plan", KEY, "--skip").out
    assert "Plan 1 of PROJ-1 is superseded; its file stays." in out
    assert "PROJ-1's plan is skipped: its implement goes ahead without one." in out
    assert [p.status for p in plans.history(scenario.conn, KEY)] == [PlanStatus.SUPERSEDED]
    assert plan_file(scenario.env, run_id).read_text() == TEXT
    ticket = present(db.get_ticket(scenario.conn, KEY))
    assert ticket.plan_setting is PlanSetting.SKIP
    scenario.run(IMPLEMENT)


def test_a_waiver_an_old_triage_wrote_lets_nothing_through(scenario: Scenario, git_pool: GitPool) -> None:
    """Triage before a plan was removed (M55): a waiver one wrote stays in the journal, read by nothing."""
    scenario.configures("workspace", policy=APPROVE)
    seen(scenario.conn, scenario.env)
    tick_id = db.start_tick(scenario.conn, dry_run=False)
    triage = db.insert_run(
        scenario.conn,
        tick_id=tick_id,
        key=KEY,
        kind=RunKind.NEEDS_PLAN,
        branch="",
        slots=[],
        runs_dir=scenario.env.state_dir,
        works_units=False,
    )
    with db.transaction(scenario.conn):
        scenario.conn.execute("UPDATE runs SET status = 'done', ended_at = started_at WHERE id = ?", (triage,))
        scenario.conn.execute(
            "INSERT INTO plan_waivers (ticket_key, run_id, reason, at) VALUES (?, ?, 'A typo.', ?)",
            (KEY, triage, db.now()),
        )
    assert scenario.refuses(IMPLEMENT) == [("refused:unplanned", UNPLANNED.format("it has no plan approved"))]
    planned(scenario)


def test_asking_for_a_plan_gates_a_ticket_whatever_the_policy(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.seen()
    assert "the next tick dispatches a planner" in scenario.operator("plan", KEY).out
    assert scenario.refuses(IMPLEMENT) == [("refused:unplanned", UNPLANNED.format("it has no plan approved"))]
    planned(scenario)
    scenario.operator("plan", KEY, "--approve")

    # Asking again makes a new plan: the approved one is superseded, and the implement waits again.
    assert "Plan 1 of PROJ-1 is superseded" in scenario.operator("plan", KEY).out
    assert plans.current(scenario.conn, KEY) is None
    assert scenario.refuses(IMPLEMENT) == [("refused:unplanned", UNPLANNED.format("it has no plan approved"))]
    assert "already waits on a plan" in scenario.operator("plan", KEY).out


def test_an_edit_after_approval_holds_the_implement_until_approved_again(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy=APPROVE)
    run_id = planned(scenario)
    scenario.operator("plan", KEY, "--approve")
    path = plan_file(scenario.env, run_id)
    path.write_text(TEXT + "\nAnd a test.\n")
    changed = (
        f"plan 1 of {KEY}, {path}, is no longer the text the operator approved; they approve it again, or ask for a "
        "new one or skip it"
    )
    assert scenario.refuses(IMPLEMENT) == [("refused:plan_changed", changed)]
    scenario.operator("plan", KEY, "--approve")
    scenario.run(IMPLEMENT)


@pytest.mark.parametrize(
    ("title", "body", "changed"),
    [
        (TITLE, BODY + "\nAnd a progress bar.", "description"),
        ("Retry flaky downloads", BODY, "title"),
        ("Retry flaky downloads", "Drop retries.", "title and description"),
    ],
)
def test_a_ticket_edited_after_approval_holds_the_implement_until_approved_again(
    scenario: Scenario,
    git_pool: GitPool,
    connector_state: Path,
    title: str,
    body: str,
    changed: str,
) -> None:
    """Someone edits the ticket after the operator approved its plan: the plan was written for words now gone (§25)."""
    scenario.configures("workspace", policy=APPROVE)
    tracker_reads(connector_state)
    planned(scenario)
    scenario.operator("plan", KEY, "--approve")
    tracker_reads(connector_state, title=title, body=body)
    reason = (
        f"{KEY}'s {changed} changed since plan 1 was approved, so the plan may no longer fit it; they approve it "
        "again, or ask for a new one or skip it"
    )
    assert scenario.refuses(IMPLEMENT) == [("refused:plan_changed", reason)]
    assert raised(scenario) == {
        "plan_changed": (
            f"{KEY}'s {changed} changed since you approved plan 1: canopy show {KEY}, then canopy plan {KEY} --approve "
            f"if it still fits, or canopy plan {KEY} for a new one, or --skip"
        ),
    }

    # Approving again says the plan still fits the ticket as it reads now.
    scenario.operator("plan", KEY, "--approve")
    refused = scenario.operator("plan", KEY, "--approve", code=1)
    assert "neither its file nor the ticket's text has changed since" in refused.err
    scenario.run(IMPLEMENT)


def test_a_ticket_unchanged_since_approval_goes_ahead(
    scenario: Scenario,
    git_pool: GitPool,
    connector_state: Path,
) -> None:
    """Whitespace a connector trims is no edit, and an implement on an unchanged ticket needs nothing more."""
    scenario.configures("workspace", policy=APPROVE)
    tracker_reads(connector_state)
    planned(scenario)
    scenario.operator("plan", KEY, "--approve")
    plan = present(plans.current(scenario.conn, KEY))
    assert plan.approved_title_sha256 is not None
    assert plan.approved_body_sha256 is not None
    tracker_reads(connector_state, body=f"  {BODY}\n")
    scenario.run(IMPLEMENT)


def test_an_approval_that_recorded_no_ticket_text_is_never_stale(
    scenario: Scenario,
    git_pool: GitPool,
    connector_state: Path,
) -> None:
    """An approval from before canopy recorded the ticket's text, or of a ticket not observed then, holds as it was."""
    scenario.configures("workspace", policy=APPROVE)
    tracker_reads(connector_state)
    planned(scenario)
    scenario.operator("plan", KEY, "--approve")
    with db.transaction(scenario.conn):
        records.update(records.Plan).set(approved_title_sha256=None, approved_body_sha256=None).everything().run(
            scenario.conn,
        )
    tracker_reads(connector_state, title="Something else entirely", body="Rewritten.")
    scenario.run(IMPLEMENT)


def test_a_ticket_edited_after_its_first_implement_holds_nothing(
    scenario: Scenario,
    git_pool: GitPool,
    connector_state: Path,
) -> None:
    """The check is before the work starts: once the ticket has a branch, its PR's review weighs an edit."""
    scenario.configures("workspace", policy=APPROVE)
    tracker_reads(connector_state)
    planned(scenario)
    scenario.operator("plan", KEY, "--approve")
    scenario.run(IMPLEMENT)
    tracker_reads(connector_state, body="Rewritten.")
    scenario.run(RESUME)
    assert "plan_changed" not in raised(scenario)


def test_a_missing_plan_holds_a_resume_until_skipped(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy=APPROVE)
    run_id = planned(scenario)
    scenario.operator("plan", KEY, "--approve")
    scenario.run(IMPLEMENT)
    path = plan_file(scenario.env, run_id)
    path.unlink()
    changed = (
        f"plan 1 of {KEY}, {path}, is no longer the text the operator approved; they approve it again, or ask for a "
        "new one or skip it"
    )
    assert scenario.refuses(RESUME) == [("refused:plan_changed", changed)]
    # A file that is gone cannot be approved, and a ticket with a branch is not planned again: --skip is the way past.
    refused = scenario.operator("plan", KEY, "--approve", code=1)
    assert f"plan refused (bad_plan): plan 1's file {path} is missing" in refused.err
    refused = scenario.operator("plan", KEY, code=1)
    assert "plan refused (bad_plan): PROJ-1 already has work on agent/PROJ-1-work" in refused.err
    scenario.operator("plan", KEY, "--skip")
    scenario.run(RESUME)


def test_the_operators_plan_verbs_refuse_inside_a_run(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen(conn, canopy_env)
    for flags in VERBS:
        with in_run(7):
            assert main(["plan", KEY, *flags]) == 1
        assert "plan refused (inside_run): CANOPY_RUN_ID is set" in capsys.readouterr().err
    ticket = present(db.get_ticket(conn, KEY))
    assert ticket.plan_setting is None


def test_the_plan_verbs_refuse_while_a_plan_run_is_running(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy=APPROVE)
    planned(scenario)
    # A plan run still running, its planner held at work.
    running = scenario.starts(dispatches(kind=RunKind.PLAN)).id
    for flags in VERBS:
        refused = scenario.operator("plan", KEY, *flags, code=1)
        reason = f"plan run {running} for {KEY} is running; wait for it to end, then decide on its plan"
        assert f"plan refused (bad_plan): {reason}" in refused.err
    assert [p.status for p in plans.history(scenario.conn, KEY)] == [PlanStatus.PROPOSED]


def test_the_plan_verbs_need_a_ticket_canopy_knows(scenario: Scenario) -> None:
    assert "plan refused (unknown): canopy has no record of PROJ-1" in scenario.operator("plan", KEY, code=1).err
    assert "plan refused (unsupported): chore:build is a chore" in scenario.operator("plan", "chore:build", code=1).err
    refused = scenario.operator("plan", KEY, "--skip", "--approve", code=2)
    assert "--approve and --skip are each a decision of their own" in refused.err


def test_start_with_plan_starts_a_private_ticket_planned(scenario: Scenario) -> None:
    assert "It is planned first" in scenario.operator("start", KEY, "--plan").out
    ticket = present(db.get_ticket(scenario.conn, KEY))
    assert ticket.plan_setting is PlanSetting.PLAN
    assert conversation.is_started(conversation.start_of(scenario.conn, KEY))
    assert plans.needed("off", ticket.plan_setting)


def test_start_with_plan_refuses_a_ticket_with_a_branch(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen(conn, canopy_env)
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-1-work' WHERE key = ?", (KEY,))
    assert operator("start", KEY, "--plan") == 1
    assert "start refused (bad_plan): PROJ-1 already has work on agent/PROJ-1-work" in capsys.readouterr().err
    assert conversation.start_of(conn, KEY) is None


def test_start_with_plan_refuses_while_a_plan_run_is_running(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy=APPROVE)
    # A plan run still running, its planner held at work.
    running = scenario.starts(dispatches(kind=RunKind.PLAN)).id
    refused = scenario.operator("start", KEY, "--plan", code=1)
    assert f"start refused (bad_plan): plan run {running} for {KEY} is running" in refused.err
    assert conversation.start_of(scenario.conn, KEY) is None


def test_grant_plan_raises_the_tickets_plan_limit(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy={"max_plan_attempts": 1})
    planned(scenario)
    reason = "PROJ-1 has had 1 plan runs and the limit is 1"
    plan = dispatches(kind=RunKind.PLAN)
    assert scenario.refuses(plan) == [("refused:attempt_limit", reason), ("attention:attempt_limit", reason)]
    refused = scenario.operator("grant", KEY, "plan", "--repo", "repo", code=1)
    assert "grant refused (bad_repo): a plan's limit is the ticket's own; leave out --repo" in refused.err
    assert "PROJ-1 has had 1 plan runs, and may now have 2." in scenario.operator("grant", KEY, "plan").out
    planned(scenario)


def test_grant_plan_refuses_inside_a_run_and_an_unknown_ticket(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert operator("grant", KEY, "plan") == 1
    assert "grant refused (unknown): canopy has no record of PROJ-1" in capsys.readouterr().err
    seen(conn, canopy_env)
    with in_run(7):
        assert main(["grant", KEY, "plan"]) == 1
    assert "grant refused (inside_run)" in capsys.readouterr().err
    assert conn.execute("SELECT count(*) FROM ticket_grants").fetchone()[0] == 0


def test_a_policy_set_in_the_workspace_file_may_only_tighten(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    approve_policy(canopy_env)
    assert context(canopy_env).config.policy.plan == "approve"
    assert plans.needed("approve", None)
    assert not plans.needed("approve", PlanSetting.SKIP)
    assert not plans.needed("off", None)
