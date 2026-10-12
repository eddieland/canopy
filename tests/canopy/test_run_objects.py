"""The per-run object directory and how a run's slots are tidied (DESIGN §8, D111, HOST_ISOLATION §4.2).

A sandboxed worker cannot write the git directory its slot shares, so its new objects go to the run's own directory,
which a sandbox wrapper names to git. These tests play that wrapper in the fake worker's commands: they set git's
variables from `CANOPY_GIT_OBJECTS`, as `examples/sandbox/canopy-sandbox` will.
"""

import sqlite3
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db, hostgit
from canopy.infra.procs import SubprocessRunner
from tests.canopy.helpers import InlineRunner, in_tick, journal, pool, slot_of, worker_does
from tests.conftest import CanopyEnv, GitPool, git

BRANCH = "agent/PROJ-1-work"
DEAD_PID = 4_194_305
# What a sandbox wrapper does before git runs: new objects to the run's directory, the slot's shared ones read through.
SANDBOXED = (
    'export GIT_OBJECT_DIRECTORY="$CANOPY_GIT_OBJECTS" '
    'GIT_ALTERNATE_OBJECT_DIRECTORIES="$(git rev-parse --path-format=absolute --git-common-dir)/objects"; '
)
# A worker that commits, leaves a ref of the worktree's own and a FETCH_HEAD naming its objects, and pushes nothing.
WORKER = (
    SANDBOXED + "git -c core.hooksPath=/dev/null commit --quiet --allow-empty -m 'PROJ-1: work' && "
    "git update-ref refs/worktree/mine HEAD && git fetch --quiet --refmap= origin main"
)


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


def dispatch(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, runner: InlineRunner) -> int:
    tick_id = in_tick(conn, monkeypatch)
    args = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
    assert main([*args, "--slug", "work"], runner=runner) == 0
    db.finish_tick(conn, tick_id, "ok", "test")
    return int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])


def objects_of(canopy_env: CanopyEnv, run_id: int) -> Path:
    return canopy_env.state_dir / "runs" / f"{run_id}.objects"


def assert_healthy(slot: Path, primary: Path) -> None:
    """git works in the slot and the primary clone, and names no missing object, now the run's objects are gone."""
    for args, cwd in (
        (("status", "--porcelain"), slot),
        (("for-each-ref",), slot),
        (("fsck", "--no-progress"), slot),
        (("gc", "--quiet"), primary),
        (("fsck", "--no-progress"), primary),
    ):
        git(*args, cwd=cwd)


def test_a_sandboxed_workers_commits_are_pushed_from_the_run_directory_and_the_slot_is_tidied(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    worktree_pool: tuple[Path, list[Path]],
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary, _ = worktree_pool
    worker_does(monkeypatch, ["sh", "-c", WORKER])
    runner = InlineRunner()
    run_id = dispatch(conn, monkeypatch, runner)
    assert main(["_run", str(run_id)], runner=runner) == 0

    run = db.get_run(conn, run_id)
    assert run is not None
    assert run["status"] == "done"
    pushed = git_pool.remote_head(BRANCH)
    assert pushed is not None  # `_run`'s own push read the commit from the run's directory
    # The commit was only ever in the run's directory: the shared one never had it.
    assert not SubprocessRunner().run(["git", "cat-file", "-e", pushed], cwd=primary).ok
    slot = Path(slot_of(conn, run_id)["slot_path"])
    assert git("rev-parse", "HEAD", cwd=slot) == git_pool.remote_head("main")  # back on origin/main
    assert git("for-each-ref", "refs/worktree", cwd=slot) == ""
    assert not objects_of(canopy_env, run_id).exists()
    assert_healthy(slot, primary)
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_an_unsandboxed_run_leaves_the_directory_empty_and_its_slot_alone(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    worktree_pool: tuple[Path, list[Path]],
    agent_log: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_does(monkeypatch, hostgit.argv("commit", "--quiet", "--allow-empty", "-m", "PROJ-1: work"))
    runner = InlineRunner()
    run_id = dispatch(conn, monkeypatch, runner)
    assert main(["_run", str(run_id)], runner=runner) == 0

    slot = Path(slot_of(conn, run_id)["slot_path"])
    # Not tidied: HEAD stays on the worker's commit, which `_run` pushed, as before the object directory.
    assert git("rev-parse", "HEAD", cwd=slot) == git_pool.remote_head(BRANCH)
    assert not objects_of(canopy_env, run_id).exists()


def sandboxed_worker_then_kill(canopy_env: CanopyEnv, conn: sqlite3.Connection, run_id: int, slot: Path) -> None:
    """What `_run` and a sandboxed worker leave when `_run` is killed with SIGKILL after the worker committed."""
    db.set_slot_link(conn, run_id, "repo", hostgit.read_link(slot))
    git("fetch", "--quiet", "origin", cwd=slot)
    git("checkout", "--quiet", "--detach", "refs/remotes/origin/main", cwd=slot)
    objects = objects_of(canopy_env, run_id)
    objects.mkdir(mode=0o700)
    done = SubprocessRunner().run(["sh", "-c", WORKER], cwd=slot, env={"CANOPY_GIT_OBJECTS": str(objects)})
    assert done.ok, done.stderr
    conn.execute("UPDATE runs SET pid = ? WHERE id = ?", (DEAD_PID, run_id))


@pytest.mark.parametrize("rewrites_link", [False, True])
def test_reconcile_tidies_the_slots_of_a_killed_run(
    rewrites_link: bool,  # noqa: FBT001  (a parameter)
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    worktree_pool: tuple[Path, list[Path]],
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary, _ = worktree_pool
    run_id = dispatch(conn, monkeypatch, InlineRunner())
    slot = Path(slot_of(conn, run_id)["slot_path"])
    link = (slot / ".git").read_bytes()
    sandboxed_worker_then_kill(canopy_env, conn, run_id, slot)
    if rewrites_link:
        (slot / ".git").write_text("gitdir: /somewhere/else\n")

    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    assert main(["tick"]) == 0

    run = db.get_run(conn, run_id)
    assert run is not None
    assert run["status"] == "crashed"
    assert (slot / ".git").read_bytes() == link  # put back, from what `_run` recorded, before any git ran there
    assert git("rev-parse", "HEAD", cwd=slot) == git_pool.remote_head("main")
    assert not objects_of(canopy_env, run_id).exists()
    assert_healthy(slot, primary)
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_without_tidying_the_run_directory_cannot_go(
    canopy_env: CanopyEnv,
    worktree_pool: tuple[Path, list[Path]],
    agent_log: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control for the tests above: deleting the run's objects as they are breaks `gc` in the primary clone."""
    primary, _ = worktree_pool
    run_id = dispatch(conn, monkeypatch, InlineRunner())
    slot = Path(slot_of(conn, run_id)["slot_path"])
    sandboxed_worker_then_kill(canopy_env, conn, run_id, slot)
    for path in sorted(objects_of(canopy_env, run_id).rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    assert not SubprocessRunner().run(["git", "gc", "--quiet"], cwd=primary).ok
