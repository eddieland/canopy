"""`canopy gc --git` (DESIGN §26, Git in the primary clones): it packs each primary clone's loose objects and combines
its packs, losing no commit a slot holds, and skips a repository while a slot of its pool is leased."""

import json
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.loop import git_gc
from tests.canopy.conftest import Ws
from tests.conftest import git

LEASE = {"lease_id": "id-1", "lease_holder": "canopy:PROJ-9", "leased_at": "2026-10-22T00:00:00Z"}


def loose_objects(clone: Path) -> int:
    """How many loose objects `clone` has."""
    counts = dict(line.split(": ") for line in git("count-objects", "-v", cwd=clone).splitlines())
    return int(counts["count"])


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
