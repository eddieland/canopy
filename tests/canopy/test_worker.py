"""`canopy _run`: branch setup, the worker, result parsing, push verification, slot return (DESIGN §8).

Runs are dispatched with an `InlineRunner`, which spawns nothing, and then run in-process with `main(["_run", ...])`.
"""

import json
import os
import signal
import sqlite3
import threading
from pathlib import Path

import pytest

from canopy import db, worker
from canopy.cli import main
from tests.canopy.helpers import InlineRunner, commit_and_push, in_tick, journal, pool, worker_does
from tests.conftest import CanopyEnv, GitPool, git


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


def dispatch_and_run(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    runner: InlineRunner | None = None,
    slug: str = "work",
) -> sqlite3.Row:
    runner = runner or InlineRunner()
    tick_id = in_tick(conn, monkeypatch)
    assert main(["dispatch", "PROJ-1", "--kind", "implement", "--slug", slug], runner=runner) == 0
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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    worker_does(monkeypatch, *commit_and_push("agent/PROJ-1-work"))
    run = dispatch_and_run(conn, monkeypatch)

    assert run["status"] == "done"
    assert run["ended_at"] is not None
    assert json.loads(run["result_json"]) == {
        "status": "done",
        "branch": "agent/PROJ-1-work",
        "pr": "https://example.test/pr/1",
        "summary": "did it",
        "question": None,
    }
    [w] = agent_runs(agent_log)
    assert w["cwd"] == run["slot_path"]
    assert w["env"] == {}  # no CANOPY_TICK_ID: a worker cannot act as the overseer
    argv = w["argv"]
    assert isinstance(argv, list)
    assert argv[:3] == ["run", "--agent", "canopy-worker"]
    assert argv[3] == (canopy_env.state_dir / "runs" / "1.prompt").read_text()

    slot = Path(run["slot_path"])
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=slot) == "agent/PROJ-1-work"
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)
    # The branch started from origin/main, without tracking it: a bare `git push` must not target main.
    assert git("rev-parse", "HEAD~1", cwd=slot) == git_pool.remote_head("main")
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    ticket = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert ticket["pr_url"] == "https://example.test/pr/1"
    assert "run 1: done" in capsys.readouterr().out


def test_new_branch_does_not_track_the_base(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_does(monkeypatch, ["git", "config", "--get", "branch.agent/PROJ-1-work.merge"])
    dispatch_and_run(conn, monkeypatch)
    [w] = agent_runs(agent_log)
    commands = w["commands"]
    assert isinstance(commands, list)
    assert commands[0]["returncode"] == 1  # no upstream configured


def test_unpushed_commits_are_pushed_once(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_does(monkeypatch, ["git", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: forgot to push"])
    run = dispatch_and_run(conn, monkeypatch)
    assert run["status"] == "done"
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=Path(run["slot_path"]))


def test_failed_push_is_unpushed(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git_pool.reject_pushes()
    worker_does(monkeypatch, *commit_and_push("agent/PROJ-1-work"))
    run = dispatch_and_run(conn, monkeypatch)
    assert run["status"] == "unpushed"
    result = json.loads(run["result_json"])
    assert result["status"] == "done"  # what the worker claimed is kept
    assert "not on origin; the push failed: " in result["harness"]
    assert "push refused by test hook" in result["harness"]
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_no_commits_is_not_unpushed(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = json.dumps({"status": "blocked", "summary": "unclear", "question": "which API?"})
    worker_does(monkeypatch, result=blocked)
    run = dispatch_and_run(conn, monkeypatch)
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
    monkeypatch: pytest.MonkeyPatch,
    last_line: str,
    exit_code: str,
) -> None:
    worker_does(monkeypatch, result=last_line)
    monkeypatch.setenv("FAKE_WORKER_EXIT", exit_code)
    run = dispatch_and_run(conn, monkeypatch)
    assert run["status"] == "unknown"
    assert json.loads(run["result_json"]) == {"harness": "the worker's last line was not a valid result"}


def test_result_text_is_bounded(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_does(monkeypatch, result=json.dumps({"status": "failed", "summary": "x" * 10000, "extra": "ignored"}))
    run = dispatch_and_run(conn, monkeypatch)
    result = json.loads(run["result_json"])
    assert run["status"] == "failed"
    assert len(result["summary"]) == 2000
    assert "extra" not in result


def test_timeout(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = dispatch_and_run(conn, monkeypatch, InlineRunner(timeout_agent=True))
    assert run["status"] == "timeout"
    assert json.loads(run["result_json"]) == {"harness": "the worker timed out after 45 minutes"}
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_existing_branch_on_origin_is_continued(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = git_pool.slots[1]
    git("checkout", "--quiet", "-b", "agent/PROJ-1-work", "origin/main", cwd=seed)
    git("commit", "--quiet", "--allow-empty", "-m", "earlier work", cwd=seed)
    git("push", "--quiet", "origin", "agent/PROJ-1-work", cwd=seed)
    git("checkout", "--quiet", "--detach", cwd=seed)

    worker_does(monkeypatch, ["git", "log", "-1", "--format=%s"])
    dispatch_and_run(conn, monkeypatch)
    [w] = agent_runs(agent_log)
    commands = w["commands"]
    assert isinstance(commands, list)
    assert commands[0]["stdout"] == "earlier work\n"


def test_git_failure_is_crashed_and_returns_the_slot(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for slot in git_pool.slots:
        git("remote", "set-url", "origin", str(git_pool.origin.parent / "gone.git"), cwd=slot)
    run = dispatch_and_run(conn, monkeypatch)
    assert run["status"] == "crashed"
    assert json.loads(run["result_json"])["harness"].startswith("git fetch exited 128")
    assert not agent_log.exists()  # the worker never ran
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_a_run_is_claimed_once(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = dispatch_and_run(conn, monkeypatch)
    assert main(["_run", str(run["id"])]) == 1
    assert "is not waiting to start" in capsys.readouterr().err
    assert main(["_run", "99"]) == 1
    assert "no run 99" in capsys.readouterr().err

    # A running run that another process claimed is refused too: the overseer cannot start a second worker in a slot.
    tick_id = in_tick(conn, monkeypatch)
    assert main(["dispatch", "PROJ-2", "--kind", "implement"], runner=InlineRunner()) == 0
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_does(monkeypatch)
    monkeypatch.setenv("FAKE_WORKER_SLEEP", "30")
    # Signal this process once the worker has started; `_run` turns SIGTERM into cleanup.
    timer = threading.Timer(1.5, os.kill, (os.getpid(), signal.SIGTERM))
    timer.start()
    try:
        run = dispatch_and_run(conn, monkeypatch)
    finally:
        timer.cancel()
    assert run["status"] == "crashed"
    assert json.loads(run["result_json"]) == {"harness": "stopped by signal SIGTERM"}
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


def test_parse_result_takes_the_last_non_empty_line() -> None:
    parsed = worker.parse_result('chatter\n{"status": "done"}\n\n  \n')
    assert parsed is not None
    assert parsed.status == "done"
    assert worker.parse_result('{"status": "done"}\nmore chatter\n') is None
