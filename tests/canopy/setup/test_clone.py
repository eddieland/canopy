"""`canopy workspace sync` clones a missing repository beside its place, and moves it there only once it finished."""

from collections.abc import Sequence
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import config, workspace
from canopy.infra import procs
from canopy.setup import workspace as setup_workspace
from tests.canopy.conftest import Ws, map_text
from tests.conftest import git


def git_leaves_a_clone_behind(result: procs.Result | BaseException) -> procs.Runner:
    """A runner whose clone writes a `.git` into its target, as git killed part way does, then ends with `result`.

    An exception is raised in place of a result, as an interrupt reaches the clone.
    """

    def run(args: Sequence[str], **_: object) -> procs.Result:
        (Path(args[-1]) / ".git" / "objects").mkdir(parents=True)
        if isinstance(result, BaseException):
            raise result
        return result

    runner = mock.create_autospec(procs.SubprocessRunner, instance=True)
    runner.run.side_effect = run
    return runner


def staging(repo: workspace.Repo) -> Path:
    """Where git clones `repo` before the clone moves into place."""
    return repo.path.with_name(f".{repo.name}.cloning")


def docs_repo(ws: Ws) -> workspace.Repo:
    """Map a third repository, `docs`, with no clone, and return it."""
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(*((n, str(o)) for n, o in ws.origins.items()), ("docs", "https://x.test/docs.git")),
    )
    found = workspace.find(ws.root)
    [docs] = setup_workspace.missing(found)
    return docs


@pytest.mark.parametrize(
    ("result", "said"),
    [
        (procs.Result(("git",), -9, "", "", timed_out=True), "git clone timed out"),
        (
            procs.Result(("git",), 128, "", "fatal: early EOF", timed_out=False),
            "git clone exited 128: fatal: early EOF",
        ),
    ],
)
def test_a_clone_that_does_not_finish_leaves_nothing_for_the_next_sync_to_take_as_cloned(
    ws: Ws,
    result: procs.Result,
    said: str,
) -> None:
    docs = docs_repo(ws)
    checked = setup_workspace.clone(git_leaves_a_clone_behind(result), workspace.find(ws.root), docs)
    assert (checked.outcome, checked.detail) == ("failed", said)
    assert not docs.path.exists()
    assert not staging(docs).exists()
    assert [r.name for r in setup_workspace.missing(workspace.find(ws.root))] == ["docs"]


def test_a_clone_interrupted_leaves_nothing_behind(ws: Ws) -> None:
    docs = docs_repo(ws)
    runner = git_leaves_a_clone_behind(KeyboardInterrupt())
    docs.path.mkdir(parents=True)  # an empty directory where the clone goes, which sync takes as no clone
    with pytest.raises(KeyboardInterrupt):
        setup_workspace.clone(runner, workspace.find(ws.root), docs)
    assert not any(docs.path.iterdir())  # the directory that was there, as it was
    assert not staging(docs).exists()


def test_what_a_killed_clone_left_is_never_a_clone_and_the_next_clone_clears_it(ws: Ws) -> None:
    docs = docs_repo(ws)
    # A clone killed outright, as by SIGKILL, runs no cleanup: what it wrote is beside the clone, not in its place.
    (staging(docs) / ".git" / "objects").mkdir(parents=True)
    assert [r.name for r in setup_workspace.missing(workspace.find(ws.root))] == ["docs"]
    assert setup_workspace.undeclared(workspace.find(ws.root)) == []
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(*((n, str(o)) for n, o in ws.origins.items()), ("docs", str(ws.origins["api"]))),
    )
    [docs] = setup_workspace.missing(workspace.find(ws.root))
    checked = setup_workspace.clone(procs.SubprocessRunner(), workspace.find(ws.root), docs)
    assert checked.outcome == "cloned"
    assert git("log", "--format=%s", cwd=docs.path) == "initial api"
    assert not staging(docs).exists()


def test_a_clone_is_not_moved_over_what_was_written_to_its_place_meanwhile(ws: Ws) -> None:
    docs = docs_repo(ws)

    def run(args: Sequence[str], **_: object) -> procs.Result:
        (Path(args[-1]) / ".git").mkdir(parents=True)
        docs.path.mkdir(parents=True)
        (docs.path / "notes.txt").write_text("the operator's")
        return procs.Result(tuple(args), 0, "", "")

    runner = mock.create_autospec(procs.SubprocessRunner, instance=True)
    runner.run.side_effect = run
    checked = setup_workspace.clone(runner, workspace.find(ws.root), docs)
    assert checked.outcome == "failed"
    assert checked.detail.startswith(f"the clone could not be moved to {docs.path}: ")
    assert sorted(p.name for p in docs.path.iterdir()) == ["notes.txt"]
    assert not staging(docs).exists()


def test_something_in_the_way_of_a_clone_is_left_as_it_was(ws: Ws) -> None:
    docs = docs_repo(ws)
    docs.path.mkdir(parents=True)
    (docs.path / "notes.txt").write_text("the operator's")
    runner = git_leaves_a_clone_behind(AssertionError("git ran"))
    checked = setup_workspace.clone(runner, workspace.find(ws.root), docs)
    assert checked.outcome == "failed"
    assert sorted(p.name for p in docs.path.iterdir()) == ["notes.txt"]
