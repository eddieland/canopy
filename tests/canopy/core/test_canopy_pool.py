"""canopy's own pool (DESIGN §18, canopy's pool; ROADMAP M45, stage 2) beyond the contract: real git, at once, crashed.

`test_pool_contract.py` holds this pool to every guarantee treehouse keeps. These cases are about what only canopy's
pool does: two leases taken at once, a lease that died between making a worktree and recording it, a slot whose git
link a run rewrote (D118), and seeding that must not follow a link the slot holds.
"""

import contextlib
import json
import os
import sqlite3
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import pool, pools, workspace
from canopy.infra import cwds, logs, procs
from canopy.runs import reconcile
from tests.canopy.helpers import present
from tests.conftest import HERMETIC_GIT, CanopyEnv, Journals, git

REPO = "repo"


@dataclass(frozen=True)
class Ws:
    """A workspace root with one repository's clone of a bare origin, and a journal."""

    root: Path
    origin: Path
    clone: Path
    db_path: Path
    journals: Journals

    def pool(self, *, include_file: Path | None = None) -> pool.CanopyPool:
        runner = procs.SubprocessRunner()
        return pool.CanopyPool(runner, self.conn(), REPO, self.root, self.clone, include_file=include_file)

    def conn(self) -> sqlite3.Connection:
        return self.journals.open(self.db_path)

    def rows(self) -> list[sqlite3.Row]:
        return self.conn().execute("SELECT * FROM slots ORDER BY name").fetchall()


@pytest.fixture
def ws(tmp_path: Path, journals: Journals) -> Iterator[Ws]:
    tmp_path = tmp_path.resolve()
    with mock.patch.dict(os.environ, {**HERMETIC_GIT, "HOME": str(tmp_path)}):
        origin = tmp_path / "origin.git"
        origin.mkdir()
        git("init", "--quiet", "--bare", "--initial-branch=main", cwd=origin)
        seed = tmp_path / "seed"
        seed.mkdir()
        git("init", "--quiet", "--initial-branch=main", cwd=seed)
        (seed / ".gitignore").write_text("*.local\n")
        git("add", "--all", cwd=seed)
        git("commit", "--quiet", "-m", "initial", cwd=seed)
        git("push", "--quiet", str(origin), "main", cwd=seed)
        root = tmp_path / "ws"
        clone = root / "repos" / REPO
        clone.parent.mkdir(parents=True)
        git("clone", "--quiet", str(origin), str(clone), cwd=tmp_path)
        yield Ws(root, origin, clone, tmp_path / "canopy.db", journals)


# Run in a process of its own: lease a slot of the pool at argv[1] (root) for argv[3], recording it in the journal at
# argv[2], and print the lease.
LEASE_SCRIPT = """
import sys
from pathlib import Path
from canopy.core import db, pool
from canopy.infra import procs
root, journal, key = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
conn = db.connect(journal)
try:
    made = pool.CanopyPool(procs.SubprocessRunner(), conn, "repo", root, root / "repos" / "repo")
    print(made.lease(key).model_dump_json())
finally:
    conn.close()
"""


def test_two_leases_at_once_take_two_slots(ws: Ws) -> None:
    ws.conn()  # migrated before either process opens it
    results: list[procs.Result] = []

    def take(key: str) -> None:
        argv = [sys.executable, "-c", LEASE_SCRIPT, str(ws.root), str(ws.db_path), key]
        results.append(procs.SubprocessRunner().run(argv, timeout=120))

    threads = [threading.Thread(target=take, args=(f"PROJ-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [r.returncode for r in results] == [0, 0], [r.stderr for r in results]
    leases = [pools.Lease.model_validate_json(r.stdout) for r in results]
    assert len({lease.path for lease in leases}) == 2
    assert sorted(r["lease_holder"] for r in ws.rows()) == ["canopy:PROJ-0", "canopy:PROJ-1"]


def test_a_worktree_made_before_a_crash_could_record_it_is_adopted(ws: Ws) -> None:
    # A lease that died after `git worktree add` and before its row: the worktree is there, the journal knows nothing.
    path = ws.root / pool.POOLS_DIR / REPO / "1" / REPO
    path.parent.mkdir(parents=True)
    git("worktree", "add", "--quiet", "--detach", str(path), "origin/main", cwd=ws.clone)
    lease = ws.pool().lease("PROJ-1")
    assert lease.path == path
    [row] = ws.rows()
    assert (row["name"], row["lease_holder"]) == ("1", "canopy:PROJ-1")


def test_a_lease_that_died_before_its_worktree_is_returned_and_made_again(ws: Ws) -> None:
    lease = ws.pool().lease("PROJ-1")
    # As if the lease's process died after recording the row and before `git worktree add` finished.
    git("worktree", "remove", "--force", str(lease.path), cwd=ws.clone)
    assert not lease.path.exists()
    assert ws.pool().status()[0].status == "leased"
    # Reconcile returns a `canopy:` lease no running run holds; there is nothing to reset.
    returned = ws.pool().return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    assert returned is pools.ReturnOutcome.RETURNED
    assert ws.pool().status()[0].status == "damaged"
    again = ws.pool().lease("PROJ-2")
    assert again.path == lease.path
    assert (again.path / ".git").is_file()
    assert [r["name"] for r in ws.rows()] == ["1"]


def test_a_slot_whose_git_link_was_rewritten_is_never_touched(ws: Ws, tmp_path: Path) -> None:
    lease = ws.pool().lease("PROJ-1")
    ws.pool().return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    git("init", "--quiet", cwd=elsewhere)
    (lease.path / ".git").write_text(f"gitdir: {elsewhere / '.git'}\n")
    assert ws.pool().status()[0].status == "damaged"
    again = ws.pool().lease("PROJ-2")
    assert again.path != lease.path
    kept = present(ws.pool().destroy(lease.path))
    assert "damaged" in kept
    assert lease.path.is_dir()


def test_seeding_never_writes_through_a_link_in_the_slot(ws: Ws, tmp_path: Path) -> None:
    lease = ws.pool().lease("PROJ-1")
    outside = tmp_path / "outside"
    outside.mkdir()
    # A run leaves a link where a seeded file's directory goes; ignored, so the return keeps it.
    (ws.clone / "conf.local").mkdir()
    (ws.clone / "conf.local" / "user").write_text("personal\n")
    (lease.path / "conf.local").symlink_to(outside)
    ws.pool().return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    manifest = tmp_path / "worktreeinclude"
    manifest.write_text("*.local\n")
    with pytest.raises(pools.PoolError):
        ws.pool(include_file=manifest).lease("PROJ-2")
    assert list(outside.iterdir()) == []
    [row] = ws.rows()
    assert row["lease_holder"] == pools.QUARANTINED


def test_the_journal_records_what_seeding_wrote(ws: Ws, tmp_path: Path) -> None:
    (ws.clone / "user.local").write_text("personal\n")
    manifest = tmp_path / "worktreeinclude"
    manifest.write_text("*.local\n")
    ws.pool(include_file=manifest).lease("PROJ-1")
    [row] = ws.rows()
    assert json.loads(row["seeded"]) == ["user.local"]


def test_a_full_pool_names_its_bound(ws: Ws) -> None:
    with mock.patch.object(pool, "MAX_SLOTS", 1):
        ws.pool().lease("PROJ-1")
        with pytest.raises(pools.PoolError, match="stops at 1"):
            ws.pool().lease("PROJ-2")


# The shadow (ROADMAP M45, stage 2)


def test_the_shadow_logs_where_canopy_and_treehouse_disagree_and_changes_nothing(
    canopy_env: CanopyEnv,
    tmp_path: Path,
) -> None:
    with mock.patch.dict(os.environ, HERMETIC_GIT):
        clone = canopy_env.repo
        with contextlib.suppress(FileNotFoundError):
            (clone / ".git").rmdir()
        git("init", "--quiet", "--initial-branch=main", cwd=clone)
        git("commit", "--quiet", "--allow-empty", "-m", "initial", cwd=clone)
        clean = tmp_path / "slots" / "1" / REPO
        dirty = tmp_path / "slots" / "2" / REPO
        for path in (clean, dirty):
            path.parent.mkdir(parents=True)
            git("worktree", "add", "--quiet", "--detach", str(path), cwd=clone)
        (dirty / "scratch.txt").write_text("left\n")
        said = {
            REPO: [
                pools.Slot(name="1", path=clean, status="available"),
                pools.Slot(name="2", path=dirty, status="available"),
                pools.Slot(name="3", path=tmp_path / "held", status="leased", lease_id="x", lease_holder="canopy:P-1"),
            ],
        }
        log = mock.create_autospec(logs.TickAdapter, instance=True)
        with mock.patch.object(cwds, "table", autospec=True, side_effect=cwds.table) as read:
            assert reconcile.shadow(procs.SubprocessRunner(), workspace.find(canopy_env.root), log, said) == 1
        # One read of the process table for every slot: on macOS each read is a full `lsof`.
        assert read.call_count == 1
        [call] = log.warning.call_args_list
        assert call.args == ("pool_shadow_mismatch",)
        assert call.kwargs["extra"] == {"repo": REPO, "slot": str(dirty), "treehouse": "available", "canopy": "dirty"}
        assert (dirty / "scratch.txt").exists()
