"""`canopy dispatch` outside a dry run: guards, lease, and spawning `_run` (DESIGN §8)."""

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from canopy import db, procs
from canopy.cli import main
from tests.canopy.helpers import InlineRunner, commit_and_push, in_tick, journal, pool, wait_for_run, worker_does
from tests.conftest import CanopyEnv, GitPool


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str, str]]:
    return [(str(d["action"]), str(d["rationale"])) for d in db.decisions_for_tick(conn, tick_id)]


def test_dispatch_leases_records_and_spawns(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tick_id = in_tick(conn, monkeypatch)
    runner = InlineRunner()
    assert main(["dispatch", "PROJ-1", "--kind", "implement", "--slug", "add-login"], runner=runner) == 0

    run = db.get_run(conn, 1)
    assert run is not None
    assert (run["ticket_key"], run["kind"], run["status"]) == ("PROJ-1", "implement", "running")
    assert run["branch"] == "agent/PROJ-1-add-login"
    assert run["base_branch"] == "main"
    assert run["lease_holder"] == "canopy:PROJ-1"
    assert run["pid"] == os.getpid()
    assert run["log_path"] == str(canopy_env.state_dir / "runs" / "1.log")
    [slot] = [s for s in pool(treehouse_state) if s["status"] == "leased"]
    assert (slot["path"], slot["lease_id"]) == (run["slot_path"], run["lease_id"])

    assert runner.spawned == [(sys.executable, "-m", "canopy", "_run", "1")]
    [(action, rationale)] = decisions(conn, tick_id)
    assert action == "dispatch:implement"
    assert rationale == f"run 1: agent/PROJ-1-add-login in {run['slot_path']}"
    ticket = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert ticket["branch"] == "agent/PROJ-1-add-login"

    prompt = canopy_env.state_dir / "runs" / "1.prompt"
    assert prompt.stat().st_mode & 0o777 == 0o600
    text = prompt.read_text()
    assert text.startswith("# canopy worker: implement")
    assert "{{" not in text
    assert "ticket PROJ-1 in an isolated worktree at " + str(run["slot_path"]) in text
    assert "`agent/PROJ-1-add-login` is checked out, based on `main`" in text
    assert "the label `agent`" in text
    assert "Time limit: 45 minutes" in text


def test_detached_run_finishes_on_its_own(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_does(monkeypatch, *commit_and_push("agent/PROJ-1-work"))
    in_tick(conn, monkeypatch)
    assert main(["dispatch", "PROJ-1", "--kind", "implement"]) == 0
    run = wait_for_run(conn, 1)
    assert run["status"] == "done", Path(run["log_path"]).read_text()
    assert git_pool.remote_head("agent/PROJ-1-work") is not None
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    log = Path(run["log_path"])
    assert log.stat().st_mode & 0o777 == 0o600
    assert "--- worker stdout ---" in log.read_text()


def test_capacity_guard(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[capacity]\nmax_workers = 1\n")
    tick_id = in_tick(conn, monkeypatch)
    runner = InlineRunner()
    assert main(["dispatch", "PROJ-1", "--kind", "implement"], runner=runner) == 0
    assert main(["dispatch", "PROJ-2", "--kind", "implement"], runner=runner) == 1
    assert "dispatch refused (capacity): 1 of 1 workers are running" in capsys.readouterr().err
    assert decisions(conn, tick_id)[1] == ("refused:capacity", "1 of 1 workers are running")
    assert sum(s["status"] == "leased" for s in pool(treehouse_state)) == 1
    assert len(runner.spawned) == 1


def test_one_worker_per_ticket(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick_id = in_tick(conn, monkeypatch)
    runner = InlineRunner()
    assert main(["dispatch", "PROJ-1", "--kind", "implement"], runner=runner) == 0
    assert main(["dispatch", "PROJ-1", "--kind", "implement", "--slug", "again"], runner=runner) == 1
    assert decisions(conn, tick_id)[1] == ("refused:running", "run 1 is already working PROJ-1")


def test_base_is_refused_until_stacking(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick_id = in_tick(conn, monkeypatch)
    assert main(["dispatch", "PROJ-1", "--kind", "implement", "--base", "agent/PROJ-0-x"], runner=InlineRunner()) == 1
    assert decisions(conn, tick_id) == [("refused:not_implemented", "--base arrives with stacking (ROADMAP M4)")]
    assert not treehouse_state.exists()  # treehouse was never called


@pytest.mark.parametrize("slug", ["Add", "a_b", "-a", "a-", "a--b", "a" * 41, "a/b", "a\n"])
def test_bad_slugs_are_usage_errors(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, slug: str
) -> None:
    in_tick(conn, monkeypatch)
    assert main(["dispatch", "PROJ-1", "--kind", "implement", "--slug", slug], runner=InlineRunner()) == 2


def test_no_slot(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    treehouse_state.write_text(json.dumps({"max_trees": 0}))
    tick_id = in_tick(conn, monkeypatch)
    assert main(["dispatch", "PROJ-1", "--kind", "implement"], runner=InlineRunner()) == 1
    [(action, rationale)] = decisions(conn, tick_id)
    assert action == "refused:no_slot"
    assert "max_trees" in rationale
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_bad_prompt_override_returns_the_slot(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} on {{BRNACH}}\n")
    tick_id = in_tick(conn, monkeypatch)
    assert main(["dispatch", "PROJ-1", "--kind", "implement"], runner=InlineRunner()) == 1
    [(action, rationale)] = decisions(conn, tick_id)
    assert action == "refused:bad_prompt"
    assert "unknown placeholder {{BRNACH}}" in rationale
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_spawn_failure_returns_the_slot_and_closes_the_run(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tick_id = in_tick(conn, monkeypatch)
    runner = InlineRunner(spawn_error=procs.ProcError("no processes left"))
    assert main(["dispatch", "PROJ-1", "--kind", "implement"], runner=runner) == 1
    assert decisions(conn, tick_id) == [("refused:spawn_failed", "no processes left")]
    run = db.get_run(conn, 1)
    assert run is not None
    assert run["status"] == "crashed"
    assert json.loads(run["result_json"]) == {"harness": "could not start the worker: no processes left"}
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_dry_run_still_starts_nothing(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    in_tick(conn, monkeypatch, dry_run=True)
    runner = InlineRunner()
    assert main(["dispatch", "PROJ-1", "--kind", "implement"], runner=runner) == 0
    assert runner.spawned == []
    assert not treehouse_state.exists()
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_dry_run_refuses_what_a_live_dispatch_would(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = in_tick(conn, monkeypatch)

    def past_run(key: str, kind: str, status: str) -> None:
        db.touch_ticket(conn, key, str(canopy_env.repo))
        run_id = db.insert_run(
            conn,
            tick_id=earlier,
            key=key,
            kind=kind,
            slot_path=Path("/pool/1"),
            lease_id=f"lease-{key}",
            lease_holder=f"canopy:{key}",
            base_branch="main",
            branch=f"agent/{key}-work",
            runs_dir=canopy_env.state_dir / "runs",
        )
        if status == "running":
            assert db.claim_run(conn, run_id, os.getpid())
        else:
            assert db.finish_run(conn, run_id, status, None)

    past_run("LIMIT", "fix-ci", "done")
    past_run("LIMIT", "fix-ci", "done")
    past_run("COOL", "fix-ci", "done")  # just ended, so fix-ci is in its cooldown
    past_run("BUSY", "implement", "running")
    tick_id = in_tick(conn, monkeypatch, dry_run=True)
    runner = InlineRunner()
    for args, code in [
        (["LIMIT", "--kind", "fix-ci"], 1),
        (["COOL", "--kind", "fix-ci"], 1),
        (["BUSY", "--kind", "resume"], 1),
        (["NEW", "--kind", "fix-ci"], 1),
        (["NEW", "--kind", "implement", "--base", "agent/X-1-work"], 1),
        (["NEW", "--kind", "implement"], 0),  # BUSY and this one fill max_workers = 2
        (["NEW", "--kind", "implement"], 1),
        (["OTHER", "--kind", "implement"], 1),
    ]:
        assert main(["dispatch", *args], runner=runner) == code, args

    assert [(d["ticket_key"], d["action"]) for d in db.decisions_for_tick(conn, tick_id)] == [
        ("LIMIT", "refused:attempt_limit"),
        ("LIMIT", "attention:attempt_limit"),
        ("COOL", "refused:cooldown"),
        ("BUSY", "refused:running"),
        ("NEW", "refused:no_branch"),
        ("NEW", "refused:not_implemented"),
        ("NEW", "dispatch:implement"),
        ("NEW", "refused:running"),
        ("OTHER", "refused:capacity"),
    ]
    assert decisions(conn, tick_id)[-1][1] == "2 of 2 workers are running, counting 1 this dry run dispatched"
    assert runner.spawned == []
    assert not treehouse_state.exists()
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 4
