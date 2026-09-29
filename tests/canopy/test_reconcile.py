"""Reconcile (DESIGN §6 step 3), harness attention items for runs (DESIGN §14), and live ticks end to end."""

import json
import os
import signal
import sqlite3
import time
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db, definitions
from canopy.infra import procs
from canopy.loop import attention
from tests.canopy.helpers import commit_and_push, in_tick, journal, pool, wait_for_run, worker_does
from tests.conftest import CanopyEnv, GitPool

# Above Linux's largest pid_max, so never a live process.
DEAD_PID = 4_194_305


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


def overseer_does(monkeypatch: pytest.MonkeyPatch, *commands: list[str]) -> None:
    monkeypatch.setenv("FAKE_OVERSEER_COMMANDS", json.dumps([["canopy", *c] for c in commands]))
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")


def lease(treehouse_state: Path, key: str) -> dict[str, str]:
    result = procs.SubprocessRunner().run(["treehouse", "get", "--lease", "--lease-holder", f"canopy:{key}", "--json"])
    assert result.ok, result.stderr
    leased: dict[str, str] = json.loads(result.stdout)
    return leased


def add_run(
    conn: sqlite3.Connection, key: str, leased: dict[str, str], *, pid: int | None, status: str = "running"
) -> int:
    tick_id = db.start_tick(conn, dry_run=False)
    db.finish_tick(conn, tick_id, "ok", "test")
    db.touch_ticket(conn, key, "repo")
    run_id = db.insert_run(
        conn,
        tick_id=tick_id,
        key=key,
        kind="implement",
        slot_path=Path(leased["path"]),
        lease_id=leased["lease_id"],
        lease_holder=leased["lease_holder"],
        base_branch="main",
        branch=f"agent/{key}-work",
        runs_dir=Path("/state/runs"),
    )
    if pid is not None:
        db.claim_run(conn, run_id, pid)
    if status != "running":
        db.finish_run(conn, run_id, status, json.dumps({"summary": "gave up"}))
    return run_id


def last_tick_decisions(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    tick = db.last_tick(conn)
    assert tick is not None
    return [(d["ticket_key"], d["action"], d["rationale"]) for d in db.decisions_for_tick(conn, int(tick["id"]))]


def test_dead_worker_is_crashed_and_its_slot_returned(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overseer_does(monkeypatch)
    dead = add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=DEAD_PID)
    never_started = add_run(conn, "PROJ-2", lease(treehouse_state, "PROJ-2"), pid=None)
    live = add_run(conn, "PROJ-3", lease(treehouse_state, "PROJ-3"), pid=os.getpid())

    assert main(["tick"]) == 0
    for run_id in (dead, never_started):
        run = db.get_run(conn, run_id)
        assert run is not None
        assert run["status"] == "crashed"
        assert json.loads(run["result_json"]) == {"harness": "the worker process is gone"}
    still = db.get_run(conn, live)
    assert still is not None
    assert still["status"] == "running"
    assert [s["status"] for s in pool(treehouse_state)] == ["available", "available", "leased"]

    items = [(k, a) for k, a, _ in last_tick_decisions(conn)]
    assert items == [("PROJ-1", "attention:crashed"), ("PROJ-2", "attention:crashed")]
    [prompt] = [r["argv"][-1] for r in map(json.loads, agent_log.read_text().splitlines())]
    assert '"running": 1' in prompt
    assert '"available": 1' in prompt
    assert '"status": "crashed"' in prompt  # the ticket's last run, for the overseer


def test_old_definitions_snapshots_are_removed_only_when_no_run_is_live(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overseer_does(monkeypatch)
    old = canopy_env.state_dir / "runtime" / "0123456789abcdef"
    old.mkdir(parents=True)
    live = add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=os.getpid())

    # A live run may be one of an earlier canopy, still loading the old snapshot.
    assert main(["tick", "--dry-run"]) == 0
    assert old.is_dir()

    db.finish_run(conn, live, "done", "{}")
    assert main(["tick", "--dry-run"]) == 0
    assert not old.exists()
    assert definitions.ensure(canopy_env.state_dir).is_dir()


def test_stale_canopy_lease_is_returned_and_others_are_not(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overseer_does(monkeypatch)
    slots = [
        {"name": "1", "path": "/pool/1/repo", "status": "leased", "lease_id": "a", "lease_holder": "canopy:P-1"},
        {"name": "2", "path": "/pool/2/repo", "status": "leased", "lease_id": "b", "lease_holder": "someone-else"},
    ]
    treehouse_state.write_text(json.dumps({"slots": slots}))
    assert main(["tick", "--dry-run"]) == 0
    assert [s["status"] for s in pool(treehouse_state)] == ["available", "leased"]
    log = (canopy_env.state_dir / "canopy.log").read_text()
    assert "canopy lease with no running worker; returned" in log


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("crashed", "crashed"),
        ("unpushed", "unpushed"),
        ("unknown", "unknown_result"),
        ("timeout", "unknown_result"),
        ("failed", "worker_failed"),
        ("done", None),
        ("blocked", None),
    ],
)
def test_attention_from_the_latest_run(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, status: str, reason: str | None
) -> None:
    run_id = add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=DEAD_PID, status=status)
    items = attention.from_runs(conn)
    if reason is None:
        assert items == []
        return
    [item] = items
    assert (item.ticket_key, item.reason) == ("PROJ-1", reason)
    assert item.detail == f"run {run_id} (implement, agent/PROJ-1-work) ended {status}: gave up; log /state/runs/1.log"


def test_attention_clears_with_a_newer_run_or_when_done(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=DEAD_PID, status="crashed")
    add_run(conn, "PROJ-2", lease(treehouse_state, "PROJ-2"), pid=DEAD_PID, status="crashed")
    assert [i.ticket_key for i in attention.from_runs(conn)] == ["PROJ-1", "PROJ-2"]
    add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=os.getpid())
    db.set_ticket(conn, "PROJ-2", "repo", done=True)
    assert attention.from_runs(conn) == []


def test_treehouse_return_failure_stops_the_tick(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=DEAD_PID)
    broken = tmp_path / "bin"
    broken.mkdir()
    (broken / "treehouse").write_text('#!/bin/sh\n[ "$1" = status ] && echo "[]" && exit 0\necho boom >&2; exit 2\n')
    (broken / "treehouse").chmod(0o755)
    monkeypatch.setenv("PATH", f"{broken}{os.pathsep}{os.environ['PATH']}")
    assert main(["tick"]) == 1
    tick = db.last_tick(conn)
    assert tick is not None
    assert tick["status"] == "reconcile_failed"
    assert "boom" in tick["summary"]
    assert not agent_log.exists()


def test_live_tick_takes_a_ticket_to_a_pushed_branch(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """M2 acceptance, against the fakes: label to pushed branch, slot returned, a correct `runs` row."""
    overseer_does(
        monkeypatch,
        ["dispatch", "PROJ-1", "--label", "agent-ready-tester", "--kind", "implement", "--slug", "add-login"],
    )
    worker_does(monkeypatch, *commit_and_push("agent/PROJ-1-add-login"))
    assert main(["tick"]) == 0
    assert capsys.readouterr().out.startswith("tick 1: ok: 1 decisions: dispatch:implement=1")

    run = wait_for_run(conn, 1)
    assert run["status"] == "done", Path(run["log_path"]).read_text()
    assert (run["tick_id"], run["ticket_key"], run["kind"]) == (1, "PROJ-1", "implement")
    assert run["branch"] == "agent/PROJ-1-add-login"
    assert run["pid"] is not None
    assert run["ended_at"] is not None
    assert json.loads(run["result_json"])["pr"] == "https://example.test/pr/1"
    assert git_pool.remote_head("agent/PROJ-1-add-login") is not None
    assert all(s["status"] == "available" for s in pool(treehouse_state))

    # The next tick sees nothing running and nothing to return, and tells the overseer how the run ended.
    overseer_does(monkeypatch)
    assert main(["tick"]) == 0
    calls = json.loads(treehouse_state.read_text())["calls"]
    assert [c[0] for c in calls] == ["status", "get", "return", "status"]
    prompt = json.loads(agent_log.read_text().splitlines()[-1])["argv"][-1]
    assert '"last_run": {\n        "run_id": 1,' in prompt
    assert '"status": "done"' in prompt


def test_killed_worker_is_detected_on_the_next_tick(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M2 acceptance, against the fakes: a killed worker is found by the next tick and its slot returned."""
    worker_does(monkeypatch)
    monkeypatch.setenv("FAKE_WORKER_SLEEP", "60")
    tick_id = in_tick(conn, monkeypatch)
    assert main(["dispatch", "PROJ-1", "--label", "agent-ready-tester", "--kind", "implement"]) == 0
    db.finish_tick(conn, tick_id, "ok", "test")
    monkeypatch.delenv("CANOPY_TICK_ID")

    # Wait for both, in either order. `_run` records the worker's pid only after starting it, so the agent log can come
    # first. The log is written after the fake's stdout chatter: killing `_run` before then would break the worker's
    # pipe and kill it too.
    deadline = time.monotonic() + 30
    run = db.get_run(conn, 1)
    while (run is None or run["worker_pid"] is None or not agent_log.exists()) and time.monotonic() < deadline:
        time.sleep(0.05)
        run = db.get_run(conn, 1)
    assert agent_log.exists(), "the worker never started"
    assert run is not None
    assert run["worker_pid"] is not None, "`_run` never recorded the worker's pid"
    pid, worker_pid = int(run["pid"]), int(run["worker_pid"])
    # `kill -9` of `_run` alone: the worker leads its own process group and is left running, orphaned.
    os.kill(pid, signal.SIGKILL)
    while procs.alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not procs.alive(pid)
    assert procs.alive(worker_pid)
    assert pool(treehouse_state)[0]["status"] == "leased"

    overseer_does(monkeypatch)
    assert main(["tick"]) == 0
    crashed = db.get_run(conn, 1)
    assert crashed is not None
    assert crashed["status"] == "crashed"
    while procs.alive(worker_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not procs.alive(worker_pid)  # stopped before its slot went back to the pool
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert [(k, a) for k, a, _ in last_tick_decisions(conn)] == [("PROJ-1", "attention:crashed")]
    assert [(i.ticket_key, i.reason) for i in attention.current(conn)] == [("PROJ-1", "crashed")]
