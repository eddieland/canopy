"""The pool contract (DESIGN §18, What a pool guarantees; ROADMAP M45): every guarantee canopy takes from a pool.

Each case states one guarantee through `core/treehouse.py`'s four operations, `status`, `lease`, `return_slot`, and
`destroy`, the interface every caller uses, and runs against each pool: the fake on every `make check`, and real
treehouse when it is on PATH (`make pool-contract`, which fails instead of skipping when it is not). A behavior no case
states is not a guarantee. Where pools differ on purpose, the design says so and the case says which expects what.

The fake models treehouse's CLI and its lease bookkeeping, not git: its slots are empty directories. A case about what
is in a slot (`checkout` below) runs only against a pool whose slots are real worktrees. For the fake, a dirty or busy
slot is one its state says is, as a test seeds it; for a real pool, one with a file written in it or a process in it.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import signal
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from canopy.core import hostgit, treehouse
from canopy.infra import procs
from tests.conftest import HERMETIC_GIT, git

# Found before any fixture puts the fake first on PATH.
REAL_TREEHOUSE = shutil.which("treehouse")
# Set by `make pool-contract`: real treehouse must run, so a missing one fails the run instead of skipping it.
REQUIRED = os.environ.get("CANOPY_POOL_CONTRACT") == "1"
REPO = "repo"
KEY = "PROJ-1"


class Impl(StrEnum):
    """A pool the contract runs against."""

    FAKE = "fake"
    TREEHOUSE = "treehouse"


def _impls() -> list[object]:
    real = pytest.mark.skipif(
        REAL_TREEHOUSE is None and not REQUIRED, reason="real treehouse is not on PATH; `make pool-contract` runs it"
    )
    return [pytest.param(Impl.FAKE, id="fake"), pytest.param(Impl.TREEHOUSE, id="treehouse", marks=real)]


@dataclass
class Contract:
    """One pool under test: a workspace with one repository, `repo`, cloned from a bare origin, and its pool.

    The operations are canopy's own, through `core/treehouse.py`; the helpers set up what a case needs in a way each
    pool understands.
    """

    impl: Impl
    root: Path
    origin: Path
    clone: Path
    state: Path
    runner: procs.Runner
    tmp: Path
    home: Path
    spawned: list[int] = field(default_factory=list[int])

    @property
    def pool(self) -> treehouse.Pool:
        """The repository's pool, as `Workspace.pool` gives it."""
        return treehouse.Pool(cwd=self.clone, root=self.root)

    @property
    def real(self) -> bool:
        """Whether slots are real worktrees, so a case may look inside one."""
        return self.impl is not Impl.FAKE

    def status(self, pool: treehouse.Pool | None = None) -> list[treehouse.Slot]:
        """Every slot, by name."""
        return sorted(treehouse.status(self.runner, pool=pool or self.pool), key=lambda s: int(s.name))

    def slot(self, path: Path) -> treehouse.Slot:
        """The slot at `path`."""
        return next(s for s in self.status() if s.path == path)

    def lease(self, key: str = KEY, *, base: str | None = None, pool: treehouse.Pool | None = None) -> treehouse.Lease:
        """Lease a slot for ticket `key`."""
        return treehouse.lease(self.runner, key, base=base, pool=pool or self.pool)

    def give_back(self, lease: treehouse.Lease, **override: str) -> treehouse.ReturnOutcome:
        """Return `lease`, or with its id or holder overridden."""
        return treehouse.return_slot(
            self.runner,
            lease.path,
            lease_id=override.get("lease_id", lease.lease_id),
            lease_holder=override.get("lease_holder", lease.lease_holder),
            pool=self.pool,
        )

    def limit(self, max_trees: int) -> None:
        """Bound an unmanaged pool at `max_trees` slots, where each pool reads its bound."""
        if self.real:
            config = self.home / ".config" / "treehouse" / "config.toml"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(f"max_trees = {max_trees}\n")
        else:
            self.state.write_text(json.dumps({"pools": {str(self.clone): {"slots": [], "max_trees": max_trees}}}))

    def make_dirty(self, path: Path) -> None:
        """Leave an untracked file in the slot at `path`, which `status --porcelain` reports."""
        if self.real:
            (path / "scratch.txt").write_text("left behind\n")
        elif self.slot(path).status == treehouse.AVAILABLE:
            self._edit_slot(path, status="dirty")

    def strand_work(self, path: Path) -> None:
        """Leave a commit in the idle slot at `path` that no branch has: clean, so `available`, but not reusable."""
        if self.real:
            git("commit", "--quiet", "--allow-empty", "-m", "committed in an idle slot", cwd=path)
        else:
            state: dict[str, Any] = json.loads(self.state.read_text())
            state["skip_reuse"] = [*state.get("skip_reuse", []), str(path)]
            state["unmerged"] = [*state.get("unmerged", []), str(path)]
            self.state.write_text(json.dumps(state))

    def occupy(self, path: Path) -> int:
        """Start a process whose working directory is in the slot at `path`. Returns its pid."""
        if not self.real:
            idle = self.slot(path).status == treehouse.AVAILABLE
            self._edit_slot(path, processes=[{"pid": 4242, "name": "sleep"}], **({"status": "in-use"} if idle else {}))
            return 4242
        pid = self.runner.spawn(["sleep", "300"], cwd=path, log_path=self.tmp / f"occupant-{len(self.spawned)}.log")
        self.spawned.append(pid)
        return pid

    def push(self, branch: str, *files: str) -> str:
        """Commit `files` to `branch` on origin, from a scratch clone. Returns the new commit."""
        work = self.tmp / f"push-{branch.replace('/', '-')}-{time.monotonic_ns()}"
        git("clone", "--quiet", str(self.origin), str(work), cwd=self.tmp)
        if git("ls-remote", "origin", f"refs/heads/{branch}", cwd=work):
            git("checkout", "--quiet", branch, cwd=work)
        else:
            git("checkout", "--quiet", "-b", branch, cwd=work)
        for name in files:
            (work / name).write_text(f"{name}\n")
        git("add", "--all", cwd=work)
        git("commit", "--quiet", "--allow-empty", "-m", f"push {branch}", cwd=work)
        git("push", "--quiet", "origin", f"HEAD:refs/heads/{branch}", cwd=work)
        return git("rev-parse", "HEAD", cwd=work)

    def _edit_slot(self, path: Path, **fields: object) -> None:
        state: dict[str, Any] = json.loads(self.state.read_text())
        for pool in state["pools"].values():
            for slot in pool["slots"]:
                if slot["path"] == str(path):
                    slot.update(fields)
        self.state.write_text(json.dumps(state))

    def stop_spawned(self) -> None:
        """Stop what `occupy` started that still runs."""
        for pid in self.spawned:
            if procs.alive(pid):
                os.kill(pid, signal.SIGKILL)


@pytest.fixture(params=_impls())
def pool(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Contract]:
    """A workspace of one repository and its pool, under `request.param`, with HOME and git kept off the machine's."""
    impl: Impl = request.param
    # Resolved, as a workspace's root is: on macOS the temp directory is a link, and treehouse names slots by the path
    # git gives, which is resolved.
    tmp_path = tmp_path.resolve()
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "treehouse.json"
    fakes = Path(__file__).resolve().parents[1] / "fakes"
    if impl is Impl.FAKE:
        (bin_dir / "treehouse").symlink_to(fakes / "treehouse")
    else:
        if REAL_TREEHOUSE is None:
            pytest.fail("CANOPY_POOL_CONTRACT=1, but treehouse is not on PATH; `make treehouse` installs it")
        (bin_dir / "treehouse").symlink_to(REAL_TREEHOUSE)
    variables = {
        **HERMETIC_GIT,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PATH": os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")]),
        "FAKE_TREEHOUSE_STATE": str(state),
        # Real treehouse checks for a newer release on every command, and may start a background process to.
        "TREEHOUSE_NO_UPDATE_CHECK": "1",
    }
    with mock.patch.dict(os.environ, variables):
        os.environ.pop("TREEHOUSE_LEASE_HOLDER", None)
        os.environ.pop("TREEHOUSE_ROOT", None)
        contract = _workspace(impl, tmp_path, state)
        try:
            yield contract
        finally:
            contract.stop_spawned()


def _workspace(impl: Impl, tmp_path: Path, state: Path) -> Contract:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git("init", "--quiet", "--bare", "--initial-branch=main", cwd=origin)
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "--quiet", "--initial-branch=main", cwd=seed)
    (seed / ".gitignore").write_text("*.local\nbuild/\n")
    (seed / "README").write_text("tracked\n")
    git("add", "--all", cwd=seed)
    git("commit", "--quiet", "-m", "initial", cwd=seed)
    git("push", "--quiet", str(origin), "main", cwd=seed)
    root = tmp_path / "ws"
    clone = root / "repos" / REPO
    clone.parent.mkdir(parents=True)
    git("clone", "--quiet", str(origin), str(clone), cwd=tmp_path)
    return Contract(impl, root, origin, clone, state, procs.SubprocessRunner(), tmp_path, tmp_path / "home")


def leased_at(stamp: str) -> datetime:
    """Parse a lease's time as the worktrees page does: ISO 8601 with an offset."""
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None, stamp
    return parsed


def needs_checkout(pool: Contract) -> None:
    """Skip a case about what is in a slot for a pool whose slots are not real worktrees."""
    if not pool.real:
        pytest.skip("the fake's slots are empty directories; this case is about what is in one")


def head(path: Path) -> str:
    return git("rev-parse", "HEAD", cwd=path)


def origin_head(pool: Contract, branch: str = "main") -> str:
    return git("rev-parse", f"refs/heads/{branch}", cwd=pool.origin)


# Leasing


def test_a_new_pool_has_no_slots(pool: Contract) -> None:
    assert pool.status() == []


def test_a_lease_names_its_slot_holder_time_and_base(pool: Contract) -> None:
    lease = pool.lease()
    assert lease.lease_holder == "canopy:PROJ-1"
    assert lease.base_branch == "main"
    assert lease.lease_id
    assert lease.path.is_dir()
    [slot] = pool.status()
    assert (slot.path, slot.status, slot.lease_id, slot.lease_holder) == (
        lease.path,
        "leased",
        lease.lease_id,
        lease.lease_holder,
    )
    assert slot.canopy_key == KEY
    assert slot.leased_at is not None
    assert leased_at(slot.leased_at) == leased_at(lease.leased_at)


def test_slots_live_under_the_workspace_in_the_pinned_layout(pool: Contract) -> None:
    lease = pool.lease()
    # treehouse names the pool directory for the repository and a hash of its remote; the layout below it is pinned.
    pool_dir, slot, leaf = lease.path.relative_to(pool.root / ".treehouse").parts
    assert pool_dir.startswith(f"{REPO}-")
    assert (slot, leaf) == ("1", REPO)
    assert pool.status()[0].name == "1"


def test_leases_held_at_once_are_different_slots(pool: Contract) -> None:
    first = pool.lease()
    second = pool.lease("PROJ-2")
    assert first.path != second.path
    assert first.lease_id != second.lease_id
    assert [(s.name, s.status, s.canopy_key) for s in pool.status()] == [
        ("1", "leased", KEY),
        ("2", "leased", "PROJ-2"),
    ]


def test_a_lease_on_a_base_starts_there(pool: Contract) -> None:
    tip = pool.push("agent/PROJ-0-base", "base.txt")
    lease = pool.lease(base="agent/PROJ-0-base")
    assert lease.base_branch == "agent/PROJ-0-base"
    needs_checkout(pool)
    assert head(lease.path) == tip


def test_a_lease_fetches_first_unless_told_not_to(pool: Contract) -> None:
    needs_checkout(pool)
    before = origin_head(pool)
    after = pool.push("main", "later.txt")
    unfetched = treehouse.lease_as(pool.runner, treehouse.SYNC_HOLDER, pool=pool.pool, fetch=False)
    assert head(unfetched.path) == before
    fetched = pool.lease()
    assert head(fetched.path) == after


def test_a_slot_is_a_detached_worktree_of_the_primary_clone(pool: Contract) -> None:
    needs_checkout(pool)
    lease = pool.lease()
    [slot] = pool.status()
    assert (slot.branch, slot.detached, slot.branch_error) == ("", True, "")
    # `_run` reads the `.git` file and checks `commondir` (D118): a slot is a linked worktree, never a clone.
    link = hostgit.read_link(lease.path)
    assert link is not None
    assert not hostgit.commondir_moved(lease.path, link)
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=lease.path)
    assert Path(common).resolve() == (pool.clone / ".git").resolve()
    assert head(lease.path) == origin_head(pool)


def test_a_sync_lease_names_no_ticket(pool: Contract) -> None:
    lease = treehouse.lease_as(pool.runner, treehouse.SYNC_HOLDER, pool=pool.pool, fetch=False)
    [slot] = pool.status()
    assert (slot.lease_holder, slot.lease_id, slot.canopy_key) == (treehouse.SYNC_HOLDER, lease.lease_id, None)


# Returning


def test_a_return_frees_the_slot(pool: Contract) -> None:
    lease = pool.lease()
    assert pool.give_back(lease) is treehouse.ReturnOutcome.RETURNED
    [slot] = pool.status()
    assert (slot.status, slot.lease_id, slot.lease_holder, slot.leased_at, slot.canopy_key) == (
        treehouse.AVAILABLE,
        "",
        "",
        None,
        None,
    )


@pytest.mark.parametrize("wrong", ["lease_id", "lease_holder"])
def test_a_return_needs_the_lease_id_and_holder(pool: Contract, wrong: str) -> None:
    lease = pool.lease()
    assert pool.give_back(lease, **{wrong: "canopy:someone-else"}) is treehouse.ReturnOutcome.FAILED
    [slot] = pool.status()
    assert (slot.status, slot.lease_id, slot.lease_holder) == ("leased", lease.lease_id, lease.lease_holder)


def test_a_lease_returns_once(pool: Contract) -> None:
    lease = pool.lease()
    pool.give_back(lease)
    again = pool.lease("PROJ-2")
    # The slot is someone else's now: the first lease's return must not touch it.
    assert pool.give_back(lease) is treehouse.ReturnOutcome.FAILED
    assert pool.slot(again.path).lease_id == again.lease_id


def test_returning_a_path_no_pool_manages_fails(pool: Contract) -> None:
    pool.lease()
    elsewhere = pool.root / ".treehouse" / "nowhere" / "1" / REPO
    outcome = treehouse.return_slot(
        pool.runner, elsewhere, lease_id="x", lease_holder=treehouse.holder_for(KEY), pool=pool.pool
    )
    assert outcome is treehouse.ReturnOutcome.FAILED


def test_a_return_finds_the_pool_from_the_slot_when_the_clone_is_gone(pool: Contract) -> None:
    lease = pool.lease()
    at_root = treehouse.Pool(cwd=pool.root, root=pool.root)
    outcome = treehouse.return_slot(
        pool.runner, lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder, pool=at_root
    )
    assert outcome is treehouse.ReturnOutcome.RETURNED
    assert pool.slot(lease.path).status == treehouse.AVAILABLE


def test_a_return_is_forced_and_discards_what_the_run_left(pool: Contract) -> None:
    lease = pool.lease()
    pool.make_dirty(lease.path)
    if pool.real:
        (lease.path / "README").write_text("changed\n")
        git("commit", "--quiet", "--allow-empty", "-m", "never pushed", cwd=lease.path)
    assert pool.give_back(lease) is treehouse.ReturnOutcome.RETURNED
    assert pool.slot(lease.path).status == treehouse.AVAILABLE
    if pool.real:
        assert not (lease.path / "scratch.txt").exists()
        assert (lease.path / "README").read_text() == "tracked\n"
        assert head(lease.path) == origin_head(pool)


def test_a_return_ends_the_processes_in_the_slot(pool: Contract) -> None:
    lease = pool.lease()
    pid = pool.occupy(lease.path)
    assert pool.give_back(lease) is treehouse.ReturnOutcome.RETURNED
    slot = pool.slot(lease.path)
    assert (slot.status, slot.processes) == (treehouse.AVAILABLE, [])
    if pool.real:
        assert not procs.alive(pid)


# Reuse


def test_a_returned_slot_is_reused(pool: Contract) -> None:
    first = pool.lease()
    pool.give_back(first)
    second = pool.lease("PROJ-2", base=None)
    assert second.path == first.path
    assert second.lease_id != first.lease_id
    assert len(pool.status()) == 1


def test_reuse_keeps_ignored_files_and_nothing_else(pool: Contract) -> None:
    needs_checkout(pool)
    first = pool.lease()
    (first.path / "build").mkdir()
    (first.path / "build" / "cache.bin").write_text("warm\n")
    (first.path / "untracked.txt").write_text("gone\n")
    (first.path / "README").write_text("edited\n")
    git("add", "README", cwd=first.path)
    git("commit", "--quiet", "-m", "never pushed", cwd=first.path)
    (first.path / "README").write_text("edited again\n")
    pool.give_back(first)
    tip = pool.push("main", "newer.txt")
    second = pool.lease("PROJ-2")
    assert second.path == first.path
    assert (second.path / "build" / "cache.bin").read_text() == "warm\n"
    assert not (second.path / "untracked.txt").exists()
    assert (second.path / "README").read_text() == "tracked\n"
    assert head(second.path) == tip
    assert git("status", "--porcelain", "--untracked-files=all", cwd=second.path) == ""


def test_a_return_parks_the_slot_on_its_base_and_it_is_reused(pool: Contract) -> None:
    needs_checkout(pool)
    tip = pool.push("agent/PROJ-0-base", "base.txt")
    stacked = pool.lease(base="agent/PROJ-0-base")
    pool.give_back(stacked)
    assert head(stacked.path) == tip
    # Ahead of main, but merged into the base it was leased on, so a lease on main may reset it.
    again = pool.lease("PROJ-2")
    assert again.path == stacked.path
    assert head(again.path) == origin_head(pool)


def test_an_idle_slot_with_changes_is_dirty_and_not_reused(pool: Contract) -> None:
    first = pool.lease()
    pool.give_back(first)
    pool.make_dirty(first.path)
    assert pool.slot(first.path).status == "dirty"
    second = pool.lease("PROJ-2")
    assert second.path != first.path
    assert pool.slot(first.path).status == "dirty"


def test_an_idle_slot_with_a_process_in_it_is_in_use_and_not_reused(pool: Contract) -> None:
    first = pool.lease()
    pool.give_back(first)
    pid = pool.occupy(first.path)
    slot = pool.slot(first.path)
    assert slot.status == "in-use"
    assert [p.pid for p in slot.processes] == [pid]
    second = pool.lease("PROJ-2")
    assert second.path != first.path


def test_an_idle_slot_with_unmerged_commits_is_not_reused(pool: Contract) -> None:
    first = pool.lease()
    pool.give_back(first)
    pool.strand_work(first.path)
    # Clean, so treehouse reports it available; a reset would lose the commit, so it is passed over.
    assert pool.slot(first.path).status == treehouse.AVAILABLE
    second = pool.lease("PROJ-2")
    assert second.path != first.path


# Seeding


def include(pool: Contract, *lines: str) -> treehouse.Pool:
    """Write the operator's own `.worktreeinclude` and return the pool with it."""
    manifest = pool.tmp / "worktreeinclude"
    manifest.write_text("".join(f"{line}\n" for line in lines))
    return dataclasses.replace(pool.pool, include_file=manifest)


def test_a_lease_seeds_the_ignored_files_the_include_file_selects(pool: Contract) -> None:
    needs_checkout(pool)
    (pool.clone / "user.local").write_text("personal\n")
    (pool.clone / "build").mkdir()
    (pool.clone / "build" / "out.bin").write_text("not selected\n")
    lease = pool.lease(pool=include(pool, "*.local"))
    assert (lease.path / "user.local").read_text() == "personal\n"
    assert not (lease.path / "build").exists()


def test_seeding_repeats_on_every_lease(pool: Contract) -> None:
    needs_checkout(pool)
    seeded = include(pool, "*.local")
    (pool.clone / "user.local").write_text("first\n")
    first = pool.lease(pool=seeded)
    pool.give_back(first)
    (pool.clone / "user.local").write_text("second\n")
    second = pool.lease("PROJ-2", pool=seeded)
    assert second.path == first.path
    assert (second.path / "user.local").read_text() == "second\n"


def test_seeding_never_copies_a_tracked_file(pool: Contract) -> None:
    needs_checkout(pool)
    (pool.clone / "README").write_text("edited in the clone\n")
    lease = pool.lease(pool=include(pool, "README"))
    assert (lease.path / "README").read_text() == "tracked\n"


def test_a_return_removes_what_seeding_wrote(pool: Contract) -> None:
    needs_checkout(pool)
    (pool.clone / "user.local").write_text("personal\n")
    first = pool.lease(pool=include(pool, "*.local"))
    pool.give_back(first)
    assert not (first.path / "user.local").exists()
    second = pool.lease("PROJ-2")
    assert second.path == first.path
    assert not (second.path / "user.local").exists()


def test_a_seed_target_already_in_the_slot_fails_the_lease_and_holds_the_slot(pool: Contract) -> None:
    needs_checkout(pool)
    first = pool.lease()
    # Ignored, so the return keeps it; seeding did not write it, so the return does not remove it.
    (first.path / "user.local").write_text("the run's own\n")
    pool.give_back(first)
    (pool.clone / "user.local").write_text("personal\n")
    with pytest.raises(treehouse.TreehouseError, match="file exists"):
        pool.lease("PROJ-2", pool=include(pool, "*.local"))
    # treehouse quarantines the slot, holding it under a holder no ticket can name, so no lease is handed it as is.
    slot = pool.slot(first.path)
    assert (slot.status, slot.lease_id, slot.canopy_key) == ("leased", "", None)
    assert slot.lease_holder.startswith("quarantined")
    assert (first.path / "user.local").read_text() == "the run's own\n"


def test_a_seeded_link_is_written_as_a_file_holding_its_target(pool: Contract) -> None:
    # Open in ROADMAP M45: whether a pool should copy it as a link instead, checked against TRUST_MODEL T4.
    needs_checkout(pool)
    (pool.clone / "link.local").symlink_to("/etc/hostname")
    lease = pool.lease(pool=include(pool, "*.local"))
    seeded = lease.path / "link.local"
    assert not seeded.is_symlink()
    assert seeded.read_text() == "/etc/hostname"


def test_a_missing_include_file_fails_the_lease_before_any_slot(pool: Contract) -> None:
    missing = dataclasses.replace(pool.pool, include_file=pool.tmp / "no-such-file")
    with pytest.raises(treehouse.TreehouseError):
        pool.lease(pool=missing)
    assert pool.status() == []


# Removing


def test_destroy_removes_an_idle_merged_slot(pool: Contract) -> None:
    lease = pool.lease()
    pool.give_back(lease)
    assert treehouse.destroy(pool.runner, lease.path, pool=pool.pool) is None
    assert pool.status() == []
    assert not lease.path.exists()


def test_destroy_keeps_a_leased_slot(pool: Contract) -> None:
    lease = pool.lease()
    assert treehouse.destroy(pool.runner, lease.path, pool=pool.pool)
    assert pool.slot(lease.path).lease_id == lease.lease_id


def test_destroy_keeps_a_dirty_slot(pool: Contract) -> None:
    lease = pool.lease()
    pool.give_back(lease)
    pool.make_dirty(lease.path)
    assert treehouse.destroy(pool.runner, lease.path, pool=pool.pool)
    assert pool.slot(lease.path).status == "dirty"


def test_destroy_keeps_a_slot_with_a_process_in_it(pool: Contract) -> None:
    lease = pool.lease()
    pool.give_back(lease)
    pool.occupy(lease.path)
    assert treehouse.destroy(pool.runner, lease.path, pool=pool.pool)
    assert lease.path.is_dir()


def test_destroy_keeps_a_slot_with_unmerged_commits(pool: Contract) -> None:
    lease = pool.lease()
    pool.give_back(lease)
    pool.strand_work(lease.path)
    assert treehouse.destroy(pool.runner, lease.path, pool=pool.pool)
    assert lease.path.is_dir()


def test_destroy_of_a_path_no_pool_manages_says_why(pool: Contract) -> None:
    pool.lease()
    assert treehouse.destroy(pool.runner, pool.root / "elsewhere", pool=pool.pool)


# Size


def test_an_unmanaged_pool_stops_at_its_bound(pool: Contract) -> None:
    pool.limit(1)
    pool.lease()
    with pytest.raises(treehouse.TreehouseError):
        pool.lease("PROJ-2")
    assert len(pool.status()) == 1


def test_a_declared_pool_with_every_slot_busy_refuses_without_growing(pool: Contract) -> None:
    sized = dataclasses.replace(pool.pool, slots=1)
    pool.lease(pool=sized)
    with pytest.raises(treehouse.TreehouseError, match="busy"):
        pool.lease("PROJ-2", pool=sized)
    assert len(pool.status()) == 1


def test_a_declared_pool_counts_a_dirty_idle_slot_as_busy(pool: Contract) -> None:
    sized = dataclasses.replace(pool.pool, slots=1)
    first = pool.lease(pool=sized)
    pool.give_back(first)
    pool.make_dirty(first.path)
    with pytest.raises(treehouse.TreehouseError, match="busy"):
        pool.lease("PROJ-2", pool=sized)
    assert [s.path for s in pool.status()] == [first.path]


def test_a_declared_pool_keeps_its_size_when_its_idle_slot_cannot_be_reused(pool: Contract) -> None:
    sized = dataclasses.replace(pool.pool, slots=1)
    first = pool.lease(pool=sized)
    pool.give_back(first)
    pool.strand_work(first.path)
    with pytest.raises(treehouse.TreehouseError, match="could be reused"):
        pool.lease("PROJ-2", pool=sized)
    assert [s.path for s in pool.status()] == [first.path]
