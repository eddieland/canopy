"""Plan runs (DESIGN §25, ROADMAP M44): `canopy dispatch --kind plan`, the planner in its desk, and its plan."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db, plans
from canopy.core.vocab import PlanStatus, RunStatus, TickStatus
from canopy.runs import policy
from tests.canopy.helpers import (
    KEY,
    LABEL,
    QUESTION,
    InlineRunner,
    agent_runs,
    context,
    decisions,
    dispatch_and_run,
    dispatch_refused,
    in_tick,
    operator,
    planner_does,
    pool,
    prompt_of,
)
from tests.conftest import CanopyEnv, GitPool

PLAN = ("--label", LABEL, "--kind", "plan")
TEXT = "# Plan for PROJ-1\n\n## repo\n\nAdd the button to `ui/form.tsx`, red.\n\n## Tests\n\nA test of the colour.\n"


def plan_file(env: CanopyEnv, run_id: int) -> Path:
    return env.state_dir / "plans" / KEY / f"{run_id}.md"


def commands_run(agent_log: Path) -> list[list[dict[str, Any]]]:
    """The commands each fake agent run ran, in order: each one's argv, exit code, stdout, and stderr."""
    return [json.loads(line)["commands"] for line in agent_log.read_text().splitlines()]


def test_a_plan_is_written_to_its_file_and_recorded_proposed(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    status = ["git", "-C", "repo", "status", "--porcelain=v2", "--branch"]
    with planner_does(status, plan=TEXT):
        run = dispatch_and_run(conn, *PLAN)
    assert run["status"] == RunStatus.DONE, Path(run["log_path"]).read_text()

    # Planned in a desk, even over one repository, at the base and detached: a plan makes no branch.
    desk = canopy_env.root / "desks" / KEY
    [planner] = agent_runs(agent_log)
    argv = planner["argv"]
    assert isinstance(argv, list)
    assert argv[:3] == ["run", "--agent", "canopy-planner"]
    assert planner["cwd"] == str(desk)
    [[_, checked]] = commands_run(agent_log)
    assert "# branch.head (detached)" in checked["stdout"]
    assert not desk.exists()
    assert [s["status"] for s in pool(treehouse_state)] == ["available", "available"]
    assert run["branch"] == ""
    ticket = db.get_ticket(conn, KEY)
    assert ticket is not None
    assert ticket.branch is None
    assert db.units(conn, KEY) == []
    assert git_pool.remote_head(f"agent/{KEY}-work") is None

    prompt = prompt_of(canopy_env, int(run["id"]))
    assert prompt.startswith("# canopy worker: plan\n")
    assert f"carries none of the labels `{LABEL}`" in prompt
    assert "attempt 1 of 3" in prompt
    assert f"- `repo` at `{desk / 'repo'}`, at `main`." in prompt

    # The plan is the file the planner wrote in its desk, kept in a file of its own, operator-only, its hash on its row.
    [plan] = plans.history(conn, KEY)
    assert (plan.run_id, plan.status) == (run["id"], PlanStatus.PROPOSED)
    path = plan_file(canopy_env, int(run["id"]))
    assert path.read_text() == TEXT
    assert path.stat().st_mode & 0o777 == 0o600
    assert plan.sha256 == hashlib.sha256(TEXT.encode()).hexdigest()
    assert plan.size == len(TEXT.encode())
    # Its report is the planner's summary, as any run's.
    assert [(m["kind"], m["body"]) for m in db.run_messages(conn, int(run["id"]))] == [("report", "planned it")]


def test_a_new_plan_reads_the_one_it_replaces_as_it_stands_and_supersedes_it(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with planner_does(["cat", ".canopy-plan.md"], plan=TEXT):
        first = dispatch_and_run(conn, *PLAN)
    # The first has nothing to replace.
    [[_, cat]] = commands_run(agent_log)
    assert cat["returncode"] != 0
    # The operator edits the plan before asking for changes; the next planner reads it with the edit.
    edited = TEXT.replace("red", "blue")
    plan_file(canopy_env, int(first["id"])).write_text(edited)

    with planner_does(["cat", ".canopy-plan.md"], plan="# Plan, again\n\nBlue it is."):
        second = dispatch_and_run(conn, *PLAN)
    assert second["status"] == RunStatus.DONE
    [_, [_, cat]] = commands_run(agent_log)
    assert cat["stdout"] == edited
    assert "attempt 2 of 3" in prompt_of(canopy_env, int(second["id"]))
    # The copy went with the desk; the files stay, each its own plan's.
    assert not (canopy_env.root / "desks" / KEY).exists()
    assert [(p.run_id, p.status) for p in plans.history(conn, KEY)] == [
        (first["id"], PlanStatus.SUPERSEDED),
        (second["id"], PlanStatus.PROPOSED),
    ]
    assert plan_file(canopy_env, int(first["id"])).read_text() == edited
    assert plan_file(canopy_env, int(second["id"])).read_text() == "# Plan, again\n\nBlue it is."


@pytest.mark.parametrize(
    ("result", "plan", "status", "note"),
    [
        ({"status": "done", "summary": "s"}, None, RunStatus.UNKNOWN, "but its .canopy-new-plan.md is missing"),
        ({"status": "done", "summary": "s"}, " \n", RunStatus.UNKNOWN, "but its .canopy-new-plan.md is empty"),
        (
            {"status": "done", "summary": "s"},
            "x" * (plans.MAX_CHARS + 1),
            RunStatus.UNKNOWN,
            "but its .canopy-new-plan.md is over the bound; no plan was recorded",
        ),
        ({"status": "maybe"}, TEXT, RunStatus.UNKNOWN, "the planner's last line was not a valid plan result"),
        ({"status": "failed", "summary": "cannot plan this"}, TEXT, RunStatus.FAILED, ""),
    ],
)
def test_only_a_done_plan_within_its_bound_is_recorded(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    conn: sqlite3.Connection,
    result: dict[str, object],
    plan: str | None,
    status: RunStatus,
    note: str,
) -> None:
    with planner_does(plan=plan, result=result):
        run = dispatch_and_run(conn, *PLAN)
    assert run["status"] == status
    assert note in str(run["result_json"])
    assert plans.history(conn, KEY) == []
    assert not (canopy_env.state_dir / "plans").exists()


def test_a_blocked_plan_records_its_question(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    # On a public ticket too: the planner cannot comment, so the operator answers with `canopy reply`.
    blocked = {"status": "blocked", "summary": "the ticket leaves a choice", "question": QUESTION}
    with planner_does(plan=None, result=blocked):
        run = dispatch_and_run(conn, *PLAN)
    assert run["status"] == RunStatus.BLOCKED
    messages = [(m["kind"], m["body"]) for m in db.run_messages(conn, int(run["id"]))]
    assert messages == [("report", "the ticket leaves a choice"), ("question", QUESTION)]
    assert plans.history(conn, KEY) == []


def test_a_plan_file_that_is_a_link_is_never_read(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    # The planner's edit tool makes no links, but canopy reads its file as if it might: never through one.
    secret = tmp_path / "secret.txt"
    secret.write_text("not a plan\n")
    with planner_does(["ln", "-s", str(secret), plans.WRITTEN], plan=None):
        run = dispatch_and_run(conn, *PLAN)
    assert run["status"] == RunStatus.UNKNOWN
    assert "but its .canopy-new-plan.md is not a regular file" in str(run["result_json"])
    assert plans.history(conn, KEY) == []


def test_a_name_already_taken_is_never_overwritten(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    # A file with no row, as a `_run` that died between the two leaves, keeps its name and is never read.
    plans.write(canopy_env.state_dir, KEY, 1, "left by a run that died")
    with planner_does(plan=TEXT):
        run = dispatch_and_run(conn, *PLAN)
    assert run["status"] == RunStatus.CRASHED
    assert "a plan named 1.md is already there, so canopy leaves it as it is" in str(run["result_json"])
    assert plan_file(canopy_env, 1).read_text() == "left by a run that died"
    assert plans.history(conn, KEY) == []


@pytest.mark.parametrize(
    ("args", "guard", "reason"),
    [
        (["--slug", "work"], "bad_slug", "a plan writes down the work and names no branch; leave out --slug"),
        (
            ["--base", "agent/PROJ-2-work"],
            "bad_base",
            "a plan writes down the work and starts from no branch; leave out --base",
        ),
        (["--request", "1"], "bad_request", "--request names the comment asking for a split; it is for split only"),
    ],
)
def test_a_plan_takes_no_slug_base_or_request(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, args: list[str], guard: str, reason: str
) -> None:
    assert dispatch_refused(conn, *PLAN, *args) == [(f"refused:{guard}", reason)]


def test_a_started_or_split_ticket_is_not_planned(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    db.touch_ticket(conn, KEY, str(canopy_env.root))
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-1-work' WHERE key = ?", (KEY,))
    assert dispatch_refused(conn, *PLAN) == [
        ("refused:bad_plan", "PROJ-1 already has work on agent/PROJ-1-work; a started ticket is not planned")
    ]
    ctx = context(canopy_env)
    tick_id = db.start_tick(conn, dry_run=False)
    db.touch_ticket(conn, "PROJ-2", ctx.repo)
    split = db.insert_run(
        conn,
        tick_id=tick_id,
        key="PROJ-2",
        kind="split",
        branch="",
        slots=[],
        runs_dir=ctx.state_dir,
        works_units=False,
    )
    db.record_split_children(conn, "PROJ-2", split, {"PROJ-3": "repo"})
    db.finish_tick(conn, tick_id, TickStatus.OK, "test")
    assert dispatch_refused(conn, *PLAN, key="PROJ-2") == [
        ("refused:bad_plan", "PROJ-2 was split into PROJ-3; plan those instead")
    ]


def test_a_plan_needs_the_trackers_read_tools(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    # A planner that cannot read the ticket would plan from nothing; its definition allows only the read tools.
    canopy_env.write_shared(canopy_env.shared_file.read_text().replace('provider = "jira"', 'provider = "linear"'))
    assert dispatch_refused(conn, *PLAN) == [
        (
            "refused:no_read_tools",
            "no tracker read tools are known for the planner; set tracker.mcp_server and read_tools",
        )
    ]


def test_plan_attempts_are_the_tickets_and_limited(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    canopy_env.write_shared(canopy_env.shared_file.read_text() + "\n[policy]\nmax_plan_attempts = 1\n")
    with planner_does(plan=TEXT):
        dispatch_and_run(conn, *PLAN)
    reason = "PROJ-1 has had 1 plan runs and the limit is 1"
    assert dispatch_refused(conn, *PLAN) == [("refused:attempt_limit", reason), ("attention:attempt_limit", reason)]
    # Never a unit's: an implement in the same repository still has all of its attempts.
    assert policy.attempts(conn, ticket=KEY) == {}


def test_a_dry_run_plans_nothing(canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection) -> None:
    with in_tick(conn, dry_run=True) as tick_id:
        runner = InlineRunner()
        assert main(["dispatch", KEY, "--repo", "repo", *PLAN], runner=runner) == 0
        assert runner.spawned == []
        assert decisions(conn, tick_id) == [
            ("dispatch:plan", f"dry run: not dispatched; would plan {KEY} over repo; label {LABEL}")
        ]


def test_a_private_ticket_is_planned_from_its_conversation(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    assert operator("start", KEY) == 0
    assert operator("reply", KEY, "Keep it small.") == 0
    with planner_does(plan=TEXT):
        run = dispatch_and_run(conn, "--kind", "plan")
    assert (run["status"], run["private"]) == (RunStatus.DONE, 1)
    [planner] = agent_runs(agent_log)
    argv = planner["argv"]
    assert isinstance(argv, list)
    assert "canopy-planner" in argv
    prompt = prompt_of(canopy_env, int(run["id"]))
    assert "there is no label to check" in prompt
    assert "Keep it small." in prompt
    assert [p.status for p in plans.history(conn, KEY)] == [PlanStatus.PROPOSED]


def test_under_tracker_private_a_tickets_first_plan_starts_it_privately(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    # As its first implement would: otherwise the plan, posting nothing, would leave the ticket public for good.
    canopy_env.write_user(canopy_env.user_file.read_text().replace("[tracker]\n", "[tracker]\nprivate = true\n"))
    with planner_does(plan=TEXT):
        run = dispatch_and_run(conn, *PLAN)
    assert (run["status"], run["private"]) == (RunStatus.DONE, 1)
    assert conversation.is_started(conversation.start_of(conn, KEY))
