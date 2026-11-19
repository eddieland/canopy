"""`canopy gc --git` (DESIGN §26, Git in the primary clones): it packs each primary clone's loose objects.

It combines its packs, losing no commit a slot holds, but not a partial clone's, and skips a repository while a slot of
its pool is leased.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Final
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.loop import git_gc
from tests.canopy.conftest import Ws, turn_off_auto_maintenance
from tests.conftest import git

LEASE: Final = {"lease_id": "id-1", "lease_holder": "canopy:PROJ-9", "leased_at": "2026-10-22T00:00:00Z"}


def loose_objects(clone: Path) -> int:
    """How many loose objects `clone` has."""
    counts = dict(line.split(": ") for line in git("count-objects", "-v", cwd=clone).splitlines())
    return int(counts["count"])


def multi_pack_index(clone: Path) -> bool:
    """Whether `clone` has the multi-pack index git's incremental-repack writes."""
    return (clone / ".git" / "objects" / "pack" / "multi-pack-index").exists()


def partial_clone(ws: Ws, name: str, tmp_path: Path) -> Path:
    """Make `name`'s primary clone a `blob:none` clone of its origin, as `clone_filter` makes it, with promisor packs.

    Its origin gets history with blobs the clone never fetches, and the clone a pack from its clone, one from a fetch,
    and ones git fetched lazily.

    Returns:
        The clone.
    """
    origin, clone = ws.origins[name], ws.clone(name)
    git("config", "uploadpack.allowFilter", "true", cwd=origin)
    seed = tmp_path / f"history-{name}"
    git("clone", "--quiet", str(origin), str(seed), cwd=tmp_path)
    for n in range(4):
        (seed / "a.txt").write_text(f"v{n}\n")
        (seed / f"big{n}.txt").write_text(os.urandom(20_000).hex())
        git("add", "--all", cwd=seed)
        git("commit", "--quiet", "-m", f"history {n}", cwd=seed)
        if n == 2:
            git("push", "--quiet", "origin", "main", cwd=seed)
            shutil.rmtree(clone)
            git("clone", "--quiet", "--filter=blob:none", f"file://{origin}", str(clone), cwd=tmp_path)
            turn_off_auto_maintenance(clone)
    git("push", "--quiet", "origin", "main", cwd=seed)
    git("fetch", "--quiet", "origin", cwd=clone)
    git("cat-file", "blob", "origin/main~3:big0.txt", cwd=clone)
    git("cat-file", "blob", "origin/main:big3.txt", cwd=clone)
    return clone


def slot_with_unpushed_commit(ws: Ws, treehouse_state: Path, name: str, **lease: str) -> tuple[Path, str]:
    """Give `name`'s pool one worktree slot of its primary clone, holding a commit no branch or remote has.

    Returns:
        The slot and the commit.
    """
    slot = ws.root / ".treehouse" / f"{name}-fake" / "1" / name
    git("worktree", "add", "--quiet", "--detach", str(slot), cwd=ws.clone(name))
    (slot / "work.txt").write_text("unpushed work\n")
    git("add", "work.txt", cwd=slot)
    git("commit", "--quiet", "-m", "unpushed work", cwd=slot)
    status = "leased" if lease else "available"
    state = {"pools": {str(ws.clone(name)): {"slots": [{"name": "1", "path": str(slot), "status": status, **lease}]}}}
    treehouse_state.write_text(json.dumps(state))
    return slot, git("rev-parse", "HEAD", cwd=slot)


def test_gc_git_packs_every_loose_object_and_keeps_a_slots_unpushed_commit(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    slot, commit = slot_with_unpushed_commit(ws, treehouse_state, "api")
    # A clone of a local origin hard-links its objects, so it starts with no pack, which git's repack refuses.
    assert loose_objects(ws.clone("api")) > 0

    assert main(["gc", "--git"]) == 0

    out = capsys.readouterr().out
    assert "api: packed: " in out
    assert "web: packed: " in out
    assert loose_objects(ws.clone("api")) == 0
    assert loose_objects(ws.clone("web")) == 0
    assert git("cat-file", "-t", commit, cwd=ws.clone("api")) == "commit"
    git("fsck", "--connectivity-only", "--no-progress", cwd=ws.clone("api"))
    git("push", "--quiet", "origin", "HEAD:refs/heads/after-gc", cwd=slot)
    assert ws.remote_head("api", "after-gc") == commit


def test_gc_git_skips_a_repository_with_a_leased_slot(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    slot_with_unpushed_commit(ws, treehouse_state, "api", **LEASE)
    loose = loose_objects(ws.clone("api"))

    assert main(["gc", "--git"]) == 0

    out = capsys.readouterr().out
    assert "api: skipped: slot 1 is leased; run it again once none is\n" in out
    assert "web: packed: " in out
    assert loose_objects(ws.clone("api")) == loose


def test_gc_git_skips_a_clone_whose_maintenance_lock_is_held(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    treehouse_state.write_text(json.dumps({"pools": {}}))
    lock = ws.clone("web") / ".git" / "objects" / "maintenance.lock"
    lock.write_text("")

    assert main(["gc", "--git"]) == 0

    out = capsys.readouterr().out
    assert "api: packed: " in out
    assert f"web: skipped: {lock} is held: git's own maintenance runs there, or a dead one left it\n" in out


def test_gc_git_says_where_git_failed_and_exits_1(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    treehouse_state.write_text(json.dumps({"pools": {}}))

    with mock.patch.object(git_gc, "STEPS", (("maintenance", "run", "--task=no-such-task"),)):
        assert main(["gc", "--git"]) == 1

    captured = capsys.readouterr()
    assert "api: failed: git maintenance run --task=no-such-task exited 129: " in captured.out
    assert "git failed in 2 of 2 primary clones" in captured.err


def test_gc_git_combines_no_packs_in_a_partial_clone_and_keeps_it_whole(
    ws: Ws,
    treehouse_state: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    treehouse_state.write_text(json.dumps({"pools": {}}))
    clone = partial_clone(ws, "api", tmp_path)
    (clone / "local.txt").write_text("the clone's own\n")
    git("add", "local.txt", cwd=clone)
    git("commit", "--quiet", "-m", "the clone's own", cwd=clone)
    assert loose_objects(clone) > 0

    # incremental-repack merges packs on one run and expires the old ones on the next, so a run alone shows nothing.
    for _ in range(3):
        assert main(["gc", "--git"]) == 0

    lines = capsys.readouterr().out.splitlines()
    api = [line for line in lines if line.startswith("api: ")]
    assert len(api) == 3
    assert all(
        line.startswith("api: packed: ") and line.endswith(f"; combined no packs: {git_gc.PARTIAL}") for line in api
    )
    assert not any(git_gc.PARTIAL in line for line in lines if line.startswith("web: "))
    assert loose_objects(clone) == 0
    assert not multi_pack_index(clone)
    assert multi_pack_index(ws.clone("web"))
    git("fsck", "--no-progress", cwd=clone)


def test_gc_git_combines_no_packs_in_a_clone_whose_config_git_cannot_read(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    treehouse_state.write_text(json.dumps({"pools": {}}))

    with mock.patch.object(git_gc, "_PARTIAL_KEYS", "("):
        assert main(["gc", "--git"]) == 0

    assert f"; combined no packs: {git_gc.UNREAD}\n" in capsys.readouterr().out
    assert loose_objects(ws.clone("api")) == 0
    assert not multi_pack_index(ws.clone("api"))
