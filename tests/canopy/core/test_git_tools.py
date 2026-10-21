"""The reviewer's and the planner's read-only git (DESIGN §27): what each tool reads, refuses, and never runs."""

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest
from pydantic import BaseModel, ValidationError

from canopy.core import git_tools
from canopy.infra import procs
from tests.conftest import HERMETIC_GIT, executable, git

RUNNER = procs.SubprocessRunner()


@dataclass(frozen=True)
class Repo:
    """A repository of two commits: `main`'s, and `feature`'s on top of it, which changes `retry.py` and adds a note."""

    path: Path
    base: str
    head: str

    @property
    def checkouts(self) -> Mapping[str, Path]:
        """The run's one checkout, as the reviewer's is named."""
        return {"checkout": self.path}


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[Repo]:
    with mock.patch.dict(os.environ, HERMETIC_GIT):
        path = tmp_path / "repo"
        path.mkdir()
        git("init", "--quiet", "--initial-branch=main", cwd=path)
        (path / "retry.py").write_text("def retry():\n    return 1\n")
        git("add", ".", cwd=path)
        git("commit", "--quiet", "-m", "first", cwd=path)
        git("checkout", "--quiet", "-b", "feature", cwd=path)
        (path / "retry.py").write_text("def retry():\n    return 2\n")
        (path / "notes.md").write_text("hello\n")
        git("add", ".", cwd=path)
        git("commit", "--quiet", "-m", "second", cwd=path)
        yield Repo(path, git("rev-parse", "main", cwd=path), git("rev-parse", "feature", cwd=path))


def test_each_tool_reads_the_checkouts_history(repo: Repo) -> None:
    at = repo.checkouts
    assert git_tools.merge_base(RUNNER, at, git_tools.MergeBase(base="main", head="feature")) == repo.base

    diff = git_tools.diff(RUNNER, at, git_tools.Diff(base="main", head="feature"))
    assert diff.startswith(f"{git_tools.DATA_NOTE}\n\ndiff --git a/notes.md b/notes.md\n")
    assert "-    return 1\n+    return 2" in diff
    only = git_tools.diff(RUNNER, at, git_tools.Diff(base="main", head="feature", paths=["./notes.md"]))
    assert "notes.md" in only
    assert "retry.py" not in only
    assert git_tools.diff(RUNNER, at, git_tools.Diff(base="main", head="main")).startswith("No difference between")

    log = git_tools.log(RUNNER, at, git_tools.Log(range="main..feature"))
    assert f"commit {repo.head}\n" in log
    assert "    second\n" in log
    assert "M\tretry.py" in log
    assert "A\tnotes.md" in log
    assert "first" not in log
    assert git_tools.log(RUNNER, at, git_tools.Log(range="feature")).count("\ncommit ") == 2
    assert git_tools.log(RUNNER, at, git_tools.Log(range="feature", limit=1)).count("\ncommit ") == 1
    assert git_tools.log(RUNNER, at, git_tools.Log(range="feature...main")).count("commit ") == 1
    assert git_tools.log(RUNNER, at, git_tools.Log(range="feature..main")) == "No commits in that range."

    shown = git_tools.show(RUNNER, at, git_tools.Show(rev="main", path="retry.py"))
    assert shown == f"{git_tools.DATA_NOTE}\n\ndef retry():\n    return 1"
    listed = git_tools.show(RUNNER, at, git_tools.Show(rev=repo.head, path="."))
    assert "\tnotes.md\n100644 blob " in listed
    assert listed.endswith("\tretry.py")


def test_log_narrows_to_commits_that_change_a_text_or_say_one_and_follows_a_rename(repo: Repo) -> None:
    git("mv", "retry.py", "retries.py", cwd=repo.path)
    git("commit", "--quiet", "-m", "rename retry", cwd=repo.path)
    at = repo.checkouts

    def subjects(**asked: object) -> list[str]:
        listed = git_tools.log(RUNNER, at, git_tools.Log.model_validate({"range": "feature", **asked}))
        return [line.strip() for line in listed.splitlines() if line.startswith("    ")]

    assert subjects(search="return 2") == ["second"]
    assert subjects(search="return 1") == ["second", "first"]
    assert subjects(message="rename") == ["rename retry"]
    assert subjects(message="ren.me") == []  # the text as written, never a pattern
    assert subjects(search="return 2", message="first") == []
    # Text that looks like an option is searched for, never read as one.
    assert subjects(search="--all") == []
    assert subjects(message="--all") == []
    assert subjects(paths=["retries.py"]) == ["rename retry"]
    assert subjects(paths=["retries.py"], follow=True) == ["rename retry", "second", "first"]


def test_blame_names_the_commit_that_last_changed_each_line(repo: Repo) -> None:
    (repo.path / "retry.py").write_text("def retry():\n    return 2\n# done\n")
    git("commit", "--quiet", "-am", "third", cwd=repo.path)
    third = git("rev-parse", "HEAD", cwd=repo.path)
    at = repo.checkouts
    blamed = git_tools.blame(RUNNER, at, git_tools.Blame(rev="feature", path="./retry.py", start=1, end=3))
    first, second, last = blamed.removeprefix(f"{git_tools.DATA_NOTE}\n\n").splitlines()
    # Each line after its commit's full id: the first commit's too, never marked as a boundary.
    assert first.startswith(f"{repo.base} (canopy test ")
    assert first.endswith(" 1) def retry():")
    assert second.startswith(f"{repo.head} ")
    assert second.endswith(" 2)     return 2")
    assert last.startswith(f"{third} ")
    one = git_tools.blame(RUNNER, at, git_tools.Blame(rev="main", path="retry.py", start=2, end=2))
    assert one.endswith(" 2)     return 1")
    assert one.count("\n") == 2


def test_what_a_tool_returns_is_bounded(repo: Repo) -> None:
    big = repo.path / "big.txt"
    big.write_text("".join(f"line {n}\n" for n in range(1000)))
    git("add", "big.txt", cwd=repo.path)
    git("commit", "--quiet", "-m", "big", cwd=repo.path)
    with mock.patch.object(git_tools, "MAX_CHARS", 300):
        cut = git_tools.diff(RUNNER, repo.checkouts, git_tools.Diff(base="main", head="feature"))
    body, _, note = cut.rpartition("\n")
    assert len(body) <= 300 + len(git_tools.DATA_NOTE) + 2
    assert body.endswith("\n")  # cut at a line's end
    assert note == "[cut at 300 characters: name fewer paths, or a narrower range]"
    with mock.patch.object(git_tools, "MAX_FILE_BYTES", 100), pytest.raises(git_tools.Refused) as refused:
        git_tools.show(RUNNER, repo.checkouts, git_tools.Show(rev="feature", path="big.txt"))
    assert str(refused.value) == f"big.txt is {big.stat().st_size} bytes, past the 100 this tool reads"


def test_a_file_that_is_not_text_is_refused_and_a_hidden_character_is_named(repo: Repo) -> None:
    (repo.path / "zero.bin").write_bytes(b"a\0b")
    (repo.path / "latin.txt").write_bytes(b"caf\xe9\n")
    (repo.path / "bidi.py").write_text("x = 1  # \u202eevil\n")
    git("add", ".", cwd=repo.path)
    git("commit", "--quiet", "-m", "odd files", cwd=repo.path)
    for path, refusal in [
        ("zero.bin", "zero.bin is binary, not text"),
        ("latin.txt", "git cat-file printed what is not UTF-8 text: name fewer paths, or another file"),
    ]:
        with pytest.raises(git_tools.Refused) as refused:
            git_tools.show(RUNNER, repo.checkouts, git_tools.Show(rev="feature", path=path))
        assert str(refused.value) == refusal
    shown = git_tools.show(RUNNER, repo.checkouts, git_tools.Show(rev="feature", path="bidi.py"))
    assert shown.endswith("x = 1  # <U+202E>evil")


@pytest.mark.parametrize(
    ("request_type", "arguments", "problem"),
    [
        (git_tools.MergeBase, {"base": "--output=/tmp/x", "head": "HEAD"}, "not a revision"),
        (git_tools.MergeBase, {"base": "main", "head": "-p"}, "not a revision"),
        (git_tools.Diff, {"base": "main", "head": "feature", "paths": ["../secret"]}, "no `..`"),
        (git_tools.Diff, {"base": "main", "head": "feature", "paths": ["a/../../b"]}, "no `..`"),
        (git_tools.Diff, {"base": "main", "head": "feature", "paths": ["/etc/passwd"]}, "never starts with"),
        (git_tools.Diff, {"base": "main", "head": "feature", "paths": ["--output=x"]}, "never starts with"),
        (git_tools.Diff, {"base": "main", "head": "feature", "paths": ["a\nb"]}, "printable"),
        (git_tools.Diff, {"base": "main", "head": "feature", "paths": ["a"] * 21}, "at most 20 items"),
        (git_tools.Diff, {"base": "main..feature", "head": "feature"}, "not a revision"),
        (git_tools.Show, {"rev": "HEAD:retry.py", "path": "retry.py"}, "not a revision"),
        (git_tools.Show, {"rev": "main feature", "path": "retry.py"}, "not a revision"),
        (git_tools.Show, {"rev": "main", "path": "../../etc/passwd"}, "no `..`"),
        (git_tools.Log, {"range": "--all"}, "not a revision"),
        (git_tools.Log, {"range": "main..--all"}, "not a revision"),
        (git_tools.Log, {"range": "main....feature"}, "not a revision"),
        (git_tools.Log, {"range": "main.."}, "not a revision"),
        (git_tools.Log, {"range": "main", "limit": 0}, "greater than or equal to 1"),
        (git_tools.Log, {"range": "main", "limit": git_tools.MAX_LIMIT + 1}, "less than or equal to 100"),
        (git_tools.Log, {"range": "main", "all": True}, "Extra inputs are not permitted"),
        (git_tools.Log, {"range": "main", "search": ""}, "at least 1 character"),
        (git_tools.Log, {"range": "main", "search": "a\nb"}, "printable"),
        (git_tools.Log, {"range": "main", "message": "a\tb"}, "printable"),
        (git_tools.Log, {"range": "main", "search": "a" * 201}, "at most 200 characters"),
        (git_tools.Log, {"range": "main", "follow": True}, "name exactly one in paths"),
        (git_tools.Log, {"range": "main", "follow": True, "paths": ["a", "b"]}, "name exactly one in paths"),
        (git_tools.Blame, {"rev": "main", "path": "retry.py", "start": 0, "end": 1}, "greater than or equal to 1"),
        (git_tools.Blame, {"rev": "main", "path": "retry.py", "start": 2, "end": 1}, "at or after start"),
        (git_tools.Blame, {"rev": "main", "path": "retry.py", "start": 1, "end": 401}, "at most 400 lines"),
        (git_tools.Blame, {"rev": "main", "path": "../x", "start": 1, "end": 1}, "no `..`"),
        (git_tools.Blame, {"rev": "-L1,2", "path": "retry.py", "start": 1, "end": 1}, "not a revision"),
    ],
)
def test_an_argument_that_is_an_option_leaves_the_checkout_or_is_no_revision_is_refused(
    request_type: type[BaseModel],
    arguments: Mapping[str, object],
    problem: str,
) -> None:
    with pytest.raises(ValidationError) as refused:
        request_type.model_validate(arguments)
    assert problem in str(refused.value)


def test_what_names_nothing_here_is_refused(repo: Repo) -> None:
    blob = git("rev-parse", "main:retry.py", cwd=repo.path)
    at = repo.checkouts
    for read, refusal in [
        (lambda: git_tools.merge_base(RUNNER, at, git_tools.MergeBase(base="nope", head="main")), "nope names no"),
        (lambda: git_tools.diff(RUNNER, at, git_tools.Diff(base="main", head=blob)), f"{blob} names no commit"),
        (lambda: git_tools.log(RUNNER, at, git_tools.Log(range="main..nope")), "nope names no commit"),
        (lambda: git_tools.show(RUNNER, at, git_tools.Show(rev="main", path="notes.md")), "notes.md is not in main"),
        (lambda: git_tools.diff(RUNNER, at, git_tools.Diff(base="main", head="main", paths=["."])), "whole repo"),
        (
            lambda: git_tools.blame(RUNNER, at, git_tools.Blame(rev="main", path="notes.md", start=1, end=1)),
            "no such path notes.md in",
        ),
        (
            lambda: git_tools.blame(RUNNER, at, git_tools.Blame(rev="main", path="retry.py", start=3, end=4)),
            "file retry.py has only 2 lines",
        ),
        (
            lambda: git_tools.blame(RUNNER, at, git_tools.Blame(rev="main", path=".", start=1, end=1)),
            "blame reads a file",
        ),
        (
            lambda: git_tools.show(RUNNER, at, git_tools.Show(rev="main", path="retry.py", repo="web")),
            "no repository named 'web' here: this run reads checkout",
        ),
    ]:
        with pytest.raises(git_tools.Refused) as refused:
            read()
        assert refusal in str(refused.value)


def test_a_run_of_several_checkouts_names_the_one_it_reads(repo: Repo) -> None:
    other = repo.path / "web"
    other.mkdir()
    checkouts = {"api": repo.path, "web": other}
    with pytest.raises(git_tools.Refused) as refused:
        git_tools.show(RUNNER, checkouts, git_tools.Show(rev="main", path="retry.py"))
    assert str(refused.value) == "name the repository to read with repo: one of api, web"
    shown = git_tools.show(RUNNER, checkouts, git_tools.Show(rev="main", path="retry.py", repo="api"))
    assert shown.endswith("return 1")
    # A checkout that is no repository reads none above it, here the one it sits in.
    with pytest.raises(git_tools.Refused) as refused:
        git_tools.show(RUNNER, {"web": other}, git_tools.Show(rev="main", path="retry.py"))
    assert str(refused.value) == "main names no commit in this repository"


def test_nothing_the_repository_names_runs(repo: Repo, tmp_path: Path) -> None:
    """Hooks, external diffs, textconv filters, the filesystem monitor, a pager, and signature checks the repository's
    config or attributes name, each a program that would run on the host, never run (TRUST_MODEL T1)."""
    marker = tmp_path / "ran"

    def program(name: str) -> str:
        # A textconv filter prints the file it is given, so a diff through one still reads.
        return str(executable(tmp_path / name, f'#!/bin/sh\necho {name} >> "{marker}"\ncat "$1" 2>/dev/null\n'))

    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for hook in ("reference-transaction", "post-index-change", "post-checkout"):
        executable(hooks / hook, f'#!/bin/sh\necho hook >> "{marker}"\n')
    path = repo.path
    settings = {
        "diff.external": program("external"),
        "diff.ext.command": program("command"),
        "diff.conv.textconv": program("textconv"),
        "core.fsmonitor": program("fsmonitor"),
        "core.pager": program("pager"),
        "pager.log": program("pager"),
        "core.hooksPath": str(hooks),
        "log.showSignature": "true",
        "gpg.program": program("gpg"),
        "blame.ignoreRevsFile": str(tmp_path / "ignored"),
    }
    for key, value in settings.items():
        git("config", key, value, cwd=path)
    (path / ".gitattributes").write_text("*.py diff=ext\n*.md diff=conv\n")
    signed = _signed(path, "feature")
    marker.unlink(missing_ok=True)

    at = repo.checkouts
    diff = git_tools.diff(RUNNER, at, git_tools.Diff(base="main", head=signed))
    assert "+    return 2" in diff
    assert "+hello" in diff
    assert git_tools.log(RUNNER, at, git_tools.Log(range=f"main..{signed}")).count("commit ") == 1
    assert git_tools.show(RUNNER, at, git_tools.Show(rev=signed, path="notes.md")).endswith("hello")
    assert git_tools.merge_base(RUNNER, at, git_tools.MergeBase(base="main", head=signed)) == repo.base
    assert git_tools.log(RUNNER, at, git_tools.Log(range=signed, search="hello")).count("commit ") == 1
    assert git_tools.blame(RUNNER, at, git_tools.Blame(rev=signed, path="notes.md", start=1, end=1)).endswith("hello")
    assert not marker.exists(), marker.read_text()

    # The same reads by plain git run what the repository names: the test above would have seen them.
    git("diff", "main", signed, cwd=path)
    git("diff", "--no-ext-diff", "main", signed, cwd=path)
    git("log", "-1", signed, cwd=path)
    git("blame", "--no-ignore-revs-file", signed, "--", "notes.md", cwd=path)
    # And plain blame reads the file of revisions to skip the config names, here none.
    assert "could not open object name list" in RUNNER.run(["git", "blame", signed, "--", "notes.md"], cwd=path).stderr
    assert set(marker.read_text().split()) >= {"external", "command", "textconv", "gpg"}


def _signed(path: Path, branch: str) -> str:
    """Make `branch`'s commit again with a signature, so a log that checks signatures would run `gpg.program`.

    Returns:
        The new commit's id.
    """
    headers, _, message = git("cat-file", "commit", branch, cwd=path).partition("\n\n")
    signature = "gpgsig -----BEGIN PGP SIGNATURE-----\n \n iQEz\n -----END PGP SIGNATURE-----"
    text = f"{headers}\n{signature}\n\n{message}\n"
    done = RUNNER.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"], cwd=path, stdin=text)
    assert done.ok, done.stderr
    return done.stdout.strip()


def test_a_checkout_on_the_command_line_is_a_name_and_an_absolute_path() -> None:
    assert git_tools.parse_checkout("checkout=/a/b=c") == ("checkout", Path("/a/b=c"))
    for value in ("checkout", "Checkout=/a", "checkout=a/b", "=/a"):
        with pytest.raises(ValueError, match=r"checkout|NAME=PATH"):
            git_tools.parse_checkout(value)


def test_the_tools_are_named_as_the_definitions_name_them() -> None:
    assert git_tools.tool_names() == [
        "canopy_git_merge-base",
        "canopy_git_diff",
        "canopy_git_log",
        "canopy_git_show",
        "canopy_git_blame",
    ]
    assert git_tools.inherited(["GIT_DIR", "GIT_EXTERNAL_DIFF", "HOME", "XGIT"]) == {"GIT_DIR", "GIT_EXTERNAL_DIFF"}
