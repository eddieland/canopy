"""Triage before a plan (DESIGN §25, ROADMAP M55): a `needs-plan` run, and the waiver its `trivial` verdict writes.

A triage leases no slot: it reads each repository's primary clone through a link in its desk, writes nothing, and
judges whether the ticket needs a plan, by its prompt's measure of trivial or the operator's words for it. Only a
validated `done` `trivial` result waives the plan; anything else leaves the ticket to be planned at once, with no
attention item and no retry.
"""

import json
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli.main import main
from canopy.core import db, plans
from canopy.core.vocab import PlanSetting, RunKind, RunStatus
from canopy.loop import attention
from tests.canopy.helpers import (
    KEY,
    LABEL,
    InlineRunner,
    agent_runs,
    approve_policy,
    commands_run,
    decisions,
    dispatch_and_run,
    dispatch_refused,
    in_tick,
    operator,
    planner_does,
    pool_statuses,
    present,
    prompt_of,
    scripted,
    waits,
)
from tests.canopy.review_helpers import head, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes, reviews
from tests.conftest import CanopyEnv, GitPool

TRIVIAL = "A typo in docs or comments; one config value changed."
REASON = "The ticket fixes one misspelled word in a comment."
TRIAGE = ("--label", LABEL, "--kind", "needs-plan")
IMPLEMENT = ("--label", LABEL, "--kind", "implement")
PLAN = ("--label", LABEL, "--kind", "plan")
TEXT = "# Plan for PROJ-1\n\n## Steps\n\nFix the word.\n"
UNPLANNED = (
    "refused:unplanned",
    f"{KEY} needs a plan before its implement, and it has no plan approved; dispatch `plan` or wait for it",
)


def triage_on(env: CanopyEnv) -> None:
    """Plans on in the workspace, and triage on in the operator's own file, with their words for trivial."""
    approve_policy(env)
    env.append_user(f'\n[policy]\nplan_triage = "on"\ntrivial = "{TRIVIAL}"\n')


def verdict(judged: str, reason: str = REASON) -> dict[str, object]:
    """A triage's `done` result with `judged` as its verdict."""
    return {"status": "done", "verdict": judged, "reason": reason}


@contextmanager
def triage_reports(result: Mapping[str, object] | str, *commands: list[str]) -> Iterator[None]:
    """Until the block ends, the fake triage agent runs `commands`, then prints `result`, verbatim if a string."""
    line = result if isinstance(result, str) else json.dumps(result)
    with scripted("PLAN_TRIAGE", {"COMMANDS": json.dumps(commands), "RESULT": line}):
        yield


def test_a_trivial_verdict_waives_the_plan_and_the_implement_follows_unplanned(
    scenario: Scenario, canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, treehouse_state: Path
) -> None:
    triage_on(canopy_env)
    where = ["python3", "-c", "import os; print(os.path.realpath('repo'))"]
    ran = scenario.run(dispatches(kind=RunKind.NEEDS_PLAN), worker=triage_reports(verdict("trivial"), where))
    assert (ran.kind, ran.status, ran.branch) == (RunKind.NEEDS_PLAN, RunStatus.DONE, "")

    # It ran its own agent in a desk linking the primary clone, leased nothing, and left nothing behind.
    desk = canopy_env.root / "desks" / KEY
    [triage] = agent_runs(agent_log)
    argv = triage["argv"]
    assert isinstance(argv, list)
    assert argv[:3] == ["run", "--agent", "canopy-plan-triage"]
    assert triage["cwd"] == str(desk)
    [[linked]] = commands_run(agent_log)
    assert linked["stdout"].strip() == str(canopy_env.repo.resolve())
    assert not desk.exists()
    assert pool_statuses(treehouse_state) == ["available", "available"]
    assert db.run_slots(scenario.conn, ran.id) == []
    assert db.run_reads(scenario.conn, ran.id) == ["repo"]

    # Its prompt carries the operator's words and its own label check, and none of a worker's instructions.
    assert ran.prompt.startswith("# canopy triage: plan\n")
    assert TRIVIAL in ran.prompt
    assert f"carries none of the labels `{LABEL}`" in ran.prompt
    assert f"- `repo` at `{desk / 'repo'}`." in ran.prompt
    assert "Standing instructions" not in ran.prompt

    # The waiver is a journal fact naming the run and its reason, which is the run's report.
    ticket = present(db.get_ticket(scenario.conn, KEY))
    waiver = present(plans.waiver(scenario.conn, ticket))
    assert (waiver.run_id, waiver.reason) == (ran.id, REASON)
    assert [(m["kind"], m["body"]) for m in db.run_messages(scenario.conn, ran.id)] == [("report", REASON)]
    assert plans.history(scenario.conn, KEY) == []

    # So `unplanned` lets the implement through, and its worker never hears the triage's reason.
    implement = scenario.run(worker=pushes())
    assert implement.status == RunStatus.DONE
    assert REASON not in implement.prompt
    # Once it has started, the plan cannot be asked for: it would describe work already started.
    refused = scenario.operator("plan", KEY, code=1)
    assert "plan refused (bad_plan)" in refused.err


@pytest.mark.parametrize(
    ("result", "status", "note"),
    [
        (verdict("plan"), RunStatus.DONE, ""),
        ({"status": "failed", "reason": "The ticket says nothing yet."}, RunStatus.FAILED, ""),
        ({"status": "done", "verdict": "trivial"}, RunStatus.UNKNOWN, "not a valid triage result"),
        ({"status": "done", "verdict": "small", "reason": REASON}, RunStatus.UNKNOWN, "not a valid triage result"),
        ("trivial, I think", RunStatus.UNKNOWN, "not a valid triage result"),
    ],
    ids=["plan", "failed", "no-reason", "bad-verdict", "no-result"],
)
def test_anything_but_a_trivial_verdict_leaves_the_plan_needed_and_the_plan_follows(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    conn: sqlite3.Connection,
    result: Mapping[str, object] | str,
    status: RunStatus,
    note: str,
) -> None:
    triage_on(canopy_env)
    with triage_reports(result):
        run = dispatch_and_run(conn, *TRIAGE)
    assert run["status"] == status
    assert note in str(run["result_json"])
    assert conn.execute("SELECT count(*) FROM plan_waivers").fetchone()[0] == 0
    # The ticket needs its plan, as if triage were off; however the triage ended, nothing waits on a human.
    assert dispatch_refused(conn, *IMPLEMENT) == [UNPLANNED]
    assert attention.from_runs(conn) == []
    with planner_does(plan=TEXT):
        planned = dispatch_and_run(conn, *PLAN)
    assert planned["status"] == RunStatus.DONE


def test_a_triage_that_times_out_waives_nothing_even_with_a_trivial_line(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    triage_on(canopy_env)
    printed = f"fake agent: starting\n{json.dumps(verdict('trivial'))}\n"
    run = dispatch_and_run(conn, *TRIAGE, runner=InlineRunner(timeout_agent=True, timeout_stdout=printed))
    assert run["status"] == RunStatus.TIMEOUT
    assert "the triage timed out after 10 minutes" in str(run["result_json"])
    assert conn.execute("SELECT count(*) FROM plan_waivers").fetchone()[0] == 0
    assert dispatch_refused(conn, *IMPLEMENT) == [UNPLANNED]
    assert attention.from_runs(conn) == []


def test_a_ticket_is_triaged_once_however_its_triage_ended(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    triage_on(canopy_env)
    with triage_reports({"status": "failed", "reason": "The tracker did not answer."}):
        first = dispatch_and_run(conn, *TRIAGE)
    reason = f"{KEY} had triage run {first['id']}; a ticket is triaged once, however that ended"
    assert dispatch_refused(conn, *TRIAGE) == [("refused:triaged", reason)]
    # Not even once its work is forgotten: the bound is its runs', never reset (D030).
    assert operator("forget", KEY) == 0
    assert dispatch_refused(conn, *TRIAGE) == [("refused:triaged", reason)]


def test_triage_is_off_by_default(canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection) -> None:
    approve_policy(canopy_env)
    assert dispatch_refused(conn, *TRIAGE) == [
        ("refused:triage_off", 'policy.plan_triage is not "on": dispatch plan for a ticket that needs one')
    ]


def test_the_operators_own_word_on_a_plan_is_never_triaged(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    triage_on(canopy_env)
    db.touch_ticket(conn, KEY, str(canopy_env.root))
    assert operator("plan", KEY) == 0
    assert dispatch_refused(conn, *TRIAGE) == [
        ("refused:bad_triage", f"the operator asked for {KEY}'s plan, so it is planned, whatever a triage would say")
    ]
    assert operator("plan", KEY, "--skip") == 0
    assert dispatch_refused(conn, *TRIAGE) == [
        ("refused:bad_triage", f"the operator skipped {KEY}'s plan, so there is nothing to triage")
    ]


def test_no_triage_is_due_without_a_plan_the_policy_asks_for(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    # With plans off in the workspace, triage on alone has nothing to waive.
    canopy_env.append_user(f'\n[policy]\nplan_triage = "on"\ntrivial = "{TRIVIAL}"\n')
    assert dispatch_refused(conn, *TRIAGE) == [
        ("refused:bad_triage", f'policy.plan is not "approve", so {KEY} needs no plan to triage')
    ]
    # A ticket planned before plans were turned on is not triaged after.
    with planner_does(plan=TEXT):
        planned = dispatch_and_run(conn, *PLAN)
    approve_policy(canopy_env)
    assert dispatch_refused(conn, *TRIAGE) == [
        ("refused:bad_triage", f"{KEY} had plan run {planned['id']}; a ticket with a plan is not triaged")
    ]
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-2-work' WHERE key = ?", (KEY,))
    db.touch_ticket(conn, "PROJ-2", str(canopy_env.root))
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-2-work' WHERE key = 'PROJ-2'")
    assert dispatch_refused(conn, *TRIAGE, key="PROJ-2") == [
        ("refused:bad_triage", "PROJ-2 already has work on agent/PROJ-2-work; a started ticket is not triaged")
    ]


def test_a_ticket_due_a_triage_is_not_planned_until_it_has_had_one(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    triage_on(canopy_env)
    # Its implement's refusal points the overseer at the triage, and a plan dispatched anyway is refused.
    due = f"{KEY} needs a plan before its implement, and it has no plan approved; dispatch `needs-plan`, as its triage"
    assert dispatch_refused(conn, *IMPLEMENT) == [("refused:unplanned", f"{due} is due")]
    assert dispatch_refused(conn, *PLAN) == [
        ("refused:untriaged", f"{KEY} is due a triage before its plan; dispatch `needs-plan` first")
    ]
    # Once the triage has run and left the plan needed, the plan follows.
    with triage_reports(verdict("plan")):
        dispatch_and_run(conn, *TRIAGE)
    assert dispatch_refused(conn, *IMPLEMENT) == [UNPLANNED]
    with planner_does(plan=TEXT):
        planned = dispatch_and_run(conn, *PLAN)
    assert planned["status"] == RunStatus.DONE


def test_the_operators_own_plan_skips_a_due_triage(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    triage_on(canopy_env)
    db.touch_ticket(conn, KEY, str(canopy_env.root))
    assert operator("plan", KEY) == 0
    with planner_does(plan=TEXT):
        planned = dispatch_and_run(conn, *PLAN)
    assert planned["status"] == RunStatus.DONE
    assert conn.execute("SELECT count(*) FROM runs WHERE kind = ?", (RunKind.NEEDS_PLAN,)).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("args", "guard", "reason"),
    [
        (["--slug", "work"], "bad_slug", "a triage judges the work and names no branch; leave out --slug"),
        (
            ["--base", "agent/PROJ-2-work"],
            "bad_base",
            "a triage judges the work and starts from no branch; leave out --base",
        ),
    ],
)
def test_a_triage_takes_no_slug_or_base(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, args: list[str], guard: str, reason: str
) -> None:
    triage_on(canopy_env)
    assert dispatch_refused(conn, *TRIAGE, *args) == [(f"refused:{guard}", reason)]


def test_a_triage_needs_the_trackers_read_tools_and_a_free_worker(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    triage_on(canopy_env)
    # It leases no slot, but it is an agent run with spend: `capacity.max_workers` bounds it with the others.
    canopy_env.append_user("\n[capacity]\nmax_workers = 0\n")
    assert dispatch_refused(conn, *TRIAGE) == [("refused:capacity", "0 of 0 workers are running")]
    canopy_env.write_shared(canopy_env.shared_file.read_text().replace('provider = "jira"', 'provider = "linear"'))
    assert dispatch_refused(conn, *TRIAGE) == [
        (
            "refused:no_read_tools",
            "no tracker read tools are known for the triage; set tracker.mcp_server and read_tools",
        )
    ]


def test_a_primary_clone_that_shadows_canopys_agents_stops_the_triage(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    # The triage starts in its desk, whose links lead into the primary clones: OpenCode would read their config.
    triage_on(canopy_env)
    shadow = canopy_env.repo / ".opencode" / "agent" / "canopy-plan-triage.md"
    shadow.parent.mkdir(parents=True)
    shadow.write_text("---\npermission:\n  edit: allow\n---\n")
    with triage_reports(verdict("trivial")):
        run = dispatch_and_run(conn, *TRIAGE)
    assert run["status"] == RunStatus.CRASHED
    assert "defines one of canopy's agents" in str(run["result_json"])
    assert conn.execute("SELECT count(*) FROM plan_waivers").fetchone()[0] == 0
    assert attention.from_runs(conn) == []


def test_asking_for_a_plan_undoes_a_waiver(scenario: Scenario, canopy_env: CanopyEnv, git_pool: GitPool) -> None:
    triage_on(canopy_env)
    ran = scenario.run(dispatches(kind=RunKind.NEEDS_PLAN), worker=triage_reports(verdict("trivial")))
    shown = scenario.operator("show", KEY).out
    assert f"Plan: waived 0s ago by triage run:{ran.id}, which judged it trivial:\n  {REASON}\n" in shown
    assert f"`canopy plan {KEY}` asks for a plan instead, until its implement starts" in shown

    asked = scenario.operator("plan", KEY)
    assert f"Triage run {ran.id} had waived {KEY}'s plan; it is undone." in asked.out
    ticket = present(db.get_ticket(scenario.conn, KEY))
    assert ticket.plan_setting is PlanSetting.PLAN
    assert plans.waiver(scenario.conn, ticket) is None
    [(action, _)] = scenario.refuses(dispatches())
    assert action == "refused:unplanned"


def test_forgetting_a_ticket_ends_its_waiver(scenario: Scenario, canopy_env: CanopyEnv, git_pool: GitPool) -> None:
    triage_on(canopy_env)
    scenario.run(dispatches(kind=RunKind.NEEDS_PLAN), worker=triage_reports(verdict("trivial")))
    scenario.operator("forget", KEY)
    ticket = present(db.get_ticket(scenario.conn, KEY))
    assert plans.waiver(scenario.conn, ticket) is None
    # Planned again, as a forgotten ticket under "approve" is, and never triaged again.
    [(action, _)] = scenario.refuses(dispatches())
    assert action == "refused:unplanned"
    [(action, _)] = scenario.refuses(dispatches(kind=RunKind.NEEDS_PLAN))
    assert action == "refused:triaged"


def test_the_state_block_says_when_a_triage_is_due_and_which_waived_the_plan(
    scenario: Scenario, canopy_env: CanopyEnv, git_pool: GitPool
) -> None:
    triage_on(canopy_env)
    scenario.seen()
    scenario.tick(*waits(KEY), dry_run=True)
    assert scenario.ticket_state()["plan"] == {
        "needed": True,
        "attempts": 0,
        "limit": 3,
        "newest": None,
        "changes_asked": False,
        "blocked": False,
        "triage_due": True,
    }
    ran = scenario.run(dispatches(kind=RunKind.NEEDS_PLAN), worker=triage_reports(verdict("trivial")))
    scenario.tick(*waits(KEY), dry_run=True)
    plan = scenario.ticket_state()["plan"]
    assert (plan["needed"], plan["triage_due"], plan["waived"]) == (False, False, ran.id)


@pytest.mark.parametrize(
    ("waived", "impact", "raised"),
    [(True, "high", True), (True, "normal", False), (False, "high", False)],
    ids=["waived-high", "waived-normal", "planned-high"],
)
def test_a_review_that_judges_a_waived_tickets_pr_high_raises_not_trivial(
    scenario: Scenario, canopy_env: CanopyEnv, git_pool: GitPool, *, waived: bool, impact: str, raised: bool
) -> None:
    # The reviewer's second opinion (DESIGN §25): it is not told of the waiver, and its impact is checked against it.
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"
    scenario.configures(runtime={"review_cmd": template}, review={"agent_prs": True})
    triage = None
    if waived:
        triage_on(canopy_env)
        triage = scenario.run(dispatches(kind=RunKind.NEEDS_PLAN), worker=triage_reports(verdict("trivial")))
    implement = scenario.run(worker=pushes())
    assert implement.status == RunStatus.DONE
    pr = "https://example.test/pr/1"
    assert [u["pr_url"] for u in db.units(scenario.conn, KEY)] == [pr]
    report = {"status": "done", "verdict": "clean", "impact": impact, "summary": "It changes the retry policy."}
    reviewed = scenario.review(reviews(head(git_pool), pr, ticket=KEY), reviewer=reviewer_reports(report))
    assert "trivial" not in reviewed.prompt
    scenario.tick(*waits(KEY))
    items = [i for i in attention.current(scenario.conn) if i.reason == attention.NOT_TRIVIAL]
    if not raised:
        assert items == []
        return
    [item] = items
    assert (item.ticket_key, item.repo) == (KEY, "repo")
    assert item.detail == (
        f"review:{reviewed.id} judged {pr} high impact, but triage run:{present(triage).id} waived its plan as "
        f"trivial: {REASON}"
    )
    # The overseer neither sees nor records it: the harness raises it every tick, until the ticket is forgotten or done.
    assert attention.for_overseer(scenario.conn) == []
    scenario.tick(*waits(KEY))
    assert attention.NOT_TRIVIAL in [i.reason for i in attention.current(scenario.conn)]
    scenario.operator("forget", KEY)
    scenario.tick(*waits(KEY))
    assert attention.NOT_TRIVIAL not in [i.reason for i in attention.current(scenario.conn)]


@pytest.mark.parametrize(
    ("result", "status", "then"),
    [
        (verdict("trivial"), RunStatus.DONE, RunKind.IMPLEMENT),
        (verdict("plan"), RunStatus.DONE, RunKind.PLAN),
        ({"status": "failed", "reason": "The tracker did not answer."}, RunStatus.FAILED, RunKind.PLAN),
    ],
    ids=["trivial", "plan", "failed"],
)
def test_a_tick_triages_where_one_is_due_and_the_next_tick_dispatches_what_the_verdict_leaves(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    result: Mapping[str, object],
    status: RunStatus,
    then: RunKind,
) -> None:
    # The overseer prompt's triage row: `needs-plan` where `plan.triage_due` is true, then `implement` under a waiver,
    # or `plan` at once, with no `wait` for a triage that failed, since none raised an attention item.
    triage_on(canopy_env)
    scenario.seen()
    ticked = scenario.tick(dispatches(kind=RunKind.NEEDS_PLAN), worker=triage_reports(result))
    [ran] = ticked.runs
    assert (ran.kind, ran.status) == (RunKind.NEEDS_PLAN, status)
    assert scenario.attention() == []

    ticked = scenario.tick(dispatches(kind=then), dry_run=True)
    ticket = scenario.ticket_state()
    assert (ticket["last_run"]["kind"], ticket["last_run"]["status"]) == (RunKind.NEEDS_PLAN, status)
    assert ticket["plan"]["triage_due"] is False
    assert ticket["plan"]["needed"] is (then == RunKind.PLAN)
    assert [d.action for d in ticked.decisions if d.action.startswith(("dispatch", "refused"))] == [f"dispatch:{then}"]


def test_a_dry_run_triages_nothing(canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection) -> None:
    triage_on(canopy_env)
    with in_tick(conn, dry_run=True) as tick_id:
        runner = InlineRunner()
        assert main(["dispatch", KEY, "--repo", "repo", *TRIAGE], runner=runner) == 0
        assert runner.spawned == []
        assert decisions(conn, tick_id) == [
            ("dispatch:needs-plan", f"dry run: not dispatched; would triage {KEY}'s plan over repo; label {LABEL}")
        ]


def test_a_private_tickets_triage_reads_its_conversation_and_no_worker_reads_its_reason(
    scenario: Scenario, canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path
) -> None:
    triage_on(canopy_env)
    scenario.operator("start", KEY)
    scenario.operator("reply", KEY, "Only the comment in the README.")
    ran = scenario.run(dispatches(kind=RunKind.NEEDS_PLAN, label=None), worker=triage_reports(verdict("trivial")))
    assert ran.row["private"] == 1
    # The same prompt a public ticket's triage reads, its conversation as the operator's messages, and no label check.
    assert ran.prompt.startswith("# canopy triage: plan\n")
    assert "there is no label to check" in ran.prompt
    assert "## Messages from the operator\n\n" in ran.prompt
    assert "Only the comment in the README." in ran.prompt
    [triage] = agent_runs(agent_log)
    assert "canopy-plan-triage" in triage["argv"]
    # Its report is in the conversation the operator reads, and in no worker's prompt.
    assert REASON in scenario.operator("show", KEY).out
    implement = scenario.run(dispatches(label=None), worker=pushes())
    assert "Only the comment in the README." in implement.prompt
    assert REASON not in implement.prompt


@pytest.mark.parametrize("private", [False, True], ids=["public", "private"])
def test_the_triage_prompt(
    scenario: Scenario, canopy_env: CanopyEnv, git_pool: GitPool, markdown_snapshot: SnapshotAssertion, *, private: bool
) -> None:
    """The triage's prompt, whole, so a change to its wording or to what fills it in is a diff in review.

    A public ticket's, with its label check and no operator's messages, and a started one's, with no label to check and
    its conversation as the operator's messages.
    """
    triage_on(canopy_env)
    if private:
        scenario.operator("start", KEY)
        scenario.operator("reply", KEY, "Only the comment in the README.")
    label = None if private else LABEL
    ran = scenario.run(dispatches(kind=RunKind.NEEDS_PLAN, label=label), worker=triage_reports(verdict("plan")))
    # A message's time is when the test wrote it.
    prompt = re.sub(r"\d{4}-\d\d-\d\dT[\d:.]+Z", "<time>", ran.prompt.replace(str(canopy_env.root), "/workspace"))
    assert prompt == markdown_snapshot


def test_a_triage_is_never_wrapped_as_a_worker_run(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection, agent_log: Path
) -> None:
    # `worker_cmd_prefix` wraps the commands a worker run starts; a triage is no worker run (DESIGN §12, §25).
    triage_on(canopy_env)
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("\n[runtime]\n", "\n[runtime]\nworker_cmd_prefix = 'env CANOPY_X=1'\n")
    )
    with triage_reports(verdict("plan")):
        run = dispatch_and_run(conn, *TRIAGE)
    assert run["status"] == RunStatus.DONE
    [triage] = agent_runs(agent_log)
    assert "CANOPY_X" not in json.dumps(triage["env"])
    assert prompt_of(canopy_env, int(run["id"])).startswith("# canopy triage: plan\n")


def test_a_triage_without_the_operators_words_judges_by_its_prompts_own_measure(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    # The operator need not say what is trivial; the prompt's own measure is the one it judges by (DESIGN §25).
    approve_policy(canopy_env)
    canopy_env.append_user('\n[policy]\nplan_triage = "on"\n')
    with triage_reports(verdict("trivial")):
        run = dispatch_and_run(conn, *TRIAGE)
    assert run["status"] == RunStatus.DONE
    prompt = prompt_of(canopy_env, int(run["id"]))
    assert "Work is trivial when a plan would only restate the ticket" in prompt
    assert "The operator's own words for it, if they gave any:\n\nNone: judge by the measure above.\n" in prompt
    assert present(plans.waiver(conn, present(db.get_ticket(conn, KEY)))).reason == REASON
