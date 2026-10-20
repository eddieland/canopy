"""Resume dispatches, their reasons, attempt limits, the CI cooldown, and cursors on dispatch (DESIGN §8).

A `resume` takes everything that comes back to a PR, a failed check among it (M56); `fix-ci` runs from before that
still read, and count as `resume` runs.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canopy.core import db
from canopy.core.vocab import ResumeReason, RunKind
from tests.canopy.helpers import KEY, canopy, in_tick, present, unit_of, waits
from tests.canopy.scenario_helpers import Scenario, asks, dispatches, fails, pushes
from tests.conftest import CanopyEnv, GitPool, git

LABEL = ("--label", "agent-ready-tester")
RESUME = (*LABEL, "--kind", "resume")
CI, REVIEW, CONFLICT = ResumeReason.CI, ResumeReason.REVIEW, ResumeReason.CONFLICT
CHECK = "Check unit-tests failed on run 77: https://example.test/runs/77"


def resumes(*reasons: ResumeReason) -> list[str]:
    """The overseer resumes PROJ-1 for `reasons`."""
    return dispatches(kind=RunKind.RESUME, reasons=reasons)


def held(until: datetime) -> tuple[str, str]:
    """The refusal of a resume for CI alone while the cooldown holds, until `until`."""
    return ("refused:cooldown", f"a resume for CI alone in PROJ-1 in repo may run again after {db.format_time(until)}")


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


def test_a_red_check_resumes_the_recorded_branch_with_the_checks_named(scenario: Scenario, git_pool: GitPool) -> None:
    first = scenario.run(dispatches(slug="add-login"), worker=pushes("agent/PROJ-1-add-login", "PROJ-1: first"))
    assert first.status == "done"

    fix = dispatches(kind=RunKind.RESUME, reasons=[CI], context=CHECK, cursors={"ci": "run-77"})
    resumed = scenario.run(fix, worker=pushes("agent/PROJ-1-add-login", "PROJ-1: fix the build"))
    assert (resumed.kind, resumed.status, resumed.branch) == ("resume", "done", "agent/PROJ-1-add-login")
    assert resumed.reasons == (CI,)
    assert unit_of(scenario.conn, "PROJ-1").last_ci_run_id == "run-77"

    # The worker started from the pushed branch, not from main.
    log = git("log", "--format=%s", "agent/PROJ-1-add-login", cwd=git_pool.origin)
    assert log.splitlines() == ["PROJ-1: fix the build", "PROJ-1: first", "initial"]
    prompt = resumed.prompt
    assert prompt.startswith("# canopy worker: resume")
    assert '## Why you were resumed\n\n- `ci`: checks failed on the PR: fix them, as "Failed checks" below says.\n' in (
        prompt
    )
    assert "## Failed checks\n\nWhen `ci` is among the reasons above" in prompt
    assert "PR: https://example.test/pr/1." in prompt  # the implement worker reported it
    assert "This is attempt 1 of 6." in prompt
    assert CHECK in prompt


def test_a_red_check_and_a_review_comment_in_one_tick_make_one_run(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.run(worker=pushes())
    both = dispatches(
        kind=RunKind.RESUME,
        reasons=[REVIEW, CI],
        cursors={"ci": "run-77", "review": "2026-10-17T09:30:00Z"},
        context=f"{CHECK}, and address review comment 1501 by octocat on PR 1",
    )
    ticked = scenario.tick(both, worker=pushes(message="PROJ-1: fix and address"))
    assert ticked.actions == ["queried", "dispatch:resume"]
    [run] = ticked.runs
    assert (run.kind, run.status) == ("resume", "done")
    # One run, one push, for both; its reasons in the vocabulary's order, as the decision names them.
    assert run.reasons == (CI, REVIEW)
    assert "for ci, review" in ticked.decisions[1].rationale
    assert git("log", "--format=%s", "agent/PROJ-1-work", cwd=git_pool.origin).splitlines()[0] == (
        "PROJ-1: fix and address"
    )
    unit = unit_of(scenario.conn, "PROJ-1")
    assert (unit.last_ci_run_id, unit.last_review_id) == ("run-77", "2026-10-17T09:30:00Z")
    assert "- `ci`: checks failed" in run.prompt
    assert "- `review`: review comments" in run.prompt


def test_resume_prompt_points_at_the_reply_and_names_the_repliers(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"authorized_repliers": ["alice", "5b10ac"]})
    first = scenario.run(worker=asks("which API?"))
    assert first.status == "blocked"

    context = "Authorized reply: ticket comment 10234 by account alice"
    resume = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REPLY], context=context)
    resumed = scenario.run(resume, worker=pushes())
    assert (resumed.kind, resumed.status, resumed.branch) == ("resume", "done", "agent/PROJ-1-work")
    # Nothing was pushed before, so the resume started from main.
    assert git("log", "--format=%s", "agent/PROJ-1-work", cwd=git_pool.origin).splitlines() == [
        "PROJ-1: the change",
        "initial",
    ]
    prompt = resumed.prompt
    assert prompt.startswith("# canopy worker: resume")
    assert context in prompt
    assert "- `reply`: an authorized human's reply" in prompt
    assert "one of `alice`, `5b10ac` carries instructions" in prompt
    assert "PR: not recorded; look up the PR for `agent/PROJ-1-work` in `repo` through the GitHub MCP." in prompt
    assert "This is attempt 1 of 6." in prompt


def test_implement_prompt_without_context_or_repliers(scenario: Scenario, git_pool: GitPool) -> None:
    prompt = scenario.run(worker=asks()).prompt
    assert "## Context from the overseer\n\nNone.\n" in prompt
    assert "one of none (no reply may instruct you) and it is not a worker's" in " ".join(prompt.split())


def test_resuming_needs_a_recorded_branch(scenario: Scenario, treehouse_state: Path) -> None:
    reason = "PROJ-1 has no branch in the journal for resume to continue; dispatch implement"
    assert scenario.refuses(resumes(CI)) == [("refused:no_branch", reason)]
    assert not treehouse_state.exists()  # refused before leasing


def test_slug_is_for_implement_only(scenario: Scenario) -> None:
    reason = "resume continues the ticket's recorded branch; --slug is for implement"
    other = dispatches(kind=RunKind.RESUME, reasons=[CI], slug="other")
    assert scenario.refuses(other) == [("refused:bad_slug", reason)]


@pytest.mark.parametrize("mode", ["live", "dry run"])
def test_fix_ci_is_refused_naming_resume(scenario: Scenario, mode: str) -> None:
    with_branch(scenario.conn)
    fix_ci = canopy("dispatch", KEY, "--repo", "repo", *LABEL, "--kind", "fix-ci", "--context", CHECK)
    reason = "fix-ci is retired: a resume fixes CI now; dispatch resume --reason ci"
    assert scenario.refuses(fix_ci, dry_run=mode == "dry run") == [("refused:bad_kind", reason)]


@pytest.mark.parametrize("mode", ["live", "dry run"])
def test_split_is_refused_naming_follow_ups(scenario: Scenario, mode: str) -> None:
    split = canopy("dispatch", KEY, "--repo", "repo", *LABEL, "--kind", "split", "--context", "split it")
    [(action, reason)] = scenario.refuses(split, dry_run=mode == "dry run")
    assert action == "refused:bad_kind"
    assert reason.startswith("split is retired: a worker files follow-up tickets now")


@pytest.mark.parametrize("mode", ["live", "dry run"])
def test_needs_plan_is_refused_naming_plan(scenario: Scenario, mode: str) -> None:
    triage = canopy("dispatch", KEY, "--repo", "repo", *LABEL, "--kind", "needs-plan", "--context", "is it trivial?")
    reason = "needs-plan is retired: a ticket that needs a plan is planned; dispatch plan"
    assert scenario.refuses(triage, dry_run=mode == "dry run") == [("refused:bad_kind", reason)]


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
    scenario: Scenario, treehouse_state: Path, args: tuple[str, ...], reason: str
) -> None:
    with_branch(scenario.conn)
    assert scenario.refuses(resumes() + list(args)) == [("refused:bad_reason", reason)]
    assert not treehouse_state.exists()  # refused before leasing


def test_a_reason_is_for_resume_only(scenario: Scenario) -> None:
    assert scenario.refuses(dispatches(reasons=[CI])) == [
        ("refused:bad_reason", "--reason says why a resume runs; it is for resume only")
    ]


def test_implement_attempt_limit_refuses_and_raises_attention(scenario: Scenario, git_pool: GitPool) -> None:
    for _ in range(2):
        assert scenario.run(worker=fails()).status == "failed"
    reason = "PROJ-1 in repo has had 2 implement runs and the limit is 2"
    assert scenario.refuses(dispatches()) == [("refused:attempt_limit", reason), ("attention:attempt_limit", reason)]
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 2
    assert scenario.attention() == [("PROJ-1", "attempt_limit")]


def test_a_limit_of_zero_disables_the_kind(scenario: Scenario) -> None:
    scenario.configures(policy={"max_resume_attempts": 0})
    with_branch(scenario.conn)
    [first, _] = scenario.refuses(resumes(CI))
    assert first == ("refused:attempt_limit", "PROJ-1 in repo has had 0 resume runs and the limit is 0")


def test_one_limit_counts_every_resume_and_old_fix_ci_run_and_their_grants(
    scenario: Scenario, git_pool: GitPool
) -> None:
    scenario.configures(policy={"max_resume_attempts": 3})
    scenario.run(worker=pushes())
    # Two fix-ci runs from before a resume fixed CI, and a fix-ci grant the operator gave then.
    old_fix_ci(scenario.conn, ended=datetime.now(UTC) - timedelta(hours=3))
    old_fix_ci(scenario.conn, ended=datetime.now(UTC) - timedelta(hours=2))
    scenario.conn.execute(
        "INSERT INTO attempt_grants (ticket_key, repo, kind, runs, granted_at) "
        "VALUES ('PROJ-1', 'repo', 'fix-ci', 1, ?)",
        (db.now(),),
    )
    # 2 old runs of a limit of 3 plus 1 granted: two resumes left, whatever they are for.
    assert scenario.run(resumes(REVIEW), worker=pushes()).status == "done"
    resumed = scenario.run(resumes(CONFLICT), worker=pushes())
    assert "This is attempt 4 of 4." in resumed.prompt
    reason = "PROJ-1 in repo has had 4 resume runs and the limit is 4"
    assert scenario.refuses(resumes(ResumeReason.NO_PR)) == [
        ("refused:attempt_limit", reason),
        ("attention:attempt_limit", reason),
    ]


def test_the_cooldown_holds_a_resume_for_ci_alone_after_a_run_that_worked_on_ci(
    scenario: Scenario, git_pool: GitPool
) -> None:
    scenario.run(worker=pushes())
    # An implement did not work on CI: nothing holds the first resume for it.
    fix = scenario.run(resumes(CI), worker=pushes())
    assert scenario.refuses(resumes(CI)) == [held(fix.ended_at + timedelta(minutes=30))]
    # A resume with review feedback is not held, and takes the failed check along: its end restarts the cooldown.
    both = scenario.run(resumes(CI, REVIEW), worker=pushes())
    assert both.status == "done"
    assert scenario.refuses(resumes(CI)) == [held(both.ended_at + timedelta(minutes=30))]
    scenario.time_passes(minutes=31)
    # A resume that did not work on CI starts no cooldown.
    assert scenario.run(resumes(REVIEW), worker=pushes()).status == "done"
    assert scenario.run(resumes(CI), worker=pushes()).status == "done"


def test_an_old_fix_ci_run_starts_the_cooldown_too(scenario: Scenario) -> None:
    with_branch(scenario.conn)
    fix = present(db.get_run(scenario.conn, old_fix_ci(scenario.conn)))
    assert scenario.refuses(resumes(CI)) == [held(db.parse_time(str(fix["ended_at"])) + timedelta(minutes=30))]


def test_a_fix_ci_prompt_override_refuses_every_resume_and_says_so(
    scenario: Scenario, canopy_env: CanopyEnv, git_pool: GitPool
) -> None:
    scenario.run(worker=pushes())
    # The operator's overrides, where canopy looks for them by default.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir(parents=True)
    override = overrides / "worker-fix-ci.md"
    override.write_text("# my fix-ci\n\n{{LABELS}}\n")
    reason = (
        f"{override} overrides a fix-ci prompt, which canopy no longer uses: a resume fixes CI now. Merge what it adds "
        "into your override of worker-resume.md (or worker-resume-private.md), under its failed-checks section, then "
        "remove it"
    )
    assert scenario.refuses(resumes(REVIEW)) == [("refused:bad_prompt", reason), ("attention:fix_ci_override", reason)]
    assert scenario.attention() == [("PROJ-1", "fix_ci_override")]
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1  # the implement alone
    override.unlink()
    assert scenario.run(resumes(REVIEW), worker=pushes()).status == "done"


def test_cursors_advance_only_when_the_worker_starts(scenario: Scenario, git_pool: GitPool) -> None:
    conn = scenario.conn
    scenario.configures(capacity={"max_workers": 1})
    scenario.starts(dispatches(cursors={"comment": "c1"}))
    cursors = {"comment": "c2", "review": "2026-10-07T20:58:50Z"}
    assert scenario.refuses(dispatches("PROJ-2", cursors=cursors)) == [
        ("refused:capacity", "1 of 1 workers are running")
    ]
    rows = {r["key"]: r for r in conn.execute("SELECT * FROM tickets")}
    assert rows["PROJ-1"]["last_comment_id"] == "c1"
    assert rows["PROJ-2"]["last_comment_id"] is None
    assert db.units(conn, "PROJ-2") == []  # nor its review cursor, nor a unit at all


def test_state_block_shows_attempts_the_cooldown_and_a_resumes_reasons(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.run(worker=pushes())
    old_fix_ci(scenario.conn, ended=datetime.now(UTC) - timedelta(hours=2))
    fix = scenario.run(resumes(CI, CONFLICT), worker=pushes())
    scenario.tick(*waits("PROJ-1", rationale="the CI cooldown holds"))
    state = scenario.state()
    [ticket] = state["tickets"]
    [unit] = ticket["units"]
    assert (unit["repo"], unit["branch"]) == ("repo", "agent/PROJ-1-work")
    # The old fix-ci run is a resume attempt; its kind is in none of the counts.
    assert unit["attempts"] == {"implement": 1, "resume": 2}
    until = fix.ended_at + timedelta(minutes=30)
    assert unit["ci_cooldown_until"] == db.format_time(until)
    assert ticket["last_run"]["reasons"] == ["ci", "conflict"]
    assert state["policy"]["max_resume_attempts"] == 6
    assert state["policy"]["ci_cooldown_minutes"] == 30
    assert db.parse_time(state["now"]) < until


def test_grant_of_fix_ci_is_refused_naming_resume(scenario: Scenario) -> None:
    with_branch(scenario.conn)
    old_fix_ci(scenario.conn)
    assert "grant resume instead" in scenario.operator("grant", "PROJ-1", "fix-ci", code=1).err
    assert scenario.conn.execute("SELECT count(*) FROM attempt_grants").fetchone()[0] == 0


def test_red_pr_gets_one_fix_per_cooldown_window_and_stops_at_the_limit(scenario: Scenario, git_pool: GitPool) -> None:
    """M3 acceptance, against the fakes, as M56 left it. An overseer that asks for a resume for CI every tick, as a PR
    whose checks keep failing would make it, gets one run per cooldown window and none past `max_resume_attempts`."""
    scenario.configures(policy={"max_resume_attempts": 2})
    scenario.tick(dispatches(), worker=pushes())

    fix = dispatches(kind=RunKind.RESUME, reasons=[CI], context="checks failed", cursors={"ci": "run-1"})
    ticked = scenario.tick(fix, worker=pushes())
    assert ticked.actions == ["queried", "dispatch:resume"]
    assert [r.status for r in ticked.runs] == ["done"]
    # Every further tick inside the window is refused, however often the overseer asks. The tick itself is fine.
    for _ in range(2):
        assert scenario.tick(fix).actions == ["queried", "refused:cooldown"]

    scenario.time_passes(minutes=31)
    ticked = scenario.tick(fix, worker=pushes())
    assert ticked.actions == ["queried", "dispatch:resume"]
    assert [r.status for r in ticked.runs] == ["done"]
    # That was the last attempt: the limit refuses, whether or not the window has passed, and raises attention.
    for _ in range(2):
        assert scenario.tick(fix).actions == ["queried", "refused:attempt_limit", "attention:attempt_limit"]
        scenario.time_passes(minutes=31)

    assert [r["kind"] for r in scenario.conn.execute("SELECT kind FROM runs ORDER BY id")] == [
        "implement",
        "resume",
        "resume",
    ]
    assert scenario.attention() == [("PROJ-1", "attempt_limit")]
    # Advanced by the dispatches that started, not by the refused ones.
    assert unit_of(scenario.conn, "PROJ-1").last_ci_run_id == "run-1"


def test_status_shows_a_resumes_reasons_beside_its_kind(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.run(worker=pushes())
    scenario.run(resumes(REVIEW, CI), worker=pushes())
    old_fix_ci(scenario.conn)
    out = scenario.operator("status").out
    assert "  PROJ-1  resume (ci, review)  done  " in out
    # An old fix-ci run reads as it ran, and an implement has no reasons.
    assert "  PROJ-1  fix-ci  done  " in out
    assert "  PROJ-1  implement  done  " in out
