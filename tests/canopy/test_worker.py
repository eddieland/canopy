"""`canopy _run`: branch setup, the worker, result parsing, push verification, slot return (DESIGN §8).

Runs are dispatched with an `InlineRunner`, which spawns nothing, and then run in-process with `main(["_run", ...])`.
"""

import json
import os
import re
import signal
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, db, definitions
from canopy.core.vocab import RunStatus
from canopy.runs import worker
from tests.canopy.helpers import (
    InlineRunner,
    commit_and_push,
    in_tick,
    journal,
    pool,
    slot_of,
    unit_of,
    worker_does,
)
from tests.conftest import CanopyEnv, GitPool, git


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


def dispatch_and_run(
    conn: sqlite3.Connection,
    runner: InlineRunner | None = None,
    slug: str = "work",
    title: str | None = None,
) -> sqlite3.Row:
    runner = runner or InlineRunner()
    with in_tick(conn) as tick_id:
        if title is not None:
            assert main(["ticket", "set", "PROJ-1", "--title", title]) == 0
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
                    "--slug",
                    slug,
                ],
                runner=runner,
            )
            == 0
        )
        db.finish_tick(conn, tick_id, "ok", "test")
        run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
        assert main(["_run", str(run_id)], runner=runner) == 0
        row = db.get_run(conn, run_id)
        assert row is not None
        return row


def agent_runs(agent_log: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in agent_log.read_text().splitlines()]


def test_worker_that_pushes_is_done(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        run = dispatch_and_run(conn)

    assert run["status"] == "done"
    assert run["ended_at"] is not None
    assert json.loads(run["result_json"]) == {
        "status": "done",
        "branch": "agent/PROJ-1-work",
        "pr": "https://example.test/pr/1",
        "prs": {"repo": "https://example.test/pr/1"},  # a result from before joint runs is read as the new contract
        "summary": "did it",
        "question": None,
    }
    [w] = agent_runs(agent_log)
    assert w["cwd"] == slot_of(conn, run["id"])["slot_path"]
    # No CANOPY_TICK_ID: a worker cannot act as the overseer.
    # CANOPY_RUN_ID: the operator's commands refuse inside the run (DESIGN §22).
    snapshot = definitions.ensure(canopy_env.state_dir, config.load(canopy_env.root))
    # CANOPY_GIT_OBJECTS: the run's object directory, for a sandbox wrapper (DESIGN §8).
    objects = canopy_env.state_dir / "runs" / f"{run['id']}.objects"
    assert w["env"] == {
        "CANOPY_RUN_ID": str(run["id"]),
        "CANOPY_GIT_OBJECTS": str(objects),
        "OPENCODE_CONFIG_DIR": str(snapshot),
    }
    assert not objects.exists()  # removed once the run was over
    argv = w["argv"]
    assert isinstance(argv, list)
    assert argv[:3] == ["run", "--agent", "canopy-worker"]
    assert argv[3] == (canopy_env.state_dir / "runs" / "1.prompt").read_text()

    slot = Path(slot_of(conn, run["id"])["slot_path"])
    # Detached: the worker pushed HEAD to the branch, which started from origin/main.
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=slot) == "HEAD"
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)
    assert git("rev-parse", "HEAD~1", cwd=slot) == git_pool.remote_head("main")
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert unit_of(conn, "PROJ-1")["pr_url"] == "https://example.test/pr/1"
    assert "run 1: done" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("title", "session_title"),
    [(None, "PROJ-1 implement"), ("Fix the\nlogin loop\x1b[2J", "PROJ-1 implement: Fix the login loop [2J")],
)
def test_the_session_title_names_the_ticket_and_its_title(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
    title: str | None,
    session_title: str,
) -> None:
    """`{title}` is the run's session title, so the runtime's session list names the ticket (DESIGN §13)."""
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-worker --title={title} {prompt}"
    canopy_env.write_user(
        re.sub(r"^worker_cmd = .*$", f"worker_cmd = '{template}'", canopy_env.user_file.read_text(), flags=re.MULTILINE)
    )
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        dispatch_and_run(conn, title=title)
    [w] = agent_runs(agent_log)
    argv = w["argv"]
    assert isinstance(argv, list)
    assert argv[3] == f"--title={session_title}"


def test_a_run_makes_no_local_branch(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    """A pool's slots share its branch refs, so a worker starts detached, and a bare push has nowhere to go."""
    with worker_does(
        ["git", "symbolic-ref", "--quiet", "HEAD"],
        ["git", "for-each-ref", "--format=%(refname)", "refs/heads/agent/"],
        ["git", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: work"],
        ["git", "push", "--quiet", "origin"],
    ):
        run = dispatch_and_run(conn)
    [w] = agent_runs(agent_log)
    commands = w["commands"]
    assert isinstance(commands, list)
    assert commands[0]["returncode"] == 1  # detached
    assert commands[1]["stdout"] == ""
    assert commands[3]["returncode"] != 0  # not on a branch: nothing a bare push could target, the base included
    assert git_pool.remote_head("main") == git("rev-parse", "HEAD~1", cwd=Path(slot_of(conn, run["id"])["slot_path"]))


def test_unpushed_commits_are_pushed_once(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(["git", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: forgot to push"]):
        run = dispatch_and_run(conn)
    assert run["status"] == "done"
    assert git_pool.remote_head("agent/PROJ-1-work") == git(
        "rev-parse", "HEAD", cwd=Path(slot_of(conn, run["id"])["slot_path"])
    )


def test_commits_the_worker_moved_head_off_are_unpushed(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    """Detached, HEAD alone holds the worker's commits: checking out something else leaves them behind."""
    with worker_does(
        ["git", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: left behind"],
        ["git", "checkout", "--quiet", "--detach", "origin/main"],
    ):
        run = dispatch_and_run(conn)
    assert run["status"] == "unpushed"
    assert "the worker moved HEAD off 1 commit(s) not on origin" in json.loads(run["result_json"])["harness"]
    assert git_pool.remote_head("agent/PROJ-1-work") is None


def test_a_worker_that_pushed_and_then_moved_head_is_done(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(
        *commit_and_push("agent/PROJ-1-work"),
        ["git", "checkout", "--quiet", "--detach", "origin/main"],
    ):
        run = dispatch_and_run(conn)
    assert run["status"] == "done"
    assert git_pool.remote_head("agent/PROJ-1-work") != git_pool.remote_head("main")


def branch_behind_main(git_pool: GitPool, branch: str = "agent/PROJ-1-work") -> None:
    """Put `branch` on origin with two commits of its own, and then a commit on `main` it lacks."""
    seed = git_pool.slots[1]
    git("checkout", "--quiet", "-b", branch, "origin/main", cwd=seed)
    for name in ("a", "b"):
        (seed / f"{name}.txt").write_text(f"{name}\n")
        git("add", f"{name}.txt", cwd=seed)
        git("commit", "--quiet", "-m", f"PROJ-1: {name}", cwd=seed)
    git("push", "--quiet", "origin", branch, cwd=seed)
    git("checkout", "--quiet", "--detach", "origin/main", cwd=seed)
    (seed / "m.txt").write_text("m\n")
    git("add", "m.txt", cwd=seed)
    git("commit", "--quiet", "-m", "main moves on", cwd=seed)
    git("push", "--quiet", "origin", "HEAD:refs/heads/main", cwd=seed)
    git("checkout", "--quiet", "--detach", cwd=seed)


def commit_file(name: str) -> list[str]:
    return ["sh", "-c", f"echo {name} > {name}.txt && git add {name}.txt && git commit --quiet -m 'PROJ-1: {name}'"]


def with_rebase(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[trust]\nrebase = true\n")


def test_a_rebase_dropped_for_the_same_work_pushed_another_way_is_done(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    """Issue #293: the worker rebased, could not force-push, and pushed a fix on top of origin's branch instead."""
    branch_behind_main(git_pool)
    with worker_does(
        ["git", "rebase", "--quiet", "origin/main"],
        ["git", "checkout", "--quiet", "--detach", "origin/agent/PROJ-1-work"],
        commit_file("fix"),
        ["git", "push", "--quiet", "origin", "HEAD:refs/heads/agent/PROJ-1-work"],
    ):
        run = dispatch_and_run(conn)
    assert run["status"] == "done", run["result_json"]
    slot = Path(slot_of(conn, run["id"])["slot_path"])
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)


def test_a_rebase_dropped_with_work_of_its_own_is_unpushed(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    """Only a commit whose change origin already has is dropped from the check: new work left behind still counts."""
    branch_behind_main(git_pool)
    with worker_does(
        ["git", "rebase", "--quiet", "origin/main"],
        commit_file("lost"),
        ["git", "checkout", "--quiet", "--detach", "origin/agent/PROJ-1-work"],
        commit_file("fix"),
        ["git", "push", "--quiet", "origin", "HEAD:refs/heads/agent/PROJ-1-work"],
    ):
        run = dispatch_and_run(conn)
    assert run["status"] == "unpushed"
    assert "the worker moved HEAD off 1 commit(s) not on origin" in json.loads(run["result_json"])["harness"]


def test_without_rebase_a_rebased_branch_is_never_forced(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    branch_behind_main(git_pool)
    before = git_pool.remote_head("agent/PROJ-1-work")
    with worker_does(["git", "rebase", "--quiet", "origin/main"]):
        run = dispatch_and_run(conn)
    assert run["status"] == "unpushed"
    assert "not on origin; the push failed: " in json.loads(run["result_json"])["harness"]
    assert git_pool.remote_head("agent/PROJ-1-work") == before


def test_with_rebase_a_worker_that_rebased_and_pushed_with_a_lease_is_done(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    """Its own commit, made before the rebase, and origin's old commits are replaced by copies: nothing is lost."""
    with_rebase(canopy_env)
    branch_behind_main(git_pool)
    with worker_does(
        commit_file("fix"),
        ["git", "rebase", "--quiet", "origin/main"],
        ["git", "push", "--quiet", "--force-with-lease", "origin", "HEAD:refs/heads/agent/PROJ-1-work"],
    ):
        run = dispatch_and_run(conn)
    assert run["status"] == "done", run["result_json"]
    slot = Path(slot_of(conn, run["id"])["slot_path"])
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)
    assert git("merge-base", "--is-ancestor", "origin/main", "HEAD", cwd=slot) == ""


def test_with_rebase_canopy_pushes_a_rebased_branch_with_a_lease(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with_rebase(canopy_env)
    branch_behind_main(git_pool)
    with worker_does(["git", "rebase", "--quiet", "origin/main"]):
        run = dispatch_and_run(conn)
    assert run["status"] == "done", run["result_json"]
    slot = Path(slot_of(conn, run["id"])["slot_path"])
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)


def test_with_rebase_canopy_never_overwrites_a_push_made_since_the_run_started(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with_rebase(canopy_env)
    branch_behind_main(git_pool)
    other = git_pool.slots[1]
    script = (
        f"git -C {other} fetch --quiet origin && git -C {other} checkout --quiet --detach origin/agent/PROJ-1-work && "
        f"git -C {other} commit --quiet --allow-empty -m 'a coworker' && "
        f"git -C {other} push --quiet origin HEAD:refs/heads/agent/PROJ-1-work"
    )
    pushed_meanwhile = ["sh", "-c", script]
    with worker_does(pushed_meanwhile, ["git", "rebase", "--quiet", "origin/main"]):
        run = dispatch_and_run(conn)
    assert run["status"] == "unpushed"
    assert "not on origin; the push failed: " in json.loads(run["result_json"])["harness"]
    assert git("log", "-1", "--format=%s", git_pool.remote_head("agent/PROJ-1-work") or "", cwd=other) == "a coworker"


@pytest.mark.parametrize("only_here", [False, True])
def test_a_local_branch_an_earlier_canopy_left_is_dropped_unless_it_holds_commits_origin_lacks(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
    only_here: bool,  # noqa: FBT001  (a parameter of the test)
) -> None:
    """Before D109 a run made its branch locally with `checkout -B`, and the pool's repository still has it."""
    for slot in git_pool.slots:
        git("branch", "agent/PROJ-1-work", "origin/main", cwd=slot)
        if only_here:
            stray = git("commit-tree", "-m", "only here", "-p", "origin/main", "origin/main^{tree}", cwd=slot)
            git("branch", "--force", "agent/PROJ-1-work", stray, cwd=slot)
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        run = dispatch_and_run(conn)
    assert run["status"] == "done"
    slot = Path(slot_of(conn, run["id"])["slot_path"])
    left = git("for-each-ref", "--format=%(refname)", "refs/heads/agent/PROJ-1-work", cwd=slot)
    assert left == ("refs/heads/agent/PROJ-1-work" if only_here else "")


def test_failed_push_is_unpushed(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    git_pool.reject_pushes()
    with worker_does(*commit_and_push("agent/PROJ-1-work")):
        run = dispatch_and_run(conn)
    assert run["status"] == "unpushed"
    result = json.loads(run["result_json"])
    assert result["status"] == "done"  # what the worker claimed is kept
    assert "not on origin; the push failed: " in result["harness"]
    assert "push refused by test hook" in result["harness"]
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_no_commits_is_not_unpushed(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    blocked = json.dumps({"status": "blocked", "summary": "unclear", "question": "which API?"})
    with worker_does(result=blocked):
        run = dispatch_and_run(conn)
    assert run["status"] == "blocked"
    assert json.loads(run["result_json"])["question"] == "which API?"
    assert git_pool.remote_head("agent/PROJ-1-work") is None


@pytest.mark.parametrize(
    ("last_line", "exit_code"),
    [("not json", "0"), ("", "0"), ('{"status": "finished"}', "0"), ('{"summary": "no status"}', "1")],
)
def test_bad_result_line_is_unknown(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
    last_line: str,
    exit_code: str,
) -> None:
    with worker_does(result=last_line), mock.patch.dict(os.environ, {"FAKE_WORKER_EXIT": exit_code}):
        run = dispatch_and_run(conn)
    assert run["status"] == "unknown"
    assert json.loads(run["result_json"]) == {"harness": "the worker's last line was not a valid result"}


def test_result_text_is_bounded(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    with worker_does(result=json.dumps({"status": "failed", "summary": "x" * 10000, "extra": "ignored"})):
        run = dispatch_and_run(conn)
    result = json.loads(run["result_json"])
    assert run["status"] == "failed"
    assert len(result["summary"]) == 2000
    assert "extra" not in result


def test_timeout(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    run = dispatch_and_run(conn, InlineRunner(timeout_agent=True))
    assert run["status"] == "timeout"
    assert json.loads(run["result_json"]) == {"harness": "the worker timed out after 45 minutes"}
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_existing_branch_on_origin_is_continued(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    seed = git_pool.slots[1]
    git("checkout", "--quiet", "-b", "agent/PROJ-1-work", "origin/main", cwd=seed)
    git("commit", "--quiet", "--allow-empty", "-m", "earlier work", cwd=seed)
    git("push", "--quiet", "origin", "agent/PROJ-1-work", cwd=seed)
    git("checkout", "--quiet", "--detach", cwd=seed)

    with worker_does(["git", "log", "-1", "--format=%s"]):
        dispatch_and_run(conn)
    [w] = agent_runs(agent_log)
    commands = w["commands"]
    assert isinstance(commands, list)
    assert commands[0]["stdout"] == "earlier work\n"


def test_worker_refuses_to_start_on_a_branch_that_defines_its_agent(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    # Anyone who can push to the repository could commit this (TRUST_MODEL T7).
    clone = tmp_path / "pusher"
    git("clone", "--quiet", str(git_pool.origin), str(clone), cwd=tmp_path)
    agent = clone / ".opencode" / "agent" / "canopy-worker.md"
    agent.parent.mkdir(parents=True)
    agent.write_text('---\npermission:\n  bash:\n    "*": allow\n    "canopy *": allow\n---\n')
    git("add", ".", cwd=clone)
    git("commit", "--quiet", "-m", "loosen the worker", cwd=clone)
    git("push", "--quiet", "origin", "main", cwd=clone)

    run = dispatch_and_run(conn)
    assert run["status"] == "crashed"
    assert "defines one of canopy's agents" in json.loads(run["result_json"])["harness"]
    assert not agent_log.exists()
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_git_failure_is_crashed_and_returns_the_slot(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    for slot in git_pool.slots:
        git("remote", "set-url", "origin", str(git_pool.origin.parent / "gone.git"), cwd=slot)
    run = dispatch_and_run(conn)
    assert run["status"] == "crashed"
    assert json.loads(run["result_json"])["harness"].startswith("repo: git fetch exited 128")
    assert not agent_log.exists()  # the worker never ran
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_a_run_is_claimed_once(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = dispatch_and_run(conn)
    assert main(["_run", str(run["id"])]) == 1
    assert "is not waiting to start" in capsys.readouterr().err
    assert main(["_run", "99"]) == 1
    assert "no run 99" in capsys.readouterr().err

    # A running run that another process claimed is refused too: the overseer cannot start a second worker in a slot.
    with in_tick(conn) as tick_id:
        assert (
            main(
                ["dispatch", "PROJ-2", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=InlineRunner(),
            )
            == 0
        )
        db.finish_tick(conn, tick_id, "ok", "test")
        conn.execute("UPDATE runs SET pid = 1 WHERE id = 2")
        assert main(["_run", "2"]) == 1
        still = db.get_run(conn, 2)
        assert still is not None
        assert still["status"] == "running"
        assert len(agent_runs(agent_log)) == 1


def test_sigterm_returns_the_slot(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    with worker_does(), mock.patch.dict(os.environ, {"FAKE_WORKER_SLEEP": "30"}):
        # Signal this process once the worker has started; `_run` turns SIGTERM into cleanup.
        timer = threading.Timer(1.5, os.kill, (os.getpid(), signal.SIGTERM))
        timer.start()
        try:
            run = dispatch_and_run(conn)
        finally:
            timer.cancel()
    assert run["status"] == "crashed"
    assert json.loads(run["result_json"]) == {"harness": "stopped by signal SIGTERM"}
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


def test_parse_result_takes_the_last_json_object_line() -> None:
    parsed = worker.parse_result('chatter\n{"status": "done"}\n\n  \n')
    assert parsed is not None
    assert parsed.status == "done"
    # A plugin's notice after the result is passed over (DESIGN §13).
    parsed = worker.parse_result('{"status": "done"}\n[policy-plugin] session audited\n')
    assert parsed is not None
    assert parsed.status == "done"
    # An invalid last object is no result, even with a valid one before it.
    assert worker.parse_result('{"status": "done"}\n{"status": "finished"}\nchatter\n') is None
    assert worker.parse_result("chatter only\n") is None


@contextmanager
def report_events(canopy_env: CanopyEnv) -> Iterator[None]:
    """Have the worker's template ask for OpenCode's JSON events, as the default does, with session `ses_w1`."""
    text = canopy_env.user_file.read_text().replace("--agent canopy-worker", "--agent canopy-worker --format json")
    canopy_env.write_user(text)
    with mock.patch.dict(os.environ, {"FAKE_WORKER_SESSION": "ses_w1"}):
        yield


def test_a_worker_records_the_session_and_cost_it_reported(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with report_events(canopy_env), worker_does(*commit_and_push("agent/PROJ-1-work")):
        run = dispatch_and_run(conn)

    # The result line is read from the events' text, as it is from stdout without them.
    assert run["status"] == "done"
    assert json.loads(run["result_json"])["summary"] == "did it"
    assert unit_of(conn, "PROJ-1")["pr_url"] == "https://example.test/pr/1"
    # Two model calls, summed.
    assert run["session_id"] == "ses_w1"
    assert run["cost_usd"] == 0.25
    tokens = ("tokens_input", "tokens_output", "tokens_reasoning", "tokens_cache_read", "tokens_cache_write")
    assert tuple(run[c] for c in tokens) == (2000, 400, 60, 8000, 1000)
    assert run["tokens_peak_context"] == 1000 + 4000 + 500  # one call's input, cache read, and cache write
    assert (run["tokens_first_call"], run["tokens_first_cache_write"]) == (5500, 500)
    assert (canopy_env.state_dir / definitions.RUNTIME_DIR / run["definitions_digest"]).is_dir()  # the one it loaded

    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"\nRecent runs \(1\):\n  PROJ-1  implement  done  \d+s ago  https://example.test/pr/1\n", out)
    assert f"\n    did it\n    session ses_w1  $0.25, 3.5k tokens, 5.5k peak context  log {run['log_path']}\n" in out


def test_a_timed_out_worker_records_what_it_reported_before_the_kill(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    tokens = {"input": 1, "output": 2, "reasoning": 0, "cache": {"read": 3, "write": 4}}
    events = [
        {"type": "step_finish", "sessionID": "ses_slow", "part": {"cost": 0.5, "tokens": tokens}},
        {"type": "text", "sessionID": "ses_slow", "part": {"type": "text", "text": "still going"}},
    ]
    stdout = "".join(json.dumps(e) + "\n" for e in events)
    with report_events(canopy_env):
        run = dispatch_and_run(conn, InlineRunner(timeout_agent=True, timeout_stdout=stdout))
    assert run["status"] == "timeout"
    assert (run["session_id"], run["cost_usd"], run["tokens_cache_write"]) == ("ses_slow", 0.5, 4)


def test_a_worker_without_events_reports_no_session(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = "\x1b[2Jcleared the screen\nand  went on   " + "x" * 300
    with worker_does(result=json.dumps({"status": "failed", "summary": summary, "pr": "https://x.test/\x1b"})):
        run = dispatch_and_run(conn)
    assert (run["status"], run["session_id"], run["cost_usd"]) == ("failed", None, None)

    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    # Agent-written text reaches the terminal on one line, without control characters, and cut; a PR that is not a
    # plain URL is not printed at all.
    assert re.search(r"\n  PROJ-1  implement  failed  \d+s ago\n", out)
    assert "\x1b" not in out
    [said] = [line for line in out.splitlines() if line.startswith("    [2J")]
    assert said == "    [2Jcleared the screen and went on " + "x" * 123 + "..."
    assert len(said) == 4 + 160
    assert f"\n    no session reported  log {run['log_path']}\n" in out


def test_status_lists_recent_runs_newest_first(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status"]) == 0
    assert "\nRecent runs (0):\n  none\n" in capsys.readouterr().out
    tick_id = db.start_tick(conn, dry_run=False)
    db.touch_ticket(conn, "PROJ-1", str(canopy_env.root))
    for n in range(12):
        run_id = db.insert_run(
            conn, tick_id=tick_id, key="PROJ-1", kind="fix-ci", branch="b", slots=[], runs_dir=Path()
        )
        db.finish_run(conn, "runs", run_id, RunStatus.DONE, json.dumps({"summary": f"run {n + 1}"}))
    running = db.insert_run(conn, tick_id=tick_id, key="PROJ-1", kind="resume", branch="b", slots=[], runs_dir=Path())

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    recent = out[out.index("Recent runs") :]
    assert re.match(r"Recent runs \(10\):\n  PROJ-1  fix-ci  done  \d+s ago\n    run 12\n", recent)
    assert "run 3\n" in recent
    assert "run 2\n" not in recent
    assert db.get_run(conn, running) is not None
    assert "resume" not in recent
