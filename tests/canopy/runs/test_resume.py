"""Resume dispatches, their reasons, attempt limits, the CI cooldown, and cursors on dispatch (DESIGN §8).

A `resume` takes everything that comes back to a PR, a failed check among it (M56); `fix-ci` runs from before that
still read, and count as `resume` runs.
"""

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
    decisions,
    dispatch_and_run,
    dispatch_refused,
    in_tick,
    last_tick,
    operator,
    overseer_does,
    present,
    prompt_of,
    state_block,
    unit_of,
    wait_for_run,
    worker_does,
)
from tests.conftest import CanopyEnv, GitPool, git

LABEL = ("--label", "agent-ready-tester")
RESUME = (*LABEL, "--kind", "resume")
CHECK = "Check unit-tests failed on run 77: https://example.test/runs/77"


def cool_down(conn: sqlite3.Connection) -> None:
    """Move every run's end back past the CI cooldown."""
    long_ago = db.format_time(datetime.now(UTC) - timedelta(hours=2))
    conn.execute("UPDATE runs SET started_at = ?, ended_at = ? WHERE ended_at IS NOT NULL", (long_ago, long_ago))


def with_branch(conn: sqlite3.Connection) -> None:
    """Give PROJ-1 the branch its first implement would have recorded, in `repo`."""
    db.touch_ticket(conn, "PROJ-1", "repo")
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-1-work'")
    conn.execute("INSERT INTO ticket_units (ticket_key, repo, branch) VALUES ('PROJ-1', 'repo', 'agent/PROJ-1-work')")


def old_fix_ci(conn: sqlite3.Connection, *, ended: datetime | None = None) -> int:
    """Record a `fix-ci` run in `repo` as an earlier canopy left it, ended `ended` (now by default).

    Returns:
        Its id.
    """
    with in_tick(conn, ends_ok=True) as tick_id:
        slot = db.RunSlot("repo", Path("/slot"), "lease-old", "canopy:PROJ-1", "main")
        run_id = db.insert_run(
            conn,
            tick_id=tick_id,
            key="PROJ-1",
            kind="fix-ci",
            branch="agent/PROJ-1-work",
            slots=[slot],
            runs_dir=Path(),
        )
    at = db.format_time(ended or datetime.now(UTC))
    conn.execute("UPDATE runs SET status = 'done', ended_at = ? WHERE id = ?", (at, run_id))
    return run_id


def test_a_red_check_resumes_the_recorded_branch_with_the_checks_named(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-add-login", "PROJ-1: first")):
        first = dispatch_and_run(conn, *LABEL, "--kind", "implement", "--slug", "add-login")
    assert first["status"] == "done"

    with worker_does(*commit_and_push("agent/PROJ-1-add-login", "PROJ-1: fix the build")):
        fix = dispatch_and_run(conn, *RESUME, "--reason", "ci", "--context", CHECK, "--cursor", "ci=run-77")
    assert (fix["kind"], fix["status"], fix["branch"]) == ("resume", "done", "agent/PROJ-1-add-login")
    assert db.run_reasons(conn, [int(fix["id"])]) == {int(fix["id"]): ("ci",)}
    assert unit_of(conn, "PROJ-1")["last_ci_run_id"] == "run-77"

    # The worker started from the pushed branch, not from main.
    log = git("log", "--format=%s", "agent/PROJ-1-add-login", cwd=git_pool.origin)
    assert log.splitlines() == ["PROJ-1: fix the build", "PROJ-1: first", "initial"]
    prompt = prompt_of(canopy_env, int(fix["id"]))
    assert prompt.startswith("# canopy worker: resume")
    assert '## Why you were resumed\n\n- `ci`: checks failed on the PR: fix them, as "Failed checks" below says.\n' in (
        prompt
    )
    assert "## Failed checks\n\nWhen `ci` is among the reasons above" in prompt
    assert "PR: https://example.test/pr/1." in prompt  # the implement worker reported it
    assert "This is attempt 1 of 6." in prompt
    assert CHECK in prompt


def test_a_red_check_and_a_review_comment_in_one_tick_make_one_run(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        dispatch_and_run(conn, *LABEL, "--kind", "implement")
    both = canopy(
        "dispatch",
        "PROJ-1",
        "--repo",
        "repo",
        *RESUME,
        "--reason",
        "review",
        "--reason",
        "ci",
        "--cursor",
        "ci=run-77",
        "--cursor",
        "review=2026-10-17T09:30:00Z",
        "--context",
        f"{CHECK}, and address review comment 1501 by octocat on PR 1",
    )
    with worker_does(*commit_and_push("agent/PROJ-1-work", "PROJ-1: fix and address")), overseer_does(both):
        assert main(["tick"]) == 0
        tick = last_tick(conn)
        assert [d.action for d in db.decisions_for_tick(conn, tick.id)] == ["queried", "dispatch:resume"]
        run = wait_for_run(conn, 2)
    assert (run["kind"], run["status"]) == ("resume", "done")
    # One run, one push, for both; its reasons in the vocabulary's order, as the decision names them.
    assert db.run_reasons(conn, [2]) == {2: ("ci", "review")}
    assert "for ci, review" in db.decisions_for_tick(conn, tick.id)[1].rationale
    assert git("log", "--format=%s", "agent/PROJ-1-work", cwd=git_pool.origin).splitlines()[0] == (
        "PROJ-1: fix and address"
    )
    unit = unit_of(conn, "PROJ-1")
    assert (unit["last_ci_run_id"], unit["last_review_id"]) == ("run-77", "2026-10-17T09:30:00Z")
    prompt = prompt_of(canopy_env, 2)
    assert "- `ci`: checks failed" in prompt
    assert "- `review`: review comments" in prompt


def test_resume_prompt_points_at_the_reply_and_names_the_repliers(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    canopy_env.append_user('\n[trust]\nauthorized_repliers = ["alice", "5b10ac"]\n')
    blocked = json.dumps({"status": "blocked", "summary": "unclear", "question": "which API?"})
    with worker_does(result=blocked):
        first = dispatch_and_run(conn, *LABEL, "--kind", "implement")
    assert first["status"] == "blocked"

    context = "Authorized reply: ticket comment 10234 by account alice"
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        resumed = dispatch_and_run(conn, *RESUME, "--reason", "reply", "--context", context)
    assert (resumed["kind"], resumed["status"], resumed["branch"]) == ("resume", "done", "agent/PROJ-1-work")
    # Nothing was pushed before, so the resume started from main.
    assert git("log", "--format=%s", "agent/PROJ-1-work", cwd=git_pool.origin).splitlines() == [
        "PROJ-1: the change",
        "initial",
    ]
    prompt = prompt_of(canopy_env, int(resumed["id"]))
    assert prompt.startswith("# canopy worker: resume")
    assert context in prompt
    assert "- `reply`: an authorized human's reply" in prompt
    assert "one of `alice`, `5b10ac` carries instructions" in prompt
    assert "PR: not recorded; look up the PR for `agent/PROJ-1-work` in `repo` through the GitHub MCP." in prompt
    assert "This is attempt 1 of 6." in prompt


def test_implement_prompt_without_context_or_repliers(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    with in_tick(conn):
        assert main(["dispatch", "PROJ-1", "--repo", "repo", *LABEL, "--kind", "implement"], runner=InlineRunner()) == 0
    prompt = prompt_of(canopy_env, 1)
    assert "## Context from the overseer\n\nNone.\n" in prompt
    assert "one of none (no reply may instruct you) and it is not a worker's" in " ".join(prompt.split())


def test_resuming_needs_a_recorded_branch(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    reason = "PROJ-1 has no branch in the journal for resume to continue; dispatch implement"
    assert dispatch_refused(conn, *RESUME, "--reason", "ci") == [("refused:no_branch", reason)]
    assert not treehouse_state.exists()  # refused before leasing


def test_slug_is_for_implement_only(canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection) -> None:
    reason = "resume continues the ticket's recorded branch; --slug is for implement"
    assert dispatch_refused(conn, *RESUME, "--reason", "ci", "--slug", "other") == [("refused:bad_slug", reason)]


@pytest.mark.parametrize("mode", ["live", "dry run"])
def test_fix_ci_is_refused_naming_resume(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, mode: str
) -> None:
    with_branch(conn)
    with in_tick(conn, dry_run=mode == "dry run") as tick_id:
        args = ["dispatch", "PROJ-1", "--repo", "repo", *LABEL, "--kind", "fix-ci", "--context", CHECK]
        assert main(args, runner=InlineRunner()) == 1
        made = decisions(conn, tick_id)
    reason = "fix-ci is retired: a resume fixes CI now; dispatch resume --reason ci"
    assert made == [("refused:bad_kind", reason)]
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        (
            (),
            (
                "--reason is required for a resume: name why it runs, one or more of ci, review, reply, conflict, "
                "no_pr, retarget"
            ),
        ),
        (("--reason", "review", "--cursor", "ci=run-7"), "--cursor ci is handled by a resume for ci: add --reason ci"),
        (
            ("--reason", "ci", "--cursor", "review=2026-10-17T09:30:00Z"),
            "--cursor review is handled by a resume for review: add --reason review",
        ),
        (
            ("--reason", "ci", "--cursor", "comment=c1"),
            "--cursor comment is handled by a resume for reply: add --reason reply",
        ),
        (
            ("--reason", "ci", "--cursor", "message=4"),
            "--cursor message is handled by a resume for reply: add --reason reply",
        ),
        (
            ("--reason", "retarget", "--base", "agent/PROJ-9-other"),
            "--reason retarget is for a PR whose blocker merged, and --base says it is still open",
        ),
    ],
)
def test_a_resume_names_why_it_runs_and_each_cursor_needs_its_reason(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, args: tuple[str, ...], reason: str
) -> None:
    with_branch(conn)
    assert dispatch_refused(conn, *RESUME, *args) == [("refused:bad_reason", reason)]
    assert not treehouse_state.exists()  # refused before leasing


def test_a_reason_is_for_resume_only(canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection) -> None:
    assert dispatch_refused(conn, *LABEL, "--kind", "implement", "--reason", "ci") == [
        ("refused:bad_reason", "--reason says why a resume runs; it is for resume only")
    ]


def test_implement_attempt_limit_refuses_and_raises_attention(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(result=json.dumps({"status": "failed", "summary": "could not build"})):
        for _ in range(2):
            assert dispatch_and_run(conn, *LABEL, "--kind", "implement")["status"] == "failed"
    reason = "PROJ-1 in repo has had 2 implement runs and the limit is 2"
    assert dispatch_refused(conn, *LABEL, "--kind", "implement") == [
        ("refused:attempt_limit", reason),
        ("attention:attempt_limit", reason),
    ]
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 2
    assert [(i.ticket_key, i.reason) for i in attention.current(conn)] == [("PROJ-1", "attempt_limit")]


def test_a_limit_of_zero_disables_the_kind(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    canopy_env.append_user("\n[policy]\nmax_resume_attempts = 0\n")
    with_branch(conn)
    [first, _] = dispatch_refused(conn, *RESUME, "--reason", "ci")
    assert first == ("refused:attempt_limit", "PROJ-1 in repo has had 0 resume runs and the limit is 0")


def test_one_limit_counts_every_resume_and_old_fix_ci_run_and_their_grants(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    canopy_env.append_user("\n[policy]\nmax_resume_attempts = 3\n")
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        dispatch_and_run(conn, *LABEL, "--kind", "implement")
        # Two fix-ci runs from before a resume fixed CI, and a fix-ci grant the operator gave then.
        old_fix_ci(conn, ended=datetime.now(UTC) - timedelta(hours=3))
        old_fix_ci(conn, ended=datetime.now(UTC) - timedelta(hours=2))
        conn.execute(
            "INSERT INTO attempt_grants (ticket_key, repo, kind, runs, granted_at) "
            "VALUES ('PROJ-1', 'repo', 'fix-ci', 1, ?)",
            (db.now(),),
        )
        # 2 old runs of a limit of 3 plus 1 granted: two resumes left, whatever they are for.
        assert dispatch_and_run(conn, *RESUME, "--reason", "review")["status"] == "done"
        resumed = dispatch_and_run(conn, *RESUME, "--reason", "conflict")
        assert "This is attempt 4 of 4." in prompt_of(canopy_env, int(resumed["id"]))
    reason = "PROJ-1 in repo has had 4 resume runs and the limit is 4"
    assert dispatch_refused(conn, *RESUME, "--reason", "no_pr") == [
        ("refused:attempt_limit", reason),
        ("attention:attempt_limit", reason),
    ]


def test_the_cooldown_holds_a_resume_for_ci_alone_after_a_run_that_worked_on_ci(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        dispatch_and_run(conn, *LABEL, "--kind", "implement")
        # An implement did not work on CI: nothing holds the first resume for it.
        fix = dispatch_and_run(conn, *RESUME, "--reason", "ci")
        until = db.format_time(db.parse_time(str(fix["ended_at"])) + timedelta(minutes=30))
        held = ("refused:cooldown", f"a resume for CI alone in PROJ-1 in repo may run again after {until}")
        assert dispatch_refused(conn, *RESUME, "--reason", "ci") == [held]
        # A resume with review feedback is not held, and takes the failed check along: its end restarts the cooldown.
        both = dispatch_and_run(conn, *RESUME, "--reason", "ci", "--reason", "review")
        assert both["status"] == "done"
        until = db.format_time(db.parse_time(str(both["ended_at"])) + timedelta(minutes=30))
        assert dispatch_refused(conn, *RESUME, "--reason", "ci") == [
            ("refused:cooldown", f"a resume for CI alone in PROJ-1 in repo may run again after {until}")
        ]
        cool_down(conn)
        # A resume that did not work on CI starts no cooldown.
        assert dispatch_and_run(conn, *RESUME, "--reason", "review")["status"] == "done"
        assert dispatch_and_run(conn, *RESUME, "--reason", "ci")["status"] == "done"


def test_an_old_fix_ci_run_starts_the_cooldown_too(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    with_branch(conn)
    fix = old_fix_ci(conn)
    until = db.format_time(db.parse_time(str(present(db.get_run(conn, fix))["ended_at"])) + timedelta(minutes=30))
    assert dispatch_refused(conn, *RESUME, "--reason", "ci") == [
        ("refused:cooldown", f"a resume for CI alone in PROJ-1 in repo may run again after {until}")
    ]


def test_a_fix_ci_prompt_override_refuses_every_resume_and_says_so(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        dispatch_and_run(conn, *LABEL, "--kind", "implement")
    # The operator's overrides, where canopy looks for them by default.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir(parents=True)
    override = overrides / "worker-fix-ci.md"
    override.write_text("# my fix-ci\n\n{{LABELS}}\n")
    made = dispatch_refused(conn, *RESUME, "--reason", "review")
    reason = (
        f"{override} overrides a fix-ci prompt, which canopy no longer uses: a resume fixes CI now. Merge what it adds "
        "into your override of worker-resume.md (or worker-resume-private.md), under its failed-checks section, then "
        "remove it"
    )
    assert made == [("refused:bad_prompt", reason), ("attention:fix_ci_override", reason)]
    assert [(i.ticket_key, i.reason) for i in attention.current(conn)] == [("PROJ-1", "fix_ci_override")]
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1  # the implement alone
    override.unlink()
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        assert dispatch_and_run(conn, *RESUME, "--reason", "review")["status"] == "done"


def test_cursors_advance_only_when_the_worker_starts(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    canopy_env.append_user("\n[capacity]\nmax_workers = 1\n")
    with in_tick(conn):
        runner = InlineRunner()
        first = ["dispatch", "PROJ-1", "--repo", "repo", *LABEL, "--kind", "implement", "--cursor", "comment=c1"]
        assert main(first, runner=runner) == 0
        args = [
            "dispatch",
            "PROJ-2",
            "--repo",
            "repo",
            *LABEL,
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


def test_state_block_shows_attempts_the_cooldown_and_a_resumes_reasons(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        dispatch_and_run(conn, *LABEL, "--kind", "implement")
        old_fix_ci(conn, ended=datetime.now(UTC) - timedelta(hours=2))
        fix = dispatch_and_run(conn, *RESUME, "--reason", "ci", "--reason", "conflict")
    with overseer_does(canopy("decide", "PROJ-1", "wait", "--rationale", "the CI cooldown holds")):
        assert main(["tick"]) == 0
    state = state_block(agent_log)
    [ticket] = state["tickets"]
    [unit] = ticket["units"]
    assert (unit["repo"], unit["branch"]) == ("repo", "agent/PROJ-1-work")
    # The old fix-ci run is a resume attempt; its kind is in none of the counts.
    assert unit["attempts"] == {"implement": 1, "resume": 2}
    until = db.parse_time(str(fix["ended_at"])) + timedelta(minutes=30)
    assert unit["ci_cooldown_until"] == db.format_time(until)
    assert ticket["last_run"]["reasons"] == ["ci", "conflict"]
    assert state["policy"]["max_resume_attempts"] == 6
    assert state["policy"]["ci_cooldown_minutes"] == 30
    assert db.parse_time(state["now"]) < until


def test_grant_of_fix_ci_is_refused_naming_resume(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    with_branch(conn)
    old_fix_ci(conn)
    assert operator("grant", "PROJ-1", "fix-ci") == 1
    assert conn.execute("SELECT count(*) FROM attempt_grants").fetchone()[0] == 0


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
    """M3 acceptance, against the fakes, as M56 left it. An overseer that asks for a resume for CI every tick, as a PR
    whose checks keep failing would make it, gets one run per cooldown window and none past `max_resume_attempts`."""
    canopy_env.append_user("\n[policy]\nmax_resume_attempts = 2\n")
    with (
        worker_does(*commit_and_push("agent/PROJ-1-work")),
        overseer_does(canopy("dispatch", "PROJ-1", "--repo", "repo", *LABEL, "--kind", "implement")),
    ):
        assert main(["tick"]) == 0
        wait_for_run(conn, 1)

    fix = canopy(
        "dispatch",
        "PROJ-1",
        "--repo",
        "repo",
        *RESUME,
        "--reason",
        "ci",
        "--context",
        "checks failed",
        "--cursor",
        "ci=run-1",
    )
    with worker_does(*commit_and_push("agent/PROJ-1-work")), overseer_does(fix):
        assert main(["tick"]) == 0
        assert tick_decisions(conn) == ["queried", "dispatch:resume"]
        assert wait_for_run(conn, 2)["status"] == "done"
        # Every further tick inside the window is refused, however often the overseer asks. The tick itself is fine.
        for _ in range(2):
            assert main(["tick"]) == 0
            assert tick_decisions(conn) == ["queried", "refused:cooldown"]

        cool_down(conn)
        assert main(["tick"]) == 0
        assert tick_decisions(conn) == ["queried", "dispatch:resume"]
        assert wait_for_run(conn, 3)["status"] == "done"
        # That was the last attempt: the limit refuses, whether or not the window has passed, and raises attention.
        for _ in range(2):
            assert main(["tick"]) == 0
            assert tick_decisions(conn) == ["queried", "refused:attempt_limit", "attention:attempt_limit"]
            cool_down(conn)

    assert [r["kind"] for r in conn.execute("SELECT kind FROM runs ORDER BY id")] == ["implement", "resume", "resume"]
    assert [(i.ticket_key, i.reason) for i in attention.current(conn)] == [("PROJ-1", "attempt_limit")]
    # Advanced by the dispatches that started, not by the refused ones.
    assert unit_of(conn, "PROJ-1")["last_ci_run_id"] == "run-1"


def test_status_shows_a_resumes_reasons_beside_its_kind(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        dispatch_and_run(conn, *LABEL, "--kind", "implement")
        dispatch_and_run(conn, *RESUME, "--reason", "review", "--reason", "ci")
    old_fix_ci(conn)
    capsys.readouterr()
    assert operator("status") == 0
    out = capsys.readouterr().out
    assert "  PROJ-1  resume (ci, review)  done  " in out
    # An old fix-ci run reads as it ran, and an implement has no reasons.
    assert "  PROJ-1  fix-ci  done  " in out
    assert "  PROJ-1  implement  done  " in out
