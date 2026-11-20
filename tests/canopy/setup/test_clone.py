"""`canopy workspace sync` clones a missing repository beside its place, from a seed if named, then moves it in."""

from collections.abc import Sequence
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
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


def test_a_seeded_clone_takes_the_seeds_objects_and_does_not_depend_on_it(ws: Ws) -> None:
    runner = mock.create_autospec(procs.SubprocessRunner, instance=True)
    runner.run.side_effect = procs.SubprocessRunner().run
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(*((n, str(o)) for n, o in ws.origins.items()), ("docs", str(ws.origins["api"]))),
    )
    [docs] = setup_workspace.missing(workspace.find(ws.root))
    checked = setup_workspace.clone(runner, workspace.find(ws.root), docs, seed=ws.clone("api"))
    assert checked.outcome == "cloned"
    [call] = runner.run.call_args_list
    assert call.args[0][-6:-3] == ["--reference-if-able", str(ws.clone("api")), "--dissociate"]
    assert git("log", "--format=%s", cwd=docs.path) == git("log", "--format=%s", cwd=ws.clone("api"))
    assert not (docs.path / ".git" / "objects" / "info" / "alternates").exists()


def test_a_seed_git_cannot_use_is_passed_over(ws: Ws, tmp_path: Path) -> None:
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(*((n, str(o)) for n, o in ws.origins.items()), ("docs", str(ws.origins["api"]))),
    )
    [docs] = setup_workspace.missing(workspace.find(ws.root))
    empty = tmp_path / "not-a-clone"
    empty.mkdir()
    checked = setup_workspace.clone(procs.SubprocessRunner(), workspace.find(ws.root), docs, seed=empty)
    assert checked.outcome == "cloned"
    assert git("log", "--format=%s", cwd=docs.path) == "initial api"


def test_sync_seeds_the_clone_it_names_and_says_so(ws: Ws, capsys: pytest.CaptureFixture[str]) -> None:
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(*((n, str(o)) for n, o in ws.origins.items()), ("docs", str(ws.origins["api"]))),
    )
    seed = ws.clone("api")
    assert main(["workspace", "sync", "--dry-run", "--seed", f"docs={seed}"]) == 0
    assert (
        f"docs: to clone: {ws.origins['api']} into {ws.clone('docs')}, seeded from {seed}\n" in capsys.readouterr().out
    )
    assert main(["workspace", "sync", "--seed", f"docs={seed}", "--seed", f"api={seed}"]) == 0
    out = capsys.readouterr().out
    assert f"docs: cloning {ws.origins['api']} into {ws.clone('docs')}, seeded from {seed}\ndocs: cloned\n" in out
    assert "api: --seed not used: it is cloned already\n" in out


@pytest.mark.parametrize(
    ("seed", "said"),
    [
        ("docs", "--seed 'docs' is not NAME=PATH"),
        ("=/tmp", "--seed '=/tmp' is not NAME=PATH"),
        ("nowhere={here}", "--seed names nowhere, which the map does not list"),
        ("api={missing}", "--seed api: {missing} is not a directory"),
    ],
)
def test_sync_refuses_a_seed_it_cannot_use_before_it_changes_anything(
    ws: Ws,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    seed: str,
    said: str,
) -> None:
    missing = tmp_path / "missing"
    fill = {"here": str(ws.clone("api")), "missing": str(missing)}
    assert main(["workspace", "sync", "--seed", seed.format(**fill)]) == 1
    assert f"sync: {said.format(**fill)}" in capsys.readouterr().err
