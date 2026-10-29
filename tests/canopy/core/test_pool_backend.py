"""Choosing the pool (DESIGN §18; ROADMAP M45, stage 3): `pools.backend` and `canopy workspace sync`.

Leases go back to the pool that made them, and `canopy workspace sync` carries the slots over when the operator
switches.
"""

import dataclasses
import json
import shutil
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, db, pool, pools, workspace
from canopy.core.context import Context
from canopy.core.vocab import PoolKind, RunStatus, TickStatus
from canopy.infra import logs, procs, resources
from canopy.runs import reconcile
from tests.canopy.conftest import Ws, seed_pools
from tests.canopy.helpers import (
    BRANCH,
    LABEL,
    InlineRunner,
    commit_and_push,
    in_run,
    in_tick,
    present,
    running_run,
    tick_starts,
    tracker_holds,
    worker_does,
)
from tests.canopy.helpers import context as loop_context
from tests.canopy.web_helpers import signed_in_client
from tests.conftest import CanopyEnv, git, user_toml


def use(canopy_env: CanopyEnv, backend: str, *, slots: str = "") -> None:
    """Name `backend` in the operator's user file, and declare `slots`, lines of `[capacity.repo_slots]`, if any."""
    declared = f"\n[capacity.repo_slots]\n{slots}\n" if slots else ""
    canopy_env.write_user(user_toml() + f'\n[pools]\nbackend = "{backend}"\n' + declared)


def implement(repo: str) -> list[str]:
    return ["dispatch", "PROJ-1", "--label", LABEL, "--kind", "implement", "--repo", repo]


def context(ws: Ws, canopy_env: CanopyEnv, conn: sqlite3.Connection) -> Context:
    cfg = config.load(ws.root, canopy_env.user_file)
    return Context(config=cfg, conn=conn, runner=procs.SubprocessRunner(), ws=workspace.load(ws.root))


def fake_pool(treehouse_state: Path, ws: Ws, name: str) -> list[dict[str, object]]:
    found: list[dict[str, object]] = json.loads(treehouse_state.read_text())["pools"][str(ws.clone(name))]["slots"]
    return found


def calls(treehouse_state: Path, verb: str) -> list[list[str]]:
    """The fake treehouse's invocations of `verb`, each its argv."""
    made: list[list[str]] = json.loads(treehouse_state.read_text())["calls"]
    return [c for c in made if c[0] == verb]


def unmerged(treehouse_state: Path, paths: list[str]) -> None:
    """Have the fake treehouse's `destroy` keep the slots at `paths` as unmerged."""
    state = json.loads(treehouse_state.read_text())
    state["unmerged"] = paths
    treehouse_state.write_text(json.dumps(state))


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
    with pytest.raises(config.ConfigError, match="is private"):
        config.load(ws.root, canopy_env.user_file)


# Where a lease comes from and goes back to


def test_under_canopy_a_run_leases_from_canopy_s_pool_and_its_slot_goes_back_there(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    use(canopy_env, "canopy")
    conn = ws.journal()
    runner = InlineRunner()
    tracker_holds(conn)
    with worker_does(*commit_and_push(BRANCH)), in_tick(conn) as tick_id:
        assert main(implement("api"), runner=runner) == 0
        tick_starts(runner)
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        [slot] = db.run_slots(conn, 1)
        assert slot.pool == PoolKind.CANOPY
        assert Path(slot.slot_path) == ws.root / pool.POOLS_DIR / "api" / "1" / "api"
        assert canopy_rows(conn) == [("api", slot.slot_path, "canopy:PROJ-1")]
        assert main(["_run", "1"], runner=runner) == 0
    run = present(db.get_run(conn, 1))
    assert run["status"] == RunStatus.DONE
    assert canopy_rows(conn) == [("api", slot.slot_path, None)]
    assert ws.remote_head("api", BRANCH) is not None
    # treehouse was never asked.
    assert not treehouse_state.exists()


def test_a_lease_goes_back_to_the_pool_that_made_it_after_a_switch(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    runner = InlineRunner()
    tracker_holds(conn)
    with worker_does(*commit_and_push(BRANCH)), in_tick(conn) as tick_id:
        assert main(implement("api"), runner=runner) == 0
        tick_starts(runner)
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        [slot] = db.run_slots(conn, 1)
        assert slot.pool == PoolKind.TREEHOUSE
        # The operator switches while the run is in flight.
        use(canopy_env, "canopy")
        assert main(["_run", "1"], runner=runner) == 0
    assert [s["status"] for s in fake_pool(treehouse_state, ws, "api")] == ["available"]
    assert canopy_rows(conn) == []


def test_under_canopy_reconcile_still_returns_a_stale_treehouse_lease(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
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


def set_status(treehouse_state: Path, ws: Ws, name: str, status: str) -> None:
    """Set repository `name`'s one treehouse slot to `status`, leased to a run when `status` is `leased`."""
    state = json.loads(treehouse_state.read_text())
    [slot] = state["pools"][str(ws.clone(name))]["slots"]
    slot["status"] = status
    for key in ("lease_id", "lease_holder", "leased_at"):
        slot.pop(key, None)
    if status == "leased":
        slot |= {"lease_id": "id-1", "lease_holder": "canopy:PROJ-9", "leased_at": "2026-10-07T00:00:00Z"}
    treehouse_state.write_text(json.dumps(state))


def test_switching_to_canopy_moves_idle_treehouse_slots_with_their_caches(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
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
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
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
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
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


def test_a_treehouse_slot_busy_at_the_switch_moves_in_at_a_later_sync(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = treehouse_worktree(ws, treehouse_state, "api")
    set_status(treehouse_state, ws, "api", "leased")
    use(canopy_env, "canopy", slots="api = 2")
    waits = "1 left in treehouse's pool, moved in by a later sync"
    assert main(["workspace", "sync", "--dry-run"]) == 0
    assert f"api: slots: 0 of 2, would make 1; {waits}\n" in capsys.readouterr().out

    # Sync makes only the slot the move cannot supply, so the busy one still fits once it is idle.
    assert main(["workspace", "sync"]) == 0
    assert f"api: slots: 1 of 2, made 1; {waits}\n" in capsys.readouterr().out
    conn = ws.journal()
    assert len(canopy_rows(conn)) == 1
    assert old.is_dir()

    # The run ends and its lease goes back to treehouse; the next sync moves the slot, caches and all.
    set_status(treehouse_state, ws, "api", "available")
    assert main(["workspace", "sync"]) == 0
    out = capsys.readouterr().out
    assert "api: moved: moved 1 of 1 idle treehouse slots into pools/\n" in out
    assert "api: slots: 2 of 2\n" in out
    moved = ws.root / pool.POOLS_DIR / "api" / "2" / "api"
    assert not old.exists()
    assert (moved / "cache.local").read_text() == "warm\n"
    assert [path for _, path, _ in canopy_rows(conn)][1] == str(moved)


def test_an_idle_treehouse_slot_the_move_refuses_is_made_up_in_canopy_s_pool(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = treehouse_worktree(ws, treehouse_state, "api")
    (old / "scratch.txt").write_text("not committed\n")
    use(canopy_env, "canopy", slots="api = 2")
    # The move refuses it, and no later sync would move it either, so it does not hold a place in canopy's pool.
    assert main(["workspace", "sync"]) == 1
    out = capsys.readouterr().out
    assert "api: kept: moved 0 of 1 idle treehouse slots into pools/; slot 1 stays in treehouse's pool: " in out
    assert "api: slots: 2 of 2, made 2\n" in out
    assert "later sync" not in out
    assert len(canopy_rows(ws.journal())) == 2


def test_a_switch_s_dry_run_counts_the_slots_its_move_brings_in(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    treehouse_worktree(ws, treehouse_state, "api")
    use(canopy_env, "canopy", slots="api = 1")
    assert main(["workspace", "sync", "--dry-run"]) == 0
    dry = [line for line in capsys.readouterr().out.splitlines() if line.startswith("api: slots: ")]
    assert main(["workspace", "sync"]) == 0
    real = [line for line in capsys.readouterr().out.splitlines() if line.startswith("api: slots: ")]
    assert dry == real == ["api: slots: 1 of 1"]
    assert len(canopy_rows(ws.journal())) == 1


def test_switching_back_keeps_a_canopy_slot_with_work_in_it(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
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
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
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


# Releasing a quarantined slot, with `canopy workspace release`


def quarantined(ws: Ws, canopy_env: CanopyEnv, conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Leave api's one slot of canopy's pool quarantined: a lease's seeding collides with a file a run left there."""
    clone = ws.clone("api")
    (clone / ".git" / "info" / "exclude").write_text("*.local\n")
    ours = context(ws, canopy_env, conn).canopy_pool("api")
    lease = ours.lease("PROJ-1")
    (lease.path / "user.local").write_text("the run's own\n")
    ours.return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    (clone / "user.local").write_text("personal\n")
    manifest = tmp_path / "worktreeinclude"
    manifest.write_text("*.local\n")
    with pytest.raises(pools.PoolError, match="file exists"):
        dataclasses.replace(ours, include_file=manifest).lease("PROJ-2")
    return lease.path


def test_release_frees_a_quarantined_slot_of_canopy_s_pool(
    ws: Ws,
    canopy_env: CanopyEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use(canopy_env, "canopy")
    conn = ws.journal()
    path = quarantined(ws, canopy_env, conn, tmp_path)
    assert canopy_rows(conn) == [("api", str(path), pools.QUARANTINED)]
    assert main(["workspace", "release", "api", "1"]) == 0
    assert capsys.readouterr().out == f"api: released slot 1 ({path})\n"
    assert canopy_rows(conn) == [("api", str(path), None)]
    # The file seeding collided with is the operator's to remove: a release keeps ignored files, as a return does.
    assert (path / "user.local").read_text() == "the run's own\n"
    assert context(ws, canopy_env, conn).pool("api").lease("PROJ-3").path == path


def held_by_a_run(conn: sqlite3.Connection, lease: pools.Lease, key: str, *, pool_: PoolKind) -> int:
    """Record a running run of `key` that holds `lease`, as a dispatch records one, and return its id."""
    tick_id = db.start_tick(conn, dry_run=False)
    db.touch_ticket(conn, key, "repo")
    slot = db.RunSlot("api", lease.path, lease.lease_id, lease.lease_holder, "main", pool_)
    run_id = db.insert_run(
        conn,
        tick_id=tick_id,
        key=key,
        kind="implement",
        branch=f"agent/{key}-work",
        slots=[slot],
        runs_dir=conn_dir(conn) / "runs",
    )
    db.finish_tick(conn, tick_id, TickStatus.OK, "test")
    return run_id


def conn_dir(conn: sqlite3.Connection) -> Path:
    [(path,)] = conn.execute("SELECT file FROM pragma_database_list WHERE name = 'main'").fetchall()
    return Path(path).parent


def test_release_refuses_a_slot_something_running_holds_or_nothing_does(
    ws: Ws,
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use(canopy_env, "canopy")
    conn = ws.journal()
    ours = context(ws, canopy_env, conn).pool("api")
    lease = ours.lease("PROJ-1")
    run_id = held_by_a_run(conn, lease, "PROJ-1", pool_=PoolKind.CANOPY)
    assert main(["workspace", "release", "api", "1"]) == 1
    assert f"slot 1 is held by run:{run_id} of PROJ-1, still running" in capsys.readouterr().err
    assert canopy_rows(conn) == [("api", str(lease.path), "canopy:PROJ-1")]
    idle = ours.lease("PROJ-2")
    ours.return_slot(idle.path, lease_id=idle.lease_id, lease_holder=idle.lease_holder)
    assert main(["workspace", "release", "api", "2"]) == 1
    assert "slot 2 is available, and nothing holds it; nothing released" in capsys.readouterr().err
    assert main(["workspace", "release", "api", "3"]) == 1
    assert "api's pool has no slot 3" in capsys.readouterr().err
    assert main(["workspace", "release", "elsewhere", "1"]) == 1
    assert "the map lists no repository elsewhere" in capsys.readouterr().err


def test_release_returns_a_canopy_lease_no_running_run_holds(
    ws: Ws,
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use(canopy_env, "canopy")
    conn = ws.journal()
    # A lease whose run is no longer running, as reconcile finds one: it would return it at the next tick.
    lease = context(ws, canopy_env, conn).pool("api").lease("PROJ-9")
    (lease.path / "stray.txt").write_text("left behind\n")
    assert main(["workspace", "release", "api", str(lease.path)]) == 0
    assert capsys.readouterr().out == (
        f"api: returned slot 1 ({lease.path}), whose lease canopy:PROJ-9 no running run held\n"
    )
    assert canopy_rows(conn) == [("api", str(lease.path), None)]
    assert not (lease.path / "stray.txt").exists()


def test_release_refuses_inside_one_of_canopy_s_runs(ws: Ws, capsys: pytest.CaptureFixture[str]) -> None:
    for command in (["release", "api", "1"], ["remove-slot", "api", "1"]):
        with in_run(7):
            assert main(["workspace", *command]) == 1
        assert f"{command[0]} refused (inside_run)" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("holder", "said"),
    [
        (pools.SYNC_HOLDER, "a sync that did not finish; `canopy workspace sync` returns it"),
        ("someone", "is held by someone, which is not canopy's"),
    ],
)
def test_release_leaves_a_lease_that_is_not_a_run_s(
    ws: Ws,
    treehouse_state: Path,
    holder: str,
    said: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    slot = ws.root / ".treehouse" / "api-fake" / "1" / "api"
    held = {"name": "1", "path": str(slot), "status": "leased", "lease_id": "id-1", "lease_holder": holder}
    treehouse_state.write_text(json.dumps({"pools": {str(ws.clone("api")): {"slots": [held]}}}))
    assert main(["workspace", "release", "api", "1"]) == 1
    assert said in capsys.readouterr().err
    assert not calls(treehouse_state, "return")


def test_under_treehouse_release_returns_a_stale_lease_through_treehouse(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    slot = ws.root / ".treehouse" / "api-fake" / "1" / "api"
    slot.mkdir(parents=True)
    held = {"name": "1", "path": str(slot), "status": "leased", "lease_id": "id-1", "lease_holder": "canopy:PROJ-9"}
    treehouse_state.write_text(json.dumps({"pools": {str(ws.clone("api")): {"slots": [held]}}}))
    assert main(["workspace", "release", "api", "1"]) == 0
    assert "api: returned slot 1" in capsys.readouterr().out
    returns = calls(treehouse_state, "return")
    assert returns == [["return", "--force", "--if-lease-id", "id-1", "--if-lease-holder", "canopy:PROJ-9", str(slot)]]


def test_after_a_switch_release_finds_the_slot_in_the_other_pool(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use(canopy_env, "canopy")
    slot = ws.root / ".treehouse" / "api-fake" / "1" / "api"
    slot.mkdir(parents=True)
    held = {"name": "1", "path": str(slot), "status": "leased", "lease_id": "", "lease_holder": pools.QUARANTINED}
    treehouse_state.write_text(json.dumps({"pools": {str(ws.clone("api")): {"slots": [held]}}}))
    conn = ws.journal()
    ours = context(ws, canopy_env, conn).pool("api")
    lease = ours.lease("PROJ-1")
    held_by_a_run(conn, lease, "PROJ-1", pool_=PoolKind.CANOPY)
    # Both pools have a slot 1, so its number names neither.
    assert main(["workspace", "release", "api", "1"]) == 1
    assert f"name it by its path, {lease.path} or {slot}" in capsys.readouterr().err
    assert main(["workspace", "release", "api", str(slot)]) == 0
    assert capsys.readouterr().out == f"api: released slot 1 ({slot})\n"
    assert [s["status"] for s in fake_pool(treehouse_state, ws, "api")] == ["available"]


def test_under_treehouse_release_frees_the_slot_through_treehouse(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    slot = ws.root / ".treehouse" / "api-fake" / "1" / "api"
    slot.mkdir(parents=True)
    held = {"name": "1", "path": str(slot), "status": "leased", "lease_id": "", "lease_holder": pools.QUARANTINED}
    treehouse_state.write_text(json.dumps({"pools": {str(ws.clone("api")): {"slots": [held]}}}))
    assert main(["workspace", "release", "api", "1"]) == 0
    assert capsys.readouterr().out == f"api: released slot 1 ({slot})\n"
    assert [s["status"] for s in fake_pool(treehouse_state, ws, "api")] == ["available"]
    returns = [c for c in json.loads(treehouse_state.read_text())["calls"] if c[0] == "return"]
    assert returns == [["return", "--force", "--if-lease-holder", pools.QUARANTINED, str(slot)]]


# Listing a pool's slots, with `canopy workspace slots`


def test_slots_lists_each_slot_with_what_holds_it(
    ws: Ws,
    canopy_env: CanopyEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use(canopy_env, "canopy", slots="api = 3")
    conn = ws.journal()
    ours = context(ws, canopy_env, conn).pool("api")
    first = ours.lease("PROJ-1")
    run_id = held_by_a_run(conn, first, "PROJ-1", pool_=PoolKind.CANOPY)
    stale = ours.lease("PROJ-9")
    quarantined_path = quarantined(ws, canopy_env, conn, tmp_path)
    assert main(["workspace", "slots", "api"]) == 0
    out = capsys.readouterr().out.splitlines()
    leased = {r["path"]: r["leased_at"] for r in conn.execute("SELECT path, leased_at FROM slots")}
    stale_note = (
        "      no running run holds this lease; `canopy workspace release api 2` returns it now, as the next tick would"
    )
    quarantine_note = (
        "      a failed seeding holds it, counted as busy: remove the file seeding collided with, then "
        "`canopy workspace release api 3`"
    )
    assert out == [
        "api: canopy's pool, 3 slots of 3 declared",
        f"  1  leased  canopy:PROJ-1 (run:{run_id} of PROJ-1), since {leased[str(first.path)]}  pools/api/1/api",
        f"  2  leased  canopy:PROJ-9, since {leased[str(stale.path)]}  pools/api/2/api",
        stale_note,
        f"  3  leased  {pools.QUARANTINED}, since {leased[str(quarantined_path)]}  pools/api/3/api",
        quarantine_note,
    ]
    assert quarantined_path == ws.root / "pools" / "api" / "3" / "api"
    assert main(["workspace", "slots", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [(p["repo"], p["pool"], p["backend"], p["declared"]) for p in report["pools"]] == [
        ("api", "canopy", True, 3),
        ("web", "canopy", True, None),
    ]
    [one, two, _] = report["pools"][0]["slots"]
    assert (one["held_by"], one["note"], one["base"], one["seeded"]) == (f"run:{run_id} of PROJ-1", None, "", [])
    assert (two["held_by"], two["lease_holder"], two["lease_id"]) == (None, "canopy:PROJ-9", stale.lease_id)


def test_slots_lists_the_other_pool_while_it_has_slots(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    treehouse_worktree(ws, treehouse_state, "api")
    use(canopy_env, "canopy")
    ws.journal()
    assert main(["workspace", "slots", "api"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "api: canopy's pool, 0 slots",
        "api: treehouse's pool, 1 slot; pools.backend names the other, so this one only takes back its leases",
        "  1  available  .treehouse/api-fake/1/api",
    ]


def test_slots_says_which_pools_could_not_be_read_and_exits_1(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    treehouse_state.write_text("not json")
    shutil.rmtree(ws.clone("web"))
    assert main(["workspace", "slots"]) == 1
    printed = capsys.readouterr()
    lines = printed.out.splitlines()
    assert lines[0].startswith("api: treehouse's pool: treehouse status exited 1")
    assert lines[-1] == "web: treehouse's pool: no clone; run `canopy workspace sync`"
    assert "2 of 2 pools could not be read" in printed.err
    assert main(["workspace", "slots", "elsewhere"]) == 1
    assert "the map lists no repository elsewhere" in capsys.readouterr().err


# Removing one slot, with `canopy workspace remove-slot`


def test_remove_slot_removes_an_idle_slot_and_keeps_a_leased_one(
    ws: Ws,
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use(canopy_env, "canopy")
    conn = ws.journal()
    ours = context(ws, canopy_env, conn).pool("api")
    leased = ours.lease("PROJ-1")
    idle = ours.lease("PROJ-2")
    ours.return_slot(idle.path, lease_id=idle.lease_id, lease_holder=idle.lease_holder)
    assert main(["workspace", "remove-slot", "api", "1"]) == 1
    assert "api's pool kept slot 1: leased by canopy:PROJ-1" in capsys.readouterr().err
    assert main(["workspace", "remove-slot", "api", "2"]) == 0
    assert capsys.readouterr().out == f"api: removed slot 2 ({idle.path})\n"
    assert not idle.path.parent.exists()
    assert canopy_rows(conn) == [("api", str(leased.path), "canopy:PROJ-1")]


def test_remove_slot_forgets_a_slot_whose_directory_is_gone(
    ws: Ws,
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use(canopy_env, "canopy")
    conn = ws.journal()
    ours = context(ws, canopy_env, conn).pool("api")
    lease = ours.lease("PROJ-1")
    ours.return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    shutil.rmtree(lease.path.parent)
    assert main(["workspace", "slots", "api"]) == 0
    assert capsys.readouterr().out.splitlines()[1:] == [
        "  1  damaged  pools/api/1/api",
        "      its directory is gone; `canopy workspace remove-slot api 1` forgets it",
    ]
    assert main(["workspace", "remove-slot", "api", "1"]) == 0
    assert canopy_rows(conn) == []
    assert str(lease.path) not in git("worktree", "list", cwd=ws.clone("api"))


def test_under_treehouse_remove_slot_destroys_through_treehouse(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_pools(ws, treehouse_state)
    slot = ws.root / ".treehouse" / "api-fake" / "1" / "api"
    unmerged(treehouse_state, [str(slot)])
    assert main(["workspace", "remove-slot", "api", "1"]) == 1
    assert "api's pool kept slot 1" in capsys.readouterr().err
    unmerged(treehouse_state, [])
    assert main(["workspace", "remove-slot", "api", "1"]) == 0
    assert capsys.readouterr().out == f"api: removed slot 1 ({slot})\n"
    destroys = calls(treehouse_state, "destroy")
    assert destroys == [["destroy", "--yes", str(slot)]] * 2
    assert fake_pool(treehouse_state, ws, "api") == []
