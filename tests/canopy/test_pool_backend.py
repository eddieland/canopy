"""Choosing the pool (DESIGN §18; ROADMAP M45, stage 3): `pools.backend`, leases going back to the pool that made them,
and `canopy workspace sync` carrying the slots over when the operator switches."""

import json
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, db, pool, pools, workspace
from canopy.core.context import Context
from canopy.core.vocab import PoolKind, RunStatus
from canopy.infra import logs, procs, resources
from canopy.runs import reconcile
from tests.canopy.conftest import Ws, seed_pools
from tests.canopy.helpers import InlineRunner, commit_and_push, in_tick, running_run, worker_does
from tests.canopy.helpers import context as loop_context
from tests.canopy.web_helpers import signed_in_client
from tests.conftest import CanopyEnv, git, user_toml

LABEL = "agent-ready-tester"
BRANCH = "agent/PROJ-1-work"


def use(canopy_env: CanopyEnv, backend: str) -> None:
    """Name `backend` in the operator's user file."""
    canopy_env.write_user(user_toml() + f'\n[pools]\nbackend = "{backend}"\n')


def implement(repo: str) -> list[str]:
    return ["dispatch", "PROJ-1", "--label", LABEL, "--kind", "implement", "--repo", repo]


def context(ws: Ws, canopy_env: CanopyEnv, conn: sqlite3.Connection) -> Context:
    cfg = config.load(ws.root, canopy_env.user_file)
    return Context(config=cfg, conn=conn, runner=procs.SubprocessRunner(), ws=workspace.load(ws.root))


def fake_pool(treehouse_state: Path, ws: Ws, name: str) -> list[dict[str, object]]:
    found: list[dict[str, object]] = json.loads(treehouse_state.read_text())["pools"][str(ws.clone(name))]["slots"]
    return found


def canopy_rows(conn: sqlite3.Connection) -> list[tuple[str, str, str | None]]:
    return [(r["repo"], r["path"], r["lease_holder"]) for r in conn.execute("SELECT * FROM slots ORDER BY repo, name")]


# The setting


def test_the_backend_is_user_only_and_treehouse_by_default(ws: Ws, canopy_env: CanopyEnv) -> None:
    assert config.load(ws.root, canopy_env.user_file).pools.backend is PoolKind.TREEHOUSE
    use(canopy_env, "canopy")
    assert config.load(ws.root, canopy_env.user_file).pools.backend is PoolKind.CANOPY
    use(canopy_env, "worktrees")
    with pytest.raises(config.ConfigError, match="backend"):
        config.load(ws.root, canopy_env.user_file)
    use(canopy_env, "treehouse")
    shared = ws.root / config.WORKSPACE_FILE_NAME
    shared.write_text(shared.read_text() + '\n[pools]\nbackend = "canopy"\n')
    with pytest.raises(config.ConfigError, match="user-only"):
        config.load(ws.root, canopy_env.user_file)


# Where a lease comes from and goes back to


def test_under_canopy_a_run_leases_from_canopy_s_pool_and_its_slot_goes_back_there(
    ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    use(canopy_env, "canopy")
    conn = ws.journal()
    runner = InlineRunner()
    with worker_does(*commit_and_push(BRANCH)), in_tick(conn) as tick_id:
        assert main(implement("api"), runner=runner) == 0
        db.finish_tick(conn, tick_id, "ok", "test")
        [slot] = db.run_slots(conn, 1)
        assert slot["pool"] == PoolKind.CANOPY
        assert Path(slot["slot_path"]) == ws.root / pool.POOLS_DIR / "api" / "1" / "api"
        assert canopy_rows(conn) == [("api", slot["slot_path"], "canopy:PROJ-1")]
        assert main(["_run", "1"], runner=runner) == 0
    run = db.get_run(conn, 1)
    assert run is not None
    assert run["status"] == RunStatus.DONE
    assert canopy_rows(conn) == [("api", slot["slot_path"], None)]
    assert ws.remote_head("api", BRANCH) is not None
    # treehouse was never asked.
    assert not treehouse_state.exists()


def test_a_lease_goes_back_to_the_pool_that_made_it_after_a_switch(
    ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    runner = InlineRunner()
    with worker_does(*commit_and_push(BRANCH)), in_tick(conn) as tick_id:
        assert main(implement("api"), runner=runner) == 0
        db.finish_tick(conn, tick_id, "ok", "test")
        [slot] = db.run_slots(conn, 1)
        assert slot["pool"] == PoolKind.TREEHOUSE
        # The operator switches while the run is in flight.
        use(canopy_env, "canopy")
        assert main(["_run", "1"], runner=runner) == 0
    assert [s["status"] for s in fake_pool(treehouse_state, ws, "api")] == ["available"]
    assert canopy_rows(conn) == []


def test_under_canopy_reconcile_still_returns_a_stale_treehouse_lease(
    ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path
) -> None:
    seed_pools(ws, treehouse_state)
    runner = procs.SubprocessRunner()
    held = runner.run(
        ["treehouse", "get", "--lease", "--lease-holder", "canopy:PROJ-9", "--json"],
        cwd=ws.clone("api"),
        env={"TREEHOUSE_ROOT": str(ws.root)},
    )
    assert held.ok, held.stderr
    use(canopy_env, "canopy")
    conn = ws.journal()
    log = mock.create_autospec(logs.TickAdapter, instance=True)
    with in_tick(conn):
        reconciled = reconcile.run(context(ws, canopy_env, conn), log)
    assert [s["status"] for s in fake_pool(treehouse_state, ws, "api")] == ["available"]
    assert reconciled.leased == {"api": [], "web": []}


def test_under_canopy_reconcile_returns_a_stale_canopy_lease_and_runs_no_shadow(ws: Ws, canopy_env: CanopyEnv) -> None:
    use(canopy_env, "canopy")
    conn = ws.journal()
    ctx = context(ws, canopy_env, conn)
    lease = ctx.pool("api").lease("PROJ-9")
    log = mock.create_autospec(logs.TickAdapter, instance=True)
    with in_tick(conn):
        reconcile.run(ctx, log)
    assert canopy_rows(conn) == [("api", str(lease.path), None)]
    messages = [c.args[0] for c in log.warning.call_args_list]
    assert "canopy lease with no running worker; returned" in messages
    assert "pool_shadow_mismatch" not in messages


# Switching, with `canopy workspace sync`


def treehouse_worktree(ws: Ws, treehouse_state: Path, name: str) -> Path:
    """Give repository `name` a treehouse slot that is a real worktree of its clone, with an ignored build cache."""
    clone = ws.clone(name)
    (clone / ".git" / "info" / "exclude").write_text("*.local\n")
    slot = ws.root / workspace.POOLS_DIR / f"{name}-fake" / "1" / name
    slot.parent.mkdir(parents=True)
    git("worktree", "add", "--quiet", "--detach", str(slot), cwd=clone)
    (slot / "cache.local").write_text("warm\n")
    state = {"pools": {str(clone): {"slots": [{"name": "1", "path": str(slot), "status": "available"}]}}}
    treehouse_state.write_text(json.dumps(state))
    return slot


def test_switching_to_canopy_moves_idle_treehouse_slots_with_their_caches(
    ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = treehouse_worktree(ws, treehouse_state, "api")
    use(canopy_env, "canopy")
    assert main(["workspace", "sync", "--dry-run"]) == 0
    assert "api: to move: 1 idle treehouse slots into pools/\n" in capsys.readouterr().out
    assert old.is_dir()

    assert main(["workspace", "sync"]) == 0
    assert "api: moved: moved 1 of 1 idle treehouse slots into pools/\n" in capsys.readouterr().out
    moved = ws.root / pool.POOLS_DIR / "api" / "1" / "api"
    assert not old.exists()
    assert (moved / "cache.local").read_text() == "warm\n"
    conn = ws.journal()
    assert canopy_rows(conn) == [("api", str(moved), None)]
    # canopy's pool reuses it, and the cache with it.
    lease = context(ws, canopy_env, conn).pool("api").lease("PROJ-1")
    assert lease.path == moved
    assert (moved / "cache.local").read_text() == "warm\n"


def test_switching_back_removes_canopy_s_idle_slots(
    ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = ws.journal()
    use(canopy_env, "canopy")
    ours = context(ws, canopy_env, conn).pool("api")
    lease = ours.lease("PROJ-1")
    ours.return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    use(canopy_env, "treehouse")
    assert main(["workspace", "sync"]) == 0
    assert "api: removed: removed 1 of 1 idle slots of canopy's pool\n" in capsys.readouterr().out
    assert not lease.path.exists()
    assert canopy_rows(conn) == []


# The worktrees page


def test_the_worktrees_page_shows_canopy_s_pool_under_canopy(canopy_env: CanopyEnv) -> None:
    use(canopy_env, "canopy")
    ctx = loop_context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    run_id = running_run(ctx, "PROJ-1")
    path = canopy_env.root / pool.POOLS_DIR / "repo" / "1" / "repo"
    ctx.conn.execute(
        "INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder, base_branch, pool) "
        "VALUES (?, 'repo', ?, 'lease-run', 'canopy:PROJ-1', 'main', 'canopy')",
        (run_id, str(path)),
    )
    ctx.conn.execute(
        "INSERT INTO slots (repo, name, path, lease_id, lease_holder, leased_at) "
        "VALUES ('repo', '1', ?, 'lease-run', 'canopy:PROJ-1', '2026-10-16T00:00:00+00:00')",
        (str(path),),
    )
    c, _ = signed_in_client(ctx)
    [found] = c.get("/api/worktrees").json()
    assert found["error"] is None
    [one] = found["worktrees"]
    assert (one["name"], one["status"], one["state"], one["run"]["id"]) == ("1", "leased", "working", run_id)
    assert one["path"] == "pools/repo/1/repo"


def test_a_treehouse_slot_that_cannot_move_stays_and_sync_says_why(
    ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = treehouse_worktree(ws, treehouse_state, "api")
    (old / "scratch.txt").write_text("not committed\n")
    use(canopy_env, "canopy")
    assert main(["workspace", "sync"]) == 1
    out = capsys.readouterr().out
    assert "api: kept: moved 0 of 1 idle treehouse slots into pools/; slot 1 stays in treehouse's pool: " in out
    assert "has changes" in out
    assert (old / "scratch.txt").exists()
    assert not (ws.root / pool.POOLS_DIR / "api" / "1").exists()


def test_switching_back_keeps_a_canopy_slot_with_work_in_it(
    ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = ws.journal()
    use(canopy_env, "canopy")
    ours = context(ws, canopy_env, conn).pool("api")
    lease = ours.lease("PROJ-1")
    ours.return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    git("commit", "--quiet", "--allow-empty", "-m", "committed in an idle slot", cwd=lease.path)
    use(canopy_env, "treehouse")
    assert main(["workspace", "sync"]) == 1
    out = capsys.readouterr().out
    assert "api: kept: removed 0 of 1 idle slots of canopy's pool; slot 1 kept: HEAD is not merged into " in out
    assert lease.path.is_dir()


def test_under_treehouse_a_canopy_pool_that_cannot_be_read_is_logged_not_fatal(
    ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path
) -> None:
    seed_pools(ws, treehouse_state)
    (ws.root / pool.POOLS_DIR / "api").mkdir(parents=True)
    conn = ws.journal()
    log = mock.create_autospec(logs.TickAdapter, instance=True)
    broken = pools.PoolError("the journal says something odd")
    with in_tick(conn), mock.patch.object(pool.CanopyPool, "status", autospec=True, side_effect=broken):
        reconciled = reconcile.run(context(ws, canopy_env, conn), log)
    assert set(reconciled.leased) == {"api", "web"}
    warnings = [(c.args[0], c.kwargs["extra"]) for c in log.warning.call_args_list]
    assert ("canopy pool not read", {"repo": "api", "error": "the journal says something odd"}) in warnings
