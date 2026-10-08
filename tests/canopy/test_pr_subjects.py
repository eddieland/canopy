"""The operator's own PRs as subjects (DESIGN §23, ROADMAP M14): `canopy dispatch REPO#N --branch`, its guards, the
PR's head branch in `_run`, the PR worker prompts, the question that waits in canopy, and `canopy show` and `reply` on a
PR, against the fake treehouse, a fake overseer, and a fake worker over real git."""

import json
import sqlite3
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db
from canopy.loop import attention
from tests.canopy.helpers import InlineRunner, commit_and_push, in_tick, journal, pool, unit_of, worker_does
from tests.canopy.test_loop import canopy, context, overseer_does
from tests.canopy.test_web import signed_in_client
from tests.conftest import CanopyEnv, GitPool, git

# The workspace of one in `canopy_env` is the repository `repo`.
KEY = "repo#7"
BRANCH = "feature/login.v2"
LABEL = ("--label", "agent-ready-tester")
PR_URL = "https://github.test/acme/repo/pull/7"
QUESTION = "The reviewer wants the retry removed, but the flaky test needs it. Which?"


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


@pytest.fixture
def pr_branch(git_pool: GitPool) -> str:
    """The operator's PR's head branch, pushed by hand: one commit past main."""
    slot = git_pool.slots[1]
    git("commit", "--quiet", "--allow-empty", "-m", "by hand", cwd=slot)
    git("push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=slot)
    git("checkout", "--quiet", "--detach", "origin/main", cwd=slot)
    return BRANCH


def result(status: str = "done", question: str | None = None) -> str:
    return json.dumps(
        {"status": status, "branch": BRANCH, "prs": {"repo": PR_URL}, "summary": "fixed it", "question": question}
    )


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str, str]]:
    return [(str(d["action"]), str(d["rationale"])) for d in db.decisions_for_tick(conn, tick_id)]


def dispatch(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, *args: str, key: str = KEY, runner: InlineRunner
) -> tuple[int, list[tuple[str, str]]]:
    tick_id = in_tick(conn, monkeypatch)
    code = main(["dispatch", key, *args], runner=runner)
    db.finish_tick(conn, tick_id, "ok", "test")
    monkeypatch.delenv("CANOPY_TICK_ID")
    return code, decisions(conn, tick_id)


def run_it(conn: sqlite3.Connection, runner: InlineRunner) -> sqlite3.Row:
    run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
    assert main(["_run", str(run_id)], runner=runner) == 0
    run = db.get_run(conn, run_id)
    assert run is not None
    return run


def branch_of(conn: sqlite3.Connection) -> str | None:
    ticket = db.get_ticket(conn, KEY)
    return None if ticket is None else ticket["branch"]


def prompt_of(env: CanopyEnv, run_id: int) -> str:
    return (env.state_dir / "runs" / f"{run_id}.prompt").read_text()


def test_fix_ci_on_the_operators_pr_continues_its_head_branch(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    pr_branch: str,
    agent_log: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = git_pool.remote_head(pr_branch)
    worker_does(monkeypatch, *commit_and_push(pr_branch, "fix the build"), result=result())
    runner = InlineRunner()
    context_text = "Check unit-tests failed on run 77"
    code, recorded = dispatch(
        conn,
        monkeypatch,
        *LABEL,
        "--kind",
        "fix-ci",
        "--branch",
        pr_branch,
        "--cursor",
        "ci=77",
        "--context",
        context_text,
        runner=runner,
    )
    assert code == 0, recorded
    [(action, rationale)] = recorded
    assert action == "dispatch:fix-ci"
    assert f"{pr_branch} in" in rationale
    assert "label agent-ready-tester" in rationale

    run = run_it(conn, runner)
    assert (run["ticket_key"], run["kind"], run["status"], run["branch"]) == (KEY, "fix-ci", "done", pr_branch)
    # The worker started from the PR's pushed head and its push landed on it, without force.
    log = git("log", "--format=%s", pr_branch, cwd=git_pool.origin).splitlines()
    assert log == ["fix the build", "by hand", "initial"]
    assert git("rev-parse", f"{pr_branch}~1", cwd=git_pool.origin) == before
    assert git_pool.remote_head("main") == git("rev-parse", "main", cwd=git_pool.origin)
    # The journal keeps it as a ticket row keyed by the PR, with one unit in its repository.
    ticket = db.get_ticket(conn, KEY)
    assert ticket is not None
    assert ticket["branch"] == pr_branch
    unit = unit_of(conn, KEY)
    assert (unit["repo"], unit["branch"], unit["pr_url"], unit["last_ci_run_id"]) == ("repo", pr_branch, PR_URL, "77")
    # Its messages are the PR's, not a ticket's.
    [report] = db.messages_of(conn, conversation.PR, KEY, 10)
    assert report["body"] == f"fixed it\n{PR_URL}"
    assert db.messages_of(conn, conversation.TICKET, KEY, 10) == []

    prompt = prompt_of(canopy_env, int(run["id"]))
    assert prompt.startswith("# canopy worker: fix CI on the operator's PR")
    assert f"You are fixing CI on {KEY}, a PR the operator wrote by hand" in prompt
    assert f"Its head branch `{pr_branch}` is checked out" in prompt
    assert "`agent-ready-tester`" in prompt
    assert "the account the GitHub MCP is authenticated as" in prompt
    assert "not recorded yet: it is #7" in prompt
    assert context_text in prompt
    assert "{{" not in prompt
    [worker] = [json.loads(line) for line in agent_log.read_text().splitlines()]
    assert "canopy-worker" in worker["argv"]

    # A later run reads the PR the first one recorded, and continues the same branch.
    worker_does(monkeypatch, result=result())
    code, recorded = dispatch(
        conn, monkeypatch, *LABEL, "--kind", "resume", "--branch", pr_branch, "--context", "c", runner=runner
    )
    assert code == 0, recorded
    resumed = run_it(conn, runner)
    prompt = prompt_of(canopy_env, int(resumed["id"]))
    assert prompt.startswith("# canopy worker: resume the operator's PR")
    assert f"The PR: {PR_URL}." in prompt


@pytest.mark.parametrize(
    ("args", "guard"),
    [
        (("--kind", "implement", "--branch", BRANCH), "bad_kind"),
        (("--kind", "split", "--request", "c-1", "--repo", "repo", "--branch", BRANCH), "bad_kind"),
        (("--kind", "fix-ci"), "bad_branch"),
        (("--kind", "fix-ci", "--branch", "agent/PROJ-1-work"), "bad_branch"),
        (("--kind", "fix-ci", "--branch", "feature..x"), "bad_branch"),
        (("--kind", "fix-ci", "--branch", "-delete"), "bad_branch"),
        (("--kind", "fix-ci", "--branch", "x.lock/y"), "bad_branch"),
        (("--kind", "fix-ci", "--branch", "HEAD"), "bad_branch"),
        (("--kind", "fix-ci", "--branch", BRANCH, "--slug", "s"), "bad_slug"),
        (("--kind", "fix-ci", "--branch", BRANCH, "--base", "agent/PROJ-2-x"), "bad_base"),
        (("--kind", "fix-ci", "--branch", BRANCH, "--repo", "other"), "unknown_repo"),
    ],
)
def test_a_pr_dispatch_refuses_what_a_pr_cannot_take(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    args: tuple[str, ...],
    guard: str,
) -> None:
    code, recorded = dispatch(conn, monkeypatch, *LABEL, *args, runner=InlineRunner())
    assert code == 1
    assert [action for action, _ in recorded] == [f"refused:{guard}"]
    assert db.running_runs(conn) == []


def test_a_pr_dispatch_needs_a_label_and_a_repository_here(
    canopy_env: CanopyEnv, git_pool: GitPool, pr_branch: str, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = InlineRunner()
    code, recorded = dispatch(conn, monkeypatch, "--kind", "fix-ci", "--branch", pr_branch, runner=runner)
    assert (code, recorded[0][0]) == (1, "refused:unauthorized")
    code, recorded = dispatch(
        conn, monkeypatch, *LABEL, "--kind", "fix-ci", "--branch", pr_branch, key="api#7", runner=runner
    )
    assert (code, recorded[0][0]) == (1, "refused:unknown_repo")
    assert "'api', api#7's repository, is not a repository in this workspace" in recorded[0][1]
    # A branch on a ticket is the PR's, never the ticket's.
    code, recorded = dispatch(
        conn, monkeypatch, *LABEL, "--kind", "implement", "--branch", pr_branch, key="PROJ-1", runner=runner
    )
    assert (code, recorded[0][0]) == (1, "refused:bad_branch")


def test_the_pools_base_branch_is_never_a_prs_branch_and_its_lease_goes_back(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, recorded = dispatch(conn, monkeypatch, *LABEL, "--kind", "fix-ci", "--branch", "main", runner=InlineRunner())
    assert code == 1
    [(action, rationale)] = recorded
    assert action == "refused:bad_branch"
    assert "base branch" in rationale
    assert all(slot["status"] == "available" for slot in pool(treehouse_state))
    assert branch_of(conn) is None


def test_a_prs_branch_missing_from_origin_fails_the_run_and_strands_nothing(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    pr_branch: str,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A fork's PR has its head in another repository: origin has no such branch, and canopy never makes one.
    worker_does(monkeypatch, result=result())
    runner = InlineRunner()
    assert dispatch(conn, monkeypatch, *LABEL, "--kind", "fix-ci", "--branch", "from-a-fork", runner=runner)[0] == 0
    run = run_it(conn, runner)
    assert run["status"] == "crashed"
    assert "the PR's head branch from-a-fork is not on origin" in str(run["result_json"])
    assert git_pool.remote_head("from-a-fork") is None
    assert not agent_log.exists() or agent_log.read_text() == ""
    assert all(slot["status"] == "available" for slot in pool(treehouse_state))
    # A misread branch binds nothing: once the overseer reads the PR's head right, the PR is worked on it.
    assert dispatch(conn, monkeypatch, *LABEL, "--kind", "resume", "--branch", pr_branch, runner=runner)[0] == 0
    resumed = run_it(conn, runner)
    assert (resumed["status"], resumed["branch"]) == ("done", pr_branch)
    assert branch_of(conn) == pr_branch


def test_a_prs_attempts_and_cooldown_are_its_units(
    canopy_env: CanopyEnv, git_pool: GitPool, pr_branch: str, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[policy]\nmax_fix_ci_attempts = 1\n")
    worker_does(monkeypatch, result=result())
    runner = InlineRunner()
    assert dispatch(conn, monkeypatch, *LABEL, "--kind", "fix-ci", "--branch", pr_branch, runner=runner)[0] == 0
    run_it(conn, runner)
    code, recorded = dispatch(conn, monkeypatch, *LABEL, "--kind", "fix-ci", "--branch", pr_branch, runner=runner)
    assert code == 1
    assert [a for a, _ in recorded] == ["refused:attempt_limit", "attention:attempt_limit"]
    item = conn.execute("SELECT * FROM decisions WHERE action = 'attention:attempt_limit'").fetchone()
    assert (item["ticket_key"], item["repo"]) == (KEY, None)


def test_a_blocked_prs_question_waits_in_canopy_for_the_operators_reply(  # noqa: PLR0915  (one story)
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    pr_branch: str,
    agent_log: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    worker_does(monkeypatch, result=result("blocked", QUESTION))
    runner = InlineRunner()
    assert dispatch(conn, monkeypatch, *LABEL, "--kind", "resume", "--branch", pr_branch, runner=runner)[0] == 0
    run = run_it(conn, runner)
    assert run["status"] == "blocked"
    [_, question] = db.messages_of(conn, conversation.PR, KEY, 10)
    assert (question["kind"], question["body"]) == ("question", QUESTION)

    # The harness raises it, as for a private ticket: the worker asked in canopy, not on the PR.
    overseer_does(monkeypatch, canopy("decide", KEY, "wait", "--rationale", "waiting on the operator"))
    assert main(["tick"]) == 0
    [item] = [i for i in attention.listed(context(canopy_env)) if i.reason == "awaiting_reply"]
    assert item.ticket_key == KEY
    assert QUESTION in item.detail
    overseer = json.loads(agent_log.read_text().splitlines()[-1])
    state = json.loads(overseer["argv"][-1].split("```json\n", 1)[1].split("\n```", 1)[0])
    [subject] = [t for t in state["tickets"] if t["key"] == KEY]
    assert subject["pr"] == {
        "repo": "repo",
        "number": 7,
        "awaiting_reply": {"message_id": question["id"], "run_id": run["id"], "at": question["at"]},
    }
    assert "private" not in subject
    assert "operator" not in subject

    capsys.readouterr()
    assert main(["show", KEY]) == 0
    shown = capsys.readouterr().out
    assert f"{KEY}: your PR" in shown
    assert QUESTION in shown
    assert f"Message {question['id']} waits on your answer" in shown
    # Once the run recorded the PR's URL, the URL names it too; an unknown one names nothing.
    assert main(["show", PR_URL]) == 0
    assert QUESTION in capsys.readouterr().out
    assert main(["show", "https://github.test/acme/repo/pull/8"]) == 1
    assert "show refused (unknown)" in capsys.readouterr().err

    answer = "Keep the retry, and say why on the PR."
    assert main(["reply", PR_URL, answer]) == 0
    assert f"answering message {question['id']}" in capsys.readouterr().out
    assert conversation.awaiting(conn) == []
    ticket = db.get_ticket(conn, KEY)
    assert ticket is not None
    section = conversation.operator_section(conn, ticket)
    assert section is not None
    messages = section["new_operator_messages"]
    assert isinstance(messages, list)
    [message] = messages
    assert message["body"] == answer
    assert conversation.pr_section(conn, ticket) == {"repo": "repo", "number": 7, "awaiting_reply": None}

    # The next resume carries the reply: the PR worker hears the operator only in its prompt.
    worker_does(monkeypatch, result=result())
    code, recorded = dispatch(
        conn,
        monkeypatch,
        *LABEL,
        "--kind",
        "resume",
        "--branch",
        pr_branch,
        "--cursor",
        f"message={message['id']}",
        runner=runner,
    )
    assert code == 0, recorded
    resumed = run_it(conn, runner)
    prompt = prompt_of(canopy_env, int(resumed["id"]))
    assert answer in prompt
    assert QUESTION in prompt
    ticket = db.get_ticket(conn, KEY)
    assert ticket is not None
    assert conversation.operator_section(conn, ticket) is None


def test_the_overseers_commands_take_a_prs_key(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick_id = in_tick(conn, monkeypatch)
    assert (
        main(["ticket", "set", KEY, "--phase", "ci_red", "--cursor", "ci=9", "--cursor", "review=2026-10-08T10:00:00Z"])
        == 0
    )
    assert main(["decide", KEY, "wait", "--rationale", "checks running"]) == 0
    assert main(["attention", KEY, "needs_author", "--detail", "a design question"]) == 0
    assert main(["ticket", "set", KEY, "--repo", "other", "--phase", "ci_red"]) == 1
    unit = unit_of(conn, KEY)
    assert (unit["repo"], unit["phase"], unit["last_ci_run_id"]) == ("repo", "ci_red", "9")
    assert [(a, d["ticket_key"]) for a, d in [(str(d["action"]), d) for d in db.decisions_for_tick(conn, tick_id)]] == [
        ("wait", KEY),
        ("attention:needs_author", KEY),
    ]
    # Starting, stopping, forgetting, and mirroring a PR are not built yet (ROADMAP M14).
    monkeypatch.delenv("CANOPY_TICK_ID")
    for verb in (["start", KEY], ["stop", KEY], ["forget", KEY]):
        assert main(verb) == 1


def test_a_dry_run_plans_a_pr_dispatch_and_leases_nothing(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick_id = in_tick(conn, monkeypatch, dry_run=True)
    assert main(["dispatch", KEY, *LABEL, "--kind", "fix-ci", "--branch", BRANCH]) == 0
    [(action, rationale)] = decisions(conn, tick_id)
    assert action == "dispatch:fix-ci"
    assert rationale.startswith(f"dry run: not dispatched; would work on {BRANCH}")
    assert not treehouse_state.exists()  # treehouse was never asked for a slot
    assert branch_of(conn) is None


def test_the_web_ui_reads_and_answers_a_pr_subject(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    db.touch_ticket(conn, KEY, str(canopy_env.repo))
    question = db.insert_message(conn, conversation.PR, KEY, source="worker", kind="question", channel="run", body="?")
    ctx = context(canopy_env)
    c, headers = signed_in_client(ctx)
    [listed] = [t for t in c.get("/api/tickets").json() if t["key"] == KEY]
    assert listed["awaiting"] == question
    detail = c.get("/api/tickets/repo%237").json()
    assert [m["id"] for m in detail["messages"]] == [question]
    replied = c.post("/api/tickets/repo%237/replies", json={"body": "go", "submission": "form-0001"}, headers=headers)
    assert replied.json()["answers"] == question
    assert c.post("/api/tickets/repo%237/start", headers=headers).status_code == 409
