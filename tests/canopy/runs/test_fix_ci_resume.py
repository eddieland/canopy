"""fix-ci and resume dispatches, attempt limits, the fix-ci cooldown, and cursors on dispatch (DESIGN §8)."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.vocab import TickStatus
from canopy.loop import attention
from tests.canopy.helpers import (
    InlineRunner,
    canopy,
    commit_and_push,
    dispatch_and_run,
    dispatch_refused,
    in_tick,
    last_tick,
    overseer_does,
    prompt_of,
    state_block,
    unit_of,
    wait_for_run,
    worker_does,
)
from tests.conftest import CanopyEnv, GitPool, git


def cool_down(conn: sqlite3.Connection) -> None:
    """Move every run's end back past the fix-ci cooldown."""
    long_ago = db.format_time(datetime.now(UTC) - timedelta(hours=2))
    conn.execute("UPDATE runs SET started_at = ?, ended_at = ? WHERE ended_at IS NOT NULL", (long_ago, long_ago))


def test_fix_ci_continues_the_recorded_branch(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-add-login", "PROJ-1: first")):
        first = dispatch_and_run(conn, "--label", "agent-ready-tester", "--kind", "implement", "--slug", "add-login")
    assert first["status"] == "done"

    context = "Check unit-tests failed on run 77: https://example.test/runs/77"
    with worker_does(*commit_and_push("agent/PROJ-1-add-login", "PROJ-1: fix the build")):
        fix = dispatch_and_run(conn, "--label", "agent-ready-tester", "--kind", "fix-ci", "--context", context)
    assert (fix["kind"], fix["status"], fix["branch"]) == ("fix-ci", "done", "agent/PROJ-1-add-login")

    # The fix-ci worker started from the pushed branch, not from main.
    log = git("log", "--format=%s", "agent/PROJ-1-add-login", cwd=git_pool.origin)
    assert log.splitlines() == ["PROJ-1: fix the build", "PROJ-1: first", "initial"]
    prompt = prompt_of(canopy_env, int(fix["id"]))
    assert prompt.startswith("# canopy worker: fix CI")
    assert "PR: https://example.test/pr/1." in prompt  # the implement worker reported it
    assert "This is attempt 1 of 2." in prompt
    assert context in prompt


def test_resume_prompt_points_at_the_reply_and_names_the_repliers(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    canopy_env.append_user('\n[trust]\nauthorized_repliers = ["alice", "5b10ac"]\n')
    blocked = json.dumps({"status": "blocked", "summary": "unclear", "question": "which API?"})
    with worker_does(result=blocked):
        first = dispatch_and_run(conn, "--label", "agent-ready-tester", "--kind", "implement")
    assert first["status"] == "blocked"

    context = "Authorized reply: ticket comment 10234 by account alice"
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        resumed = dispatch_and_run(conn, "--label", "agent-ready-tester", "--kind", "resume", "--context", context)
    assert (resumed["kind"], resumed["status"], resumed["branch"]) == ("resume", "done", "agent/PROJ-1-work")
    # Nothing was pushed before, so the resume started from main.
    assert git("log", "--format=%s", "agent/PROJ-1-work", cwd=git_pool.origin).splitlines() == [
        "PROJ-1: the change",
        "initial",
    ]
    prompt = prompt_of(canopy_env, int(resumed["id"]))
    assert prompt.startswith("# canopy worker: resume")
    assert context in prompt
    assert "one of `alice`, `5b10ac` carries instructions" in prompt
    assert "PR: not recorded; look up the PR for `agent/PROJ-1-work` in `repo` through the GitHub MCP." in prompt
    assert "This is attempt 1 of 3." in prompt


def test_implement_prompt_without_context_or_repliers(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    with in_tick(conn):
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=InlineRunner(),
            )
            == 0
        )
    prompt = prompt_of(canopy_env, 1)
    assert "## Context from the overseer\n\nNone.\n" in prompt
    assert "one of none (no reply may instruct you) and it is not a worker's" in " ".join(prompt.split())


@pytest.mark.parametrize("kind", ["fix-ci", "resume"])
def test_continuing_needs_a_recorded_branch(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, kind: str
) -> None:
    reason = f"PROJ-1 has no branch in the journal for {kind} to continue; dispatch implement"
    assert dispatch_refused(conn, "--label", "agent-ready-tester", "--kind", kind) == [("refused:no_branch", reason)]
    assert not treehouse_state.exists()  # refused before leasing


def test_slug_is_for_implement_only(canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection) -> None:
    reason = "fix-ci continues the ticket's recorded branch; --slug is for implement"
    assert dispatch_refused(conn, "--label", "agent-ready-tester", "--kind", "fix-ci", "--slug", "other") == [
        ("refused:bad_slug", reason)
    ]


def test_implement_attempt_limit_refuses_and_raises_attention(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(result=json.dumps({"status": "failed", "summary": "could not build"})):
        for _ in range(2):
            assert dispatch_and_run(conn, "--label", "agent-ready-tester", "--kind", "implement")["status"] == "failed"
    reason = "PROJ-1 in repo has had 2 implement runs and the limit is 2"
    assert dispatch_refused(conn, "--label", "agent-ready-tester", "--kind", "implement") == [
        ("refused:attempt_limit", reason),
        ("attention:attempt_limit", reason),
    ]
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 2
    assert [(i.ticket_key, i.reason) for i in attention.current(conn)] == [("PROJ-1", "attempt_limit")]


def test_a_limit_of_zero_disables_the_kind(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    canopy_env.append_user("\n[policy]\nmax_resume_attempts = 0\n")
    db.touch_ticket(conn, "PROJ-1", "repo")
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-1-work'")
    conn.execute("INSERT INTO ticket_units (ticket_key, repo, branch) VALUES ('PROJ-1', 'repo', 'agent/PROJ-1-work')")
    [first, _] = dispatch_refused(conn, "--label", "agent-ready-tester", "--kind", "resume")
    assert first == ("refused:attempt_limit", "PROJ-1 in repo has had 0 resume runs and the limit is 0")


def test_fix_ci_cooldown_runs_from_the_end_of_the_last_fix(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        dispatch_and_run(conn, "--label", "agent-ready-tester", "--kind", "implement")
        fix = dispatch_and_run(conn, "--label", "agent-ready-tester", "--kind", "fix-ci")
        until = db.format_time(db.parse_time(str(fix["ended_at"])) + timedelta(minutes=30))
        assert dispatch_refused(conn, "--label", "agent-ready-tester", "--kind", "fix-ci") == [
            ("refused:cooldown", f"fix-ci for PROJ-1 in repo may run again after {until}")
        ]
        # The cooldown is fix-ci's only; a resume may run at once.
        assert dispatch_and_run(conn, "--label", "agent-ready-tester", "--kind", "resume")["status"] == "done"
        cool_down(conn)
        assert dispatch_and_run(conn, "--label", "agent-ready-tester", "--kind", "fix-ci")["status"] == "done"


def test_cursors_advance_only_when_the_worker_starts(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    canopy_env.append_user("\n[capacity]\nmax_workers = 1\n")
    with in_tick(conn):
        runner = InlineRunner()
        assert (
            main(
                [
                    "dispatch",
                    "PROJ-1",
                    "--repo",
                    "repo",
                    "--label",
                    "agent-ready-tester",
                    "--kind",
                    "implement",
                    "--cursor",
                    "comment=c1",
                ],
                runner=runner,
            )
            == 0
        )
        args = [
            "dispatch",
            "PROJ-2",
            "--repo",
            "repo",
            "--label",
            "agent-ready-tester",
            "--kind",
            "implement",
            "--cursor",
            "comment=c2",
            "--cursor",
            "review=2026-10-07T20:58:50Z",
        ]
        assert main(args, runner=runner) == 1  # capacity
        rows = {r["key"]: r for r in conn.execute("SELECT * FROM tickets")}
        assert rows["PROJ-1"]["last_comment_id"] == "c1"
        assert rows["PROJ-2"]["last_comment_id"] is None
        assert db.units(conn, "PROJ-2") == []  # nor its review cursor, nor a unit at all


def test_state_block_shows_attempts_and_the_cooldown(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        dispatch_and_run(conn, "--label", "agent-ready-tester", "--kind", "implement")
        fix = dispatch_and_run(conn, "--label", "agent-ready-tester", "--kind", "fix-ci")
    with overseer_does(canopy("decide", "PROJ-1", "wait", "--rationale", "the fix-ci cooldown holds")):
        assert main(["tick"]) == 0
    state = state_block(agent_log)
    [ticket] = state["tickets"]
    [unit] = ticket["units"]
    assert (unit["repo"], unit["branch"]) == ("repo", "agent/PROJ-1-work")
    assert unit["attempts"] == {"implement": 1, "fix-ci": 1, "resume": 0}
    until = db.parse_time(str(fix["ended_at"])) + timedelta(minutes=30)
    assert unit["fix_ci_cooldown_until"] == db.format_time(until)
    assert state["policy"]["max_implement_attempts"] == 2
    assert db.parse_time(state["now"]) < until


def tick_decisions(conn: sqlite3.Connection) -> list[str]:
    tick = last_tick(conn)
    assert tick.status == TickStatus.OK, tick.summary
    return [d.action for d in db.decisions_for_tick(conn, tick.id)]


def test_red_pr_gets_one_fix_per_cooldown_window_and_stops_at_the_limit(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    """M3 acceptance, against the fakes. An overseer that asks for fix-ci every tick, as a PR whose checks keep
    failing would make it, gets one run per cooldown window and none past `max_fix_ci_attempts`."""
    with (
        worker_does(*commit_and_push("agent/PROJ-1-work")),
        overseer_does(
            canopy("dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement")
        ),
    ):
        assert main(["tick"]) == 0
        wait_for_run(conn, 1)

    fix = canopy(
        "dispatch",
        "PROJ-1",
        "--repo",
        "repo",
        "--label",
        "agent-ready-tester",
        "--kind",
        "fix-ci",
        "--context",
        "checks failed",
        "--cursor",
        "ci=run-1",
    )
    with worker_does(*commit_and_push("agent/PROJ-1-work")), overseer_does(fix):
        assert main(["tick"]) == 0
        assert tick_decisions(conn) == ["queried", "dispatch:fix-ci"]
        assert wait_for_run(conn, 2)["status"] == "done"
        # Every further tick inside the window is refused, however often the overseer asks. The tick itself is fine.
        for _ in range(2):
            assert main(["tick"]) == 0
            assert tick_decisions(conn) == ["queried", "refused:cooldown"]

        cool_down(conn)
        assert main(["tick"]) == 0
        assert tick_decisions(conn) == ["queried", "dispatch:fix-ci"]
        assert wait_for_run(conn, 3)["status"] == "done"
        # That was the last attempt: the limit refuses, whether or not the window has passed, and raises attention.
        for _ in range(2):
            assert main(["tick"]) == 0
            assert tick_decisions(conn) == ["queried", "refused:attempt_limit", "attention:attempt_limit"]
            cool_down(conn)

    assert [r["kind"] for r in conn.execute("SELECT kind FROM runs ORDER BY id")] == ["implement", "fix-ci", "fix-ci"]
    assert [(i.ticket_key, i.reason) for i in attention.current(conn)] == [("PROJ-1", "attempt_limit")]
    # Advanced by the dispatches that started, not by the refused ones.
    assert unit_of(conn, "PROJ-1")["last_ci_run_id"] == "run-1"
