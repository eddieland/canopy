"""Reconcile (DESIGN §6 step 3), harness attention items for runs (DESIGN §14), and live ticks end to end."""

import json
import os
import signal
import sqlite3
import time
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, db, definitions
from canopy.core.vocab import RunStatus, StartStatus, TickStatus
from canopy.infra import lock, procs
from canopy.loop import attention
from tests.canopy.helpers import (
    DEAD_PID,
    agent_runs,
    canopy,
    commit_and_push,
    in_tick,
    last_tick,
    overseer_does,
    pool,
    present,
    tick_starts,
    tracker_holds,
    wait_for_run,
    waits,
    worker_does,
)
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.conftest import CanopyEnv, GitPool, executable, pool_state


def lease(treehouse_state: Path, key: str) -> dict[str, str]:
    result = procs.SubprocessRunner().run(["treehouse", "get", "--lease", "--lease-holder", f"canopy:{key}", "--json"])
    assert result.ok, result.stderr
    leased: dict[str, str] = json.loads(result.stdout)
    return leased


def add_run(
    conn: sqlite3.Connection,
    key: str,
    leased: Mapping[str, str],
    *,
    pid: int | None,
    status: str = "running",
) -> int:
    tick_id = db.start_tick(conn, dry_run=False)
    db.finish_tick(conn, tick_id, TickStatus.OK, "test")
    db.touch_ticket(conn, key, "repo")
    run_id = db.insert_run(
        conn,
        tick_id=tick_id,
        key=key,
        kind="implement",
        branch=f"agent/{key}-work",
        slots=[
            db.RunSlot(
                repo="repo",
                slot_path=Path(leased["path"]),
                lease_id=leased["lease_id"],
                lease_holder=leased["lease_holder"],
                base_branch="main",
            ),
        ],
        runs_dir=Path("/state/runs"),
    )
    if pid is not None:
        db.claim_run(conn, "runs", run_id, pid)
    if status != "running":
        db.finish_run(conn, "runs", run_id, RunStatus(status), json.dumps({"summary": "gave up"}))
    return run_id


def last_tick_decisions(conn: sqlite3.Connection) -> list[tuple[str | None, str, str]]:
    tick = last_tick(conn)
    return [(d.ticket_key, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick.id)]


def test_a_run_whose_process_died_is_crashed_its_worker_killed_and_its_slot_returned(
    scenario: Scenario,
    treehouse_state: Path,
    git_pool: GitPool,
) -> None:
    dies = scenario.starts(worker=pushes())
    lives = scenario.starts(dispatches("PROJ-2"), worker=pushes())
    left_behind = int(dies.row["worker_pid"])
    dies.dies()
    assert procs.alive(left_behind)  # the worker leads its own group, so it outlives the run's process

    # The harness waits on PROJ-2 for the worker still running it (DESIGN §37); the overseer, on PROJ-1.
    ticked = scenario.tick(*waits("PROJ-1"))
    assert ticked.actions == ["attention:crashed", "wait", "queried", "wait"]
    crashed = dies.row
    assert crashed["status"] == "crashed"
    assert json.loads(crashed["result_json"]) == {"harness": "the worker process is gone"}
    deadline = time.monotonic() + 30
    while procs.alive(left_behind) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not procs.alive(left_behind)
    assert git_pool.remote_head("agent/PROJ-1-work") is None  # killed before it pushed
    assert [s["status"] for s in pool(treehouse_state)] == ["available", "leased"]
    assert scenario.state()["capacity"]["running"] == 1
    assert scenario.ticket_state("PROJ-1")["last_run"]["status"] == "crashed"  # for the overseer
    assert scenario.attention() == [("PROJ-1", "crashed")]

    assert lives.finishes().status == "done"  # a run that lives is left to end as it would have
    assert git_pool.remote_head("agent/PROJ-2-work") is not None


def test_a_run_never_claimed_is_crashed_and_its_slot_returned(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
) -> None:
    with overseer_does(*waits("PROJ-1")):
        never_started = add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=None)
        assert main(["tick"]) == 0
    run = present(db.get_run(conn, never_started))
    assert run["status"] == "crashed"
    assert json.loads(run["result_json"]) == {"harness": "the worker process is gone"}
    assert [s["status"] for s in pool(treehouse_state)] == ["available"]
    assert last_tick_decisions(conn)[0][:2] == ("PROJ-1", "attention:crashed")


def test_a_worker_is_alive_while_it_holds_its_lifelock_whatever_its_pid(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
) -> None:
    # The lock beside a run's log says whether its `_run` lives; the pid counts only for a run that has none.
    with overseer_does(*waits("PROJ-1", "PROJ-2")):
        holding = add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=DEAD_PID)
        let_go = add_run(conn, "PROJ-2", lease(treehouse_state, "PROJ-2"), pid=os.getpid())
        runs = canopy_env.state_dir / "runs"
        for run_id in (holding, let_go):
            conn.execute("UPDATE runs SET log_path = ? WHERE id = ?", (str(runs / f"{run_id}.log"), run_id))
        os.close(lock.take(procs.lifelock(runs / f"{let_go}.log")))
        held = lock.take(procs.lifelock(runs / f"{holding}.log"))
        try:
            assert main(["tick"]) == 0
        finally:
            os.close(held)
        statuses = {r: (run["status"] if (run := db.get_run(conn, r)) else None) for r in (holding, let_go)}
        assert statuses == {holding: "running", let_go: "crashed"}
        # The crashed run's lock file goes with its row; the running one's stays, as it says the run lives.
        assert not procs.lifelock(runs / f"{let_go}.log").exists()
        assert procs.lifelock(runs / f"{holding}.log").exists()


def test_old_definitions_snapshots_are_removed_only_when_no_run_is_live(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
) -> None:
    with overseer_does(*waits("PROJ-1")):
        old = canopy_env.state_dir / "runtime" / "0123456789abcdef"
        old.mkdir(parents=True)
        live = add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=os.getpid())

        # A live run may be one of an earlier canopy, still loading the old snapshot.
        assert main(["tick", "--dry-run"]) == 0
        assert old.is_dir()

        db.finish_run(conn, "runs", live, RunStatus.DONE, "{}")
        assert main(["tick", "--dry-run"]) == 0
        assert not old.exists()
        current = definitions.ensure(canopy_env.state_dir, config.load(canopy_env.root))
        assert [p.name for p in (canopy_env.state_dir / "runtime").iterdir()] == [current.name]


def test_stale_canopy_lease_is_returned_and_others_are_not(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
) -> None:
    with overseer_does():
        slots = [
            {"name": "1", "path": "/pool/1/repo", "status": "leased", "lease_id": "a", "lease_holder": "canopy:P-1"},
            {"name": "2", "path": "/pool/2/repo", "status": "leased", "lease_id": "b", "lease_holder": "someone-else"},
        ]
        treehouse_state.write_text(pool_state(canopy_env.repo, slots))
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
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    status: str,
    reason: str | None,
) -> None:
    run_id = add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=DEAD_PID, status=status)
    items = attention.from_runs(conn)
    if reason is None:
        assert items == []
        return
    [item] = items
    assert (item.ticket_key, item.reason) == ("PROJ-1", reason)
    assert item.detail == f"run:{run_id} (implement, agent/PROJ-1-work) ended {status}: gave up; log /state/runs/1.log"


def test_attention_clears_with_a_newer_run_or_when_done(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=DEAD_PID, status="crashed")
    add_run(conn, "PROJ-2", lease(treehouse_state, "PROJ-2"), pid=DEAD_PID, status="crashed")
    assert [i.ticket_key for i in attention.from_runs(conn)] == ["PROJ-1", "PROJ-2"]
    add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=os.getpid())
    db.set_ticket(conn, "PROJ-2", "repo", done=True)
    assert attention.from_runs(conn) == []


def test_a_stopped_ticket_raises_no_attention_until_started_again(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=DEAD_PID, status="crashed")
    with db.transaction(conn):
        db.set_start(conn, db.SUBJECT_TICKET, "PROJ-1", status=StartStatus.STARTED, channel="cli")
        db.set_start(conn, db.SUBJECT_TICKET, "PROJ-1", status=StartStatus.STOPPED, channel="cli")
    # Nothing dispatches a stopped ticket, so no reply could answer the item.
    assert attention.from_runs(conn) == []
    with db.transaction(conn):
        db.set_start(conn, db.SUBJECT_TICKET, "PROJ-1", status=StartStatus.STARTED, channel="cli")
    assert [(i.ticket_key, i.reason) for i in attention.from_runs(conn)] == [("PROJ-1", "crashed")]


def test_treehouse_return_failure_stops_the_tick(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    add_run(conn, "PROJ-1", lease(treehouse_state, "PROJ-1"), pid=DEAD_PID)
    broken = tmp_path / "bin"
    broken.mkdir()
    executable(broken / "treehouse", '#!/bin/sh\n[ "$1" = status ] && echo "[]" && exit 0\necho boom >&2; exit 2\n')
    with mock.patch.dict(os.environ, {"PATH": f"{broken}{os.pathsep}{os.environ['PATH']}"}):
        assert main(["tick"]) == 1
        tick = last_tick(conn)
        assert tick.status == TickStatus.RECONCILE_FAILED
        assert "boom" in str(tick.summary)
        assert not agent_log.exists()


def test_live_tick_takes_a_ticket_to_a_pushed_branch(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """M2 acceptance, against the fakes: label to pushed branch, slot returned, a correct `runs` row."""
    dispatch = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
    tracker_holds(conn)
    with (
        overseer_does(canopy(*dispatch, "--slug", "add-login")),
        worker_does(*commit_and_push("agent/PROJ-1-add-login")),
    ):
        assert main(["tick"]) == 0
    assert capsys.readouterr().out.startswith("tick 1: ok: 2 decisions: dispatch:implement=1, queried=1")

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
    with overseer_does(*waits("PROJ-1")):
        assert main(["tick"]) == 0
    calls = json.loads(treehouse_state.read_text())["calls"]
    assert [c[0] for c in calls] == ["status", "get", "return", "status"]
    prompt = agent_runs(agent_log)[-1]["argv"][-1]
    assert '"last_run":{"run_id":1,' in prompt
    assert '"status":"done"' in prompt


def test_killed_worker_is_detected_on_the_next_tick(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
) -> None:
    """M2 acceptance, against the fakes: a killed worker is found by the next tick and its slot returned."""
    tracker_holds(conn)
    with (
        worker_does(sleep=60),
        in_tick(conn, ends_ok=True),
    ):
        dispatch = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
        assert main(dispatch) == 0
        tick_starts()

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

    with overseer_does(*waits("PROJ-1")):
        assert main(["tick"]) == 0
    crashed = present(db.get_run(conn, 1))
    assert crashed["status"] == "crashed"
    while procs.alive(worker_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not procs.alive(worker_pid)  # stopped before its slot went back to the pool
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert [(k, a) for k, a, _ in last_tick_decisions(conn)] == [
        ("PROJ-1", "attention:crashed"),
        (None, "queried"),
        ("PROJ-1", "wait"),
    ]
    assert [(i.ticket_key, i.reason) for i in attention.current(conn)] == [("PROJ-1", "crashed")]
