"""`canopy workspace sync` fetches each primary clone and fast-forwards its default branch, only when that is checked
out with nothing to lose (DESIGN §18)."""

import shutil
from pathlib import Path

import pytest

from canopy.cli.main import main
from tests.canopy.conftest import Ws
from tests.conftest import git


def origin_moves_on(ws: Ws, name: str, tmp_path: Path) -> str:
    """Push a new commit to `name`'s origin `main`, as someone else's merge would.

    Returns:
        The commit, shortened as sync prints it.
    """
    other = tmp_path / f"other-{name}"
    git("clone", "--quiet", str(ws.origins[name]), str(other), cwd=tmp_path)
    git("commit", "--quiet", "--allow-empty", "-m", "merged elsewhere", cwd=other)
    git("push", "--quiet", "origin", "main", cwd=other)
    return git("rev-parse", "--short", "HEAD", cwd=other)


def head(ws: Ws, name: str) -> str:
    return git("rev-parse", "--short", "HEAD", cwd=ws.clone(name))


def test_sync_fast_forwards_a_clean_default_branch_that_is_behind(
    ws: Ws,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = head(ws, "api")
    after = origin_moves_on(ws, "api", tmp_path)

    assert main(["workspace", "sync"]) == 0

    out = capsys.readouterr().out
    assert f"api: fast-forwarded: main from {before} to {after}\n" in out
    assert f"web: up to date: main at {head(ws, 'web')}\n" in out
    assert head(ws, "api") == after


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("uncommitted", "it has uncommitted changes"),
        ("committed", "main has commits origin/main does not"),
        ("branch", "it is on topic, not main"),
        ("detached", "HEAD is detached"),
        ("no origin/HEAD", "origin/HEAD is not set, so the default branch is unknown"),
    ],
)
def test_sync_leaves_a_clone_with_anything_to_lose_where_it_is(
    ws: Ws,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    change: str,
    reason: str,
) -> None:
    clone = ws.clone("api")
    origin_moves_on(ws, "api", tmp_path)
    match change:
        case "uncommitted":
            (clone / "notes.txt").write_text("staged, not committed\n")
            git("add", "notes.txt", cwd=clone)
        case "committed":
            git("commit", "--quiet", "--allow-empty", "-m", "local", cwd=clone)
        case "branch":
            git("checkout", "--quiet", "-b", "topic", cwd=clone)
        case "detached":
            git("checkout", "--quiet", "--detach", cwd=clone)
        case _:
            git("remote", "set-head", "origin", "--delete", cwd=clone)
            # Since git 2.48 a fetch makes a missing origin/HEAD again, unless the clone says not to.
            git("config", "remote.origin.followRemoteHEAD", "never", cwd=clone)
    before = head(ws, "api")

    assert main(["workspace", "sync"]) == 0

    assert f"api: not fast-forwarded: {reason}" in capsys.readouterr().out
    assert head(ws, "api") == before


def test_an_untracked_file_does_not_hold_a_fast_forward_back(
    ws: Ws,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (ws.clone("api") / "scratch.txt").write_text("the operator's\n")
    after = origin_moves_on(ws, "api", tmp_path)

    assert main(["workspace", "sync"]) == 0

    assert "api: fast-forwarded: " in capsys.readouterr().out
    assert head(ws, "api") == after
    assert (ws.clone("api") / "scratch.txt").read_text() == "the operator's\n"


def test_an_untracked_file_the_fast_forward_would_overwrite_holds_it_back(
    ws: Ws,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    other = tmp_path / "other-api"
    git("clone", "--quiet", str(ws.origins["api"]), str(other), cwd=tmp_path)
    (other / "notes.txt").write_text("theirs\n")
    git("add", "notes.txt", cwd=other)
    git("commit", "--quiet", "-m", "notes", cwd=other)
    git("push", "--quiet", "origin", "main", cwd=other)
    (ws.clone("api") / "notes.txt").write_text("the operator's\n")
    before = head(ws, "api")

    assert main(["workspace", "sync"]) == 0

    out = capsys.readouterr().out
    assert "api: not fast-forwarded: git merge refused: The following untracked working tree files would be " in out
    assert head(ws, "api") == before
    assert (ws.clone("api") / "notes.txt").read_text() == "the operator's\n"


def test_a_dry_run_fetches_nothing(ws: Ws, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = git("rev-parse", "origin/main", cwd=ws.clone("api"))
    origin_moves_on(ws, "api", tmp_path)

    assert main(["workspace", "sync", "--dry-run"]) == 0

    assert "api: to fetch: would fetch origin" in capsys.readouterr().out
    assert git("rev-parse", "origin/main", cwd=ws.clone("api")) == before


def test_a_fetch_that_fails_fails_the_sync(ws: Ws, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.rmtree(ws.origins["api"])

    assert main(["workspace", "sync"]) == 1

    out = capsys.readouterr().out
    assert "api: failed: git fetch exited 128: " in out
    assert f"web: up to date: main at {head(ws, 'web')}\n" in out
