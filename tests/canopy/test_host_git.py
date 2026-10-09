"""git the harness runs on the host, and a slot's `.git` link (DESIGN §8, HOST_ISOLATION §5).

The pool here is what treehouse makes: slots that are worktrees of one primary clone, sharing its git directory.
"""

import ast
import json
import sqlite3
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db, hostgit
from tests.canopy.helpers import InlineRunner, in_tick, journal, pool, slot_of, worker_does
from tests.conftest import CanopyEnv, GitPool, git

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "canopy"
# The worker's own git is not under test: it runs with the flags too, so only host-side git could fire a hook.
WORKER_COMMIT = hostgit.argv("commit", "--quiet", "--allow-empty", "-m", "PROJ-1: work")
HOOKS = ("post-checkout", "reference-transaction", "pre-push", "post-index-change")


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


@pytest.fixture
def worktree_pool(git_pool: GitPool, treehouse_state: Path, tmp_path: Path) -> tuple[Path, list[Path]]:
    """The primary clone and two worktree slots of it, which the fake treehouse leases instead of `git_pool`'s."""
    primary = tmp_path / "primary"
    git("clone", "--quiet", str(git_pool.origin), str(primary), cwd=tmp_path)
    slots = [tmp_path / "wpool" / name / "repo" for name in ("1", "2")]
    for slot in slots:
        git("worktree", "add", "--quiet", "--detach", str(slot), cwd=primary)
    state = [{"name": str(i), "path": str(p), "status": "available"} for i, p in enumerate(slots, 1)]
    treehouse_state.write_text(json.dumps({"max_trees": len(slots), "slots": state}))
    return primary, slots


def dispatch_and_run(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Row:
    runner = InlineRunner()
    tick_id = in_tick(conn, monkeypatch)
    args = ["dispatch", "PROJ-1", "--label", "agent-ready-tester", "--kind", "implement", "--slug", "work"]
    assert main(args, runner=runner) == 0
    db.finish_tick(conn, tick_id, "ok", "test")
    run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
    assert main(["_run", str(run_id)], runner=runner) == 0
    row = db.get_run(conn, run_id)
    assert row is not None
    return row


def plant(primary: Path, fired: Path) -> None:
    """Plant hooks and a filesystem monitor in the shared git directory, each recording that it ran."""
    for name in HOOKS:
        hook = primary / ".git" / "hooks" / name
        hook.write_text(f"#!/bin/sh\necho {name} >> {fired}\ncat > /dev/null\n")
        hook.chmod(0o755)
    monitor = primary / ".git" / "fsmonitor"
    monitor.write_text(f"#!/bin/sh\necho fsmonitor >> {fired}\nexit 1\n")
    monitor.chmod(0o755)
    git("config", "core.fsmonitor", str(monitor), cwd=primary)


def test_the_planted_hooks_fire_for_plain_git(worktree_pool: tuple[Path, list[Path]], tmp_path: Path) -> None:
    """The control for the test below: without the flags, the git `_run` runs would run them."""
    primary, slots = worktree_pool
    fired = tmp_path / "fired"
    plant(primary, fired)
    git("checkout", "--quiet", "-B", "x", "origin/main", cwd=slots[0])
    git("status", "--porcelain", cwd=slots[0])
    assert {"post-checkout", "reference-transaction", "fsmonitor"} <= set(fired.read_text().split())


def test_host_git_runs_no_hook_or_monitor_from_the_shared_git_directory(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    worktree_pool: tuple[Path, list[Path]],
    agent_log: Path,
    conn: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary, _ = worktree_pool
    fired = tmp_path / "fired"
    plant(primary, fired)
    # Left unpushed, so `_run` fetches, checks out, reads refs, and pushes: every git step it has.
    worker_does(monkeypatch, WORKER_COMMIT)
    run = dispatch_and_run(conn, monkeypatch)
    assert run["status"] == "done"
    slot = Path(slot_of(conn, run["id"])["slot_path"])
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)
    assert not fired.exists(), fired.read_text()


@pytest.mark.parametrize(
    "rewrite",
    [
        pytest.param("printf 'gitdir: /somewhere/else\\n' > .git", id="repointed"),
        pytest.param("rm .git && mkdir .git", id="directory"),
        pytest.param("rm .git && ln -s /somewhere/else .git", id="symlink"),
    ],
)
def test_a_worker_that_rewrites_the_git_link_crashes_the_run_and_the_link_is_put_back(
    rewrite: str,
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    worktree_pool: tuple[Path, list[Path]],
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, slots = worktree_pool
    links = {slot: (slot / ".git").read_bytes() for slot in slots}
    worker_does(monkeypatch, WORKER_COMMIT, ["sh", "-c", rewrite])
    run = dispatch_and_run(conn, monkeypatch)

    assert run["status"] == "crashed"
    slot = Path(slot_of(conn, run["id"])["slot_path"])
    result = json.loads(run["result_json"])
    assert result["harness"] == f"the worker rewrote {slot / '.git'}; nothing was checked or pushed"
    assert result["status"] == "done"  # what the worker claimed is kept
    # No git ran after the worker: its commit was not pushed for it.
    assert git_pool.remote_head("agent/PROJ-1-work") is None
    assert hostgit.read_link(slot) == links[slot]
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=slot) == "agent/PROJ-1-work"
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_a_clone_slot_has_no_link_to_check(git_pool: GitPool) -> None:
    assert hostgit.read_link(git_pool.slots[0]) is None


def test_read_link_never_follows_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"gitdir: /x\n")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    assert hostgit.read_link(worktree) is None  # missing
    (worktree / ".git").symlink_to(target)
    assert hostgit.read_link(worktree) is None


def test_restore_link_removes_what_is_there_without_following_it(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("the operator's")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").symlink_to(outside)
    hostgit.restore_link(worktree, b"gitdir: /pool/.git/worktrees/1\n")
    assert hostgit.read_link(worktree) == b"gitdir: /pool/.git/worktrees/1\n"
    assert (outside / "keep").read_text() == "the operator's"

    (worktree / ".git").unlink()
    (worktree / ".git").mkdir()
    (worktree / ".git" / "link").symlink_to(outside)
    hostgit.restore_link(worktree, b"gitdir: /y\n")
    assert hostgit.read_link(worktree) == b"gitdir: /y\n"
    assert (outside / "keep").read_text() == "the operator's"


def test_every_git_the_harness_runs_goes_through_hostgit() -> None:
    """No module but `hostgit` names the `git` executable, so none can run it without the flags."""
    found = [
        f"{path.relative_to(PACKAGE)}:{node.lineno}"
        for path in sorted(PACKAGE.rglob("*.py"))
        if path.name != "hostgit.py"
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path)))
        if isinstance(node, ast.Constant) and node.value == "git"
    ]
    assert found == []
