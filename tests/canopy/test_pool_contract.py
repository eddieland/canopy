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

from canopy.core import treehouse
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

    def make_dirty(self, path: Path) -> None:
        """Leave an untracked file in the slot at `path`, which `status --porcelain` reports."""
        if self.real:
            (path / "scratch.txt").write_text("left behind\n")
        else:
            self._edit_slot(path, status="dirty")

    def occupy(self, path: Path) -> int:
        """Start a process whose working directory is in the slot at `path`. Returns its pid."""
        if not self.real:
            self._edit_slot(path, status="in-use", processes=[{"pid": 4242, "name": "sleep"}])
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
    return Contract(impl, root, origin, clone, state, procs.SubprocessRunner(), tmp_path)


def leased_at(stamp: str) -> datetime:
    """Parse a lease's time as the worktrees page does: ISO 8601 with an offset."""
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None, stamp
    return parsed
