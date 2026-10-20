"""git the harness runs on the host, and a slot's `.git` link (DESIGN §8, §24).

The pool here is what treehouse makes: slots that are worktrees of one primary clone, sharing its git directory.
"""

import ast
import json
from pathlib import Path

import pytest

from canopy.core import hostgit
from canopy.infra.procs import SubprocessRunner
from tests.canopy.helpers import pool, present, slot_of, worker_does
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import GitPool, executable, git

PACKAGE = Path(__file__).resolve().parents[3] / "src" / "canopy"
# The worker's own git is not under test: it runs with the flags too, so only host-side git could fire a hook.
WORKER_COMMIT = hostgit.argv("commit", "--quiet", "--allow-empty", "-m", "PROJ-1: work")
#: The overseer dispatches PROJ-1's implement on its `work` branch.
WORK = dispatches(slug="work")
HOOKS = ("post-checkout", "reference-transaction", "pre-push", "post-index-change")


def plant(primary: Path, fired: Path) -> None:
    """Plant hooks and a filesystem monitor in the shared git directory, each recording that it ran."""
    for name in HOOKS:
        hook = primary / ".git" / "hooks" / name
        executable(hook, f"#!/bin/sh\necho {name} >> {fired}\ncat > /dev/null\n")
    monitor = primary / ".git" / "fsmonitor"
    executable(monitor, f"#!/bin/sh\necho fsmonitor >> {fired}\nexit 1\n")
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
    scenario: Scenario, git_pool: GitPool, worktree_pool: tuple[Path, list[Path]], tmp_path: Path
) -> None:
    primary, _ = worktree_pool
    fired = tmp_path / "fired"
    plant(primary, fired)
    # Left unpushed, so `_run` fetches, checks out, reads refs, and pushes: every git step it has.
    run = scenario.run(WORK, worker=worker_does(WORKER_COMMIT))
    assert run.status == "done"
    slot = Path(slot_of(scenario.conn, run.id).slot_path)
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
    scenario: Scenario,
    git_pool: GitPool,
    worktree_pool: tuple[Path, list[Path]],
    treehouse_state: Path,
) -> None:
    _, slots = worktree_pool
    links = {slot: (slot / ".git").read_bytes() for slot in slots}
    run = scenario.run(WORK, worker=worker_does(WORKER_COMMIT, ["sh", "-c", rewrite]))

    assert run.status == "crashed"
    slot = Path(slot_of(scenario.conn, run.id).slot_path)
    result = json.loads(run.row["result_json"])
    assert result["harness"] == f"repo: the worker rewrote {slot / '.git'}; nothing was checked or pushed"
    assert result["status"] == "done"  # what the worker claimed is kept
    # No git ran after the worker: its commit was not pushed for it.
    assert git_pool.remote_head("agent/PROJ-1-work") is None
    assert hostgit.read_link(slot) == links[slot]
    assert git("log", "-1", "--format=%s", cwd=slot) == "PROJ-1: work"  # the slot's own git directory again
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def plant_common_dir(fired: Path) -> str:
    """Return a script that points the slot's `commondir` at a copy of the common directory, whose config runs a
    command on a fetch from origin."""
    return (
        "own=$(git rev-parse --path-format=absolute --git-dir) && common=$(git rev-parse --git-common-dir) && "
        'mkdir planted && cp -R "$common/objects" "$common/refs" "$common/HEAD" "$common/config" planted/ && '
        f'git config --file planted/config remote.origin.uploadpack "touch {fired}; git-upload-pack" && '
        'echo "$PWD/planted" > "$own/commondir"'
    )


def test_a_planted_commondir_runs_its_config_for_host_git(
    worktree_pool: tuple[Path, list[Path]], git_pool: GitPool, tmp_path: Path
) -> None:
    """The control for the test below: host git in a slot whose `commondir` was rewritten reads the planted config."""
    _, slots = worktree_pool
    fired = tmp_path / "fired"
    assert SubprocessRunner().run(["sh", "-c", plant_common_dir(fired)], cwd=slots[0]).ok
    SubprocessRunner().run(hostgit.argv("ls-remote", "origin"), cwd=slots[0], env=hostgit.ENV)
    assert fired.exists()


def test_a_worker_that_rewrites_commondir_crashes_the_run_and_commondir_is_put_back(
    scenario: Scenario,
    git_pool: GitPool,
    worktree_pool: tuple[Path, list[Path]],
    treehouse_state: Path,
    tmp_path: Path,
) -> None:
    _, slots = worktree_pool
    fired = tmp_path / "fired"
    commondirs = {slot: hostgit.own_git_dir(slot, (slot / ".git").read_bytes()) for slot in slots}
    run = scenario.run(WORK, worker=worker_does(WORKER_COMMIT, ["sh", "-c", plant_common_dir(fired)]))

    assert run.status == "crashed"
    slot = Path(slot_of(scenario.conn, run.id).slot_path)
    own = present(commondirs[slot])
    result = json.loads(run.row["result_json"])
    assert result["harness"] == f"repo: the worker rewrote {own / 'commondir'}; nothing was checked or pushed"
    assert not fired.exists()  # no git ran in the slot after the worker
    assert git_pool.remote_head("agent/PROJ-1-work") is None
    assert (own / "commondir").read_bytes() == hostgit.COMMONDIR_CONTENT
    assert all(s["status"] == "available" for s in pool(treehouse_state))


@pytest.mark.parametrize(
    ("content", "moved"),
    [
        pytest.param(b"../..\n", False, id="as-git-writes-it"),
        pytest.param(b"{common}\n", False, id="absolute"),
        pytest.param(b"../../worktrees/..", False, id="same-directory"),
        pytest.param(b"/somewhere/else\n", True, id="elsewhere"),
        pytest.param(b"..", True, id="worktrees"),
        pytest.param(None, True, id="missing"),
    ],
)
def test_commondir_must_name_the_directory_that_holds_the_slots_git_directory(
    content: bytes | None,
    moved: bool,  # noqa: FBT001  (a parameter)
    worktree_pool: tuple[Path, list[Path]],
) -> None:
    primary, slots = worktree_pool
    link = present(hostgit.read_link(slots[0]))
    own = present(hostgit.own_git_dir(slots[0], link))
    if content is None:
        (own / "commondir").unlink()
    else:
        (own / "commondir").write_bytes(content.replace(b"{common}", bytes(primary / ".git")))
    assert hostgit.commondir_moved(slots[0], link) is moved


def test_commondir_is_never_followed_and_is_put_back(worktree_pool: tuple[Path, list[Path]], tmp_path: Path) -> None:
    _, slots = worktree_pool
    link = present(hostgit.read_link(slots[0]))
    own = present(hostgit.own_git_dir(slots[0], link))
    outside = tmp_path / "outside"
    outside.write_bytes(b"../..\n")
    (own / "commondir").unlink()
    (own / "commondir").symlink_to(outside)
    assert hostgit.commondir_moved(slots[0], link)

    hostgit.restore_commondir(slots[0], link)

    assert (own / "commondir").read_bytes() == b"../..\n"
    assert not (own / "commondir").is_symlink()
    assert outside.read_bytes() == b"../..\n"
    assert not hostgit.commondir_moved(slots[0], link)
    assert git("status", "--porcelain", cwd=slots[0]) == ""


def test_a_clone_has_no_git_directory_named_by_a_link(git_pool: GitPool) -> None:
    assert hostgit.own_git_dir(git_pool.slots[0], b"") is None
    assert not hostgit.commondir_moved(git_pool.slots[0], b"")


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
