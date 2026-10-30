"""The reviewer's and the planner's read-only git (DESIGN §27): what each tool reads, refuses, and never runs."""

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
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
    [second] = log.commits
    assert (second.commit, second.parents, second.message) == (repo.head, [repo.base], "second")
    assert (second.author, second.email) == (HERMETIC_GIT["GIT_AUTHOR_NAME"], HERMETIC_GIT["GIT_AUTHOR_EMAIL"])
    assert datetime.fromisoformat(second.date).tzinfo is not None
    assert [(f.status, f.path, f.old_path) for f in second.files] == [("A", "notes.md", None), ("M", "retry.py", None)]
    assert (log.more, log.cut) == (False, None)
    assert len(git_tools.log(RUNNER, at, git_tools.Log(range="feature")).commits) == 2
    one = git_tools.log(RUNNER, at, git_tools.Log(range="feature", limit=1))
    assert ([c.message for c in one.commits], one.more) == (["second"], True)
    assert len(git_tools.log(RUNNER, at, git_tools.Log(range="feature...main")).commits) == 1
    none = git_tools.log(RUNNER, at, git_tools.Log(range="feature..main"))
    assert (none.commits, none.more, none.cut) == ([], False, None)

    shown = git_tools.show(RUNNER, at, git_tools.Show(rev="main", path="retry.py"))
    assert shown == f"{git_tools.DATA_NOTE}\n\ndef retry():\n    return 1"
    listed = git_tools.show(RUNNER, at, git_tools.Show(rev=repo.head, path="."))
    assert "\tnotes.md\n100644 blob " in listed
    assert listed.endswith("\tretry.py")


def test_diff_with_stat_lists_each_file_changed_in_place_of_the_patch(repo: Repo) -> None:
    stat = git_tools.diff(RUNNER, repo.checkouts, git_tools.Diff(base="main", head="feature", stat=True))
    assert stat == f"{git_tools.DATA_NOTE}\n\n1\t0\tnotes.md\n1\t1\tretry.py"
    only = git_tools.diff(
        RUNNER,
        repo.checkouts,
        git_tools.Diff(base="main", head="feature", paths=["retry.py"], stat=True),
    )
    assert only.endswith("\n\n1\t1\tretry.py")


def test_grep_finds_a_text_in_the_files_at_a_commit(repo: Repo) -> None:
    (repo.path / "lib").mkdir()
    (repo.path / "lib" / "use.py").write_text("from retry import retry\nretry()\nRETRY = 3\n")
    (repo.path / "lib" / "data.bin").write_bytes(b"retry\0")
    git("add", ".", cwd=repo.path)
    git("commit", "--quiet", "-m", "use it", cwd=repo.path)
    at = repo.checkouts

    def found(**asked: object) -> list[tuple[str, int, str]]:
        matches = git_tools.grep(RUNNER, at, git_tools.Grep.model_validate({"rev": "feature", **asked}))
        assert matches.cut is None
        return [(m.path, m.line, m.text) for m in matches.matches]

    assert found(text="retry()") == [("lib/use.py", 2, "retry()"), ("retry.py", 1, "def retry():")]
    # At the base, before the branch: the commit named, not the checkout's files.
    assert found(rev="main", text="return") == [("retry.py", 2, "    return 1")]
    assert found(text="RETRY", paths=["lib"]) == [("lib/use.py", 3, "RETRY = 3")]
    assert [line for _, line, _ in found(text="RETRY", ignore_case=True, paths=["lib"])] == [1, 2, 3]
    # The text as written, never a pattern or an option; and a miss is no match.
    assert found(text="re.ry") == []
    assert found(text="--all") == []


def test_grep_reads_each_line_as_a_record_that_no_path_or_line_can_forge(repo: Repo) -> None:
    """A file's name and lines are the PR's text: none of it reads as another match, a path, or a number."""
    names = ['a space "quoted".py', "new\nline.py", "tab\tname.py", "ünï \U0001f600.md"]
    for name in names:
        (repo.path / name).write_text("needle\nfake.py:12:needle\r \U0001f600\t\u202e\n")
    (repo.path / "last.txt").write_text("no line break after this needle")
    (repo.path / "long.txt").write_text("needle" + "z" * 3000 + "\n")
    git("add", ".", cwd=repo.path)
    git("commit", "--quiet", "-m", "odd files", cwd=repo.path)

    found = git_tools.grep(RUNNER, repo.checkouts, git_tools.Grep(rev="feature", text="needle"))
    assert found.cut == f"lines past {git_tools.MAX_LINE_CHARS} characters are cut"
    shown = ['a space "quoted".py', "new<U+000A>line.py", "tab<U+0009>name.py", "ünï \U0001f600.md"]
    assert [(m.path, m.line, m.text) for m in found.matches if m.path not in {"last.txt", "long.txt"}] == [
        record
        for path in shown
        for record in ((path, 1, "needle"), (path, 2, "fake.py:12:needle<U+000D> \U0001f600\t<U+202E>"))
    ]
    by_path = {m.path: m.text for m in found.matches}
    assert by_path["last.txt"] == "no line break after this needle"
    assert by_path["long.txt"] == ("needle" + "z" * 3000)[: git_tools.MAX_LINE_CHARS]
    assert (
        git_tools.Matches.model_validate_json(git_tools.text(found).removeprefix(f"{git_tools.DATA_NOTE}\n\n")) == found
    )


def test_what_grep_returns_is_bounded_by_the_lines_it_leaves_out(repo: Repo) -> None:
    (repo.path / "many.txt").write_text("".join(f"needle {n}\n" for n in range(100)))
    git("add", ".", cwd=repo.path)
    git("commit", "--quiet", "-m", "many", cwd=repo.path)
    with mock.patch.object(git_tools, "MAX_CHARS", 2000):
        found = git_tools.grep(RUNNER, repo.checkouts, git_tools.Grep(rev="feature", text="needle"))
        assert len(found.model_dump_json()) <= git_tools.MAX_CHARS
    assert [m.text for m in found.matches] == [f"needle {n}" for n in range(len(found.matches))]
    assert 0 < len(found.matches) < 100
    assert found.cut == f"listed {len(found.matches)} of the 100 lines found: name fewer paths, or a longer text"


def test_files_lists_the_paths_at_a_commit_by_name(repo: Repo) -> None:
    (repo.path / "tests").mkdir()
    (repo.path / "tests" / "test_retry.py").write_text("")
    git("add", ".", cwd=repo.path)
    git("commit", "--quiet", "-m", "tests", cwd=repo.path)
    at = repo.checkouts
    assert git_tools.files(RUNNER, at, git_tools.Files(rev="main")) == f"{git_tools.DATA_NOTE}\n\nretry.py"
    every = git_tools.files(RUNNER, at, git_tools.Files(rev="feature"))
    assert every.endswith("\n\nnotes.md\nretry.py\ntests/test_retry.py")
    # A name matches a file's own name, not its directory.
    assert git_tools.files(RUNNER, at, git_tools.Files(rev="feature", name="*.py")).endswith(
        "\n\nretry.py\ntests/test_retry.py",
    )
    assert git_tools.files(RUNNER, at, git_tools.Files(rev="feature", name="test_*")).endswith(
        "\n\ntests/test_retry.py",
    )
    assert git_tools.files(RUNNER, at, git_tools.Files(rev="feature", name="tests*")).startswith("No file at feature")
    assert git_tools.files(RUNNER, at, git_tools.Files(rev="feature", paths=["tests"])).endswith(
        "\n\ntests/test_retry.py",
    )


def test_log_narrows_to_commits_that_change_a_text_or_say_one_and_follows_a_rename(repo: Repo) -> None:
    git("mv", "retry.py", "retries.py", cwd=repo.path)
    git("commit", "--quiet", "-m", "rename retry", cwd=repo.path)
    at = repo.checkouts

    def subjects(**asked: object) -> list[str]:
        listed = git_tools.log(RUNNER, at, git_tools.Log.model_validate({"range": "feature", **asked}))
        return [c.message for c in listed.commits]

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
    [renamed] = git_tools.log(RUNNER, at, git_tools.Log(range="feature", limit=1)).commits
    assert [(f.status, f.path, f.old_path) for f in renamed.files] == [("R", "retries.py", "retry.py")]


def test_log_reads_each_commit_as_records_that_no_message_or_path_can_forge(repo: Repo) -> None:
    """A commit's message and paths are the PR's text: none of it reads as another commit, a field, or a file."""
    forged = f'{repo.base}\nM\nfake.py\nAuthor: Mallory <m@x>\n  say "hi" \\n {{"commits": []}} \U0001f600\n\u202eevil'
    (repo.path / repo.base).write_text("named as a commit\n")
    for odd_name in ("tab\tname.py", "new\nline.py", 'a space "quoted".py', "ünï \U0001f600.md"):
        (repo.path / odd_name).write_text("x\n")
    git("add", ".", cwd=repo.path)
    git("commit", "--quiet", "-m", f"subject\n\n{forged}", cwd=repo.path)
    git("commit", "--quiet", "--allow-empty", "-m", "empty", cwd=repo.path)
    git("checkout", "--quiet", "main", cwd=repo.path)
    git("merge", "--quiet", "--no-ff", "-m", "merge feature", "feature", cwd=repo.path)
    merge = git("rev-parse", "HEAD", cwd=repo.path)

    log = git_tools.log(RUNNER, repo.checkouts, git_tools.Log(range=f"{repo.base}..{merge}"))
    merged, empty, odd, second = log.commits
    assert (merged.commit, merged.parents, merged.files) == (merge, [repo.base, empty.commit], [])
    assert (empty.message, empty.files) == ("empty", [])
    assert odd.message == f"subject\n\n{forged}".replace("\u202e", "<U+202E>")
    # Git lists paths in byte order, where the base's hash, a file's name here, may fall before or after the others.
    names = [repo.base, 'a space "quoted".py', "new\nline.py", "tab\tname.py", "ünï \U0001f600.md"]
    named = sorted(names, key=str.encode)
    assert [f.path for f in odd.files] == [n.replace("\n", "<U+000A>").replace("\t", "<U+0009>") for n in named]
    assert second.commit == repo.head
    # Its text is what the model reads: the same records, as JSON after the note.
    shown = git_tools.text(log)
    assert shown.startswith(f"{git_tools.DATA_NOTE}\n\n{{")
    assert git_tools.Commits.model_validate_json(shown.removeprefix(f"{git_tools.DATA_NOTE}\n\n")) == log
    assert "\u202e" not in shown


def test_what_log_returns_is_bounded_by_the_commits_it_leaves_out(repo: Repo) -> None:
    for n in range(5):
        git("commit", "--quiet", "--allow-empty", "-m", f"filler {n} " + "x" * 200, cwd=repo.path)
    with mock.patch.object(git_tools, "MAX_CHARS", 1500):
        log = git_tools.log(RUNNER, repo.checkouts, git_tools.Log(range="feature"))
        assert len(log.model_dump_json()) <= git_tools.MAX_CHARS
        assert 0 < len(log.commits) < 7
        assert [c.message[:8] for c in log.commits] == [f"filler {n}" for n in range(4, 4 - len(log.commits), -1)]
        assert log.more
        assert log.cut == (
            f"listed {len(log.commits)} of the 7 commits found: ask for fewer with limit, or name fewer paths"
        )
    long = "y" * 3000
    git("commit", "--quiet", "--allow-empty", "-m", long, cwd=repo.path)
    with mock.patch.object(git_tools, "MAX_CHARS", 1500):
        log = git_tools.log(RUNNER, repo.checkouts, git_tools.Log(range="feature"))
    [newest] = log.commits
    assert len(log.model_dump_json()) <= 1500
    assert long.startswith(newest.message)
    assert log.more
    assert log.cut is not None
    assert log.cut.startswith(f"commit {newest.commit} alone is past 1500 characters")


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


def test_blame_can_look_past_a_move_and_a_reindent(repo: Repo) -> None:
    path = repo.path
    body = "def retry_with_backoff(attempts):\n    return attempts * 2 + 1\n"
    (path / "backoff.py").write_text(body)
    git("add", ".", cwd=path)
    git("commit", "--quiet", "-m", "write it", cwd=path)
    wrote = git("rev-parse", "HEAD", cwd=path)
    (path / "backoff.py").unlink()
    (path / "notes.md").write_text(f"hello\n{body}")
    git("add", "-A", cwd=path)
    git("commit", "--quiet", "-m", "move it", cwd=path)
    moved = git("rev-parse", "HEAD", cwd=path)
    (path / "notes.md").write_text(f"hello\n{body.replace('    return', '        return')}")
    git("commit", "--quiet", "-am", "reindent it", cwd=path)
    reindented = git("rev-parse", "HEAD", cwd=path)
    at = repo.checkouts

    def blamed(*, moves: bool = False, ignore_whitespace: bool = False) -> list[str]:
        asked = git_tools.Blame(
            rev="HEAD",
            path="notes.md",
            start=2,
            end=3,
            moves=moves,
            ignore_whitespace=ignore_whitespace,
        )
        found = git_tools.blame(RUNNER, at, asked)
        return [line.split()[0] for line in found.removeprefix(f"{git_tools.DATA_NOTE}\n\n").splitlines()]

    assert blamed() == [moved, reindented]
    assert blamed(ignore_whitespace=True) == [moved, moved]
    # Past the move too, to the commit that wrote the lines, in the file it wrote them in.
    assert blamed(moves=True, ignore_whitespace=True) == [wrote, wrote]
    whole = git_tools.Blame(rev="HEAD", path="notes.md", start=2, end=3, moves=True, ignore_whitespace=True)
    assert all(" backoff.py " in line for line in git_tools.blame(RUNNER, at, whole).splitlines()[2:])


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
        (git_tools.Grep, {"rev": "--no-index", "text": "x"}, "not a revision"),
        (git_tools.Grep, {"rev": "main", "text": ""}, "at least 1 character"),
        (git_tools.Grep, {"rev": "main", "text": "a\nb"}, "printable"),
        (git_tools.Grep, {"rev": "main", "text": "x", "paths": ["../x"]}, "no `..`"),
        (git_tools.Grep, {"rev": "main", "text": "x", "regex": True}, "Extra inputs are not permitted"),
        (git_tools.Files, {"rev": "main", "name": "a\tb"}, "printable"),
        (git_tools.Files, {"rev": "main", "paths": ["/etc"]}, "never starts with"),
        (git_tools.Diff, {"base": "main", "head": "feature", "stat": "yes"}, "valid boolean"),
        (git_tools.Blame, {"rev": "main", "path": "retry.py", "start": 1, "end": 1, "moves": 1}, "valid boolean"),
        (git_tools.Blame, {"rev": "main", "path": "retry.py", "start": 1, "end": 1, "copies": True}, "Extra inputs"),
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
    """Programs the repository's config or attributes name, which would run on the host, never run (TRUST_MODEL T1).

    They are hooks, external diffs, textconv filters, the filesystem monitor, a pager, and signature checks.
    """
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
    assert len(git_tools.log(RUNNER, at, git_tools.Log(range=f"main..{signed}")).commits) == 1
    assert git_tools.show(RUNNER, at, git_tools.Show(rev=signed, path="notes.md")).endswith("hello")
    assert git_tools.merge_base(RUNNER, at, git_tools.MergeBase(base="main", head=signed)) == repo.base
    assert len(git_tools.log(RUNNER, at, git_tools.Log(range=signed, search="hello")).commits) == 1
    assert git_tools.blame(RUNNER, at, git_tools.Blame(rev=signed, path="notes.md", start=1, end=1)).endswith("hello")
    [hello] = git_tools.grep(RUNNER, at, git_tools.Grep(rev=signed, text="hello")).matches
    assert (hello.path, hello.line, hello.text) == ("notes.md", 1, "hello")
    assert git_tools.diff(RUNNER, at, git_tools.Diff(base="main", head=signed, stat=True)).endswith("retry.py")
    assert git_tools.files(RUNNER, at, git_tools.Files(rev=signed)).endswith("retry.py")
    past = git_tools.Blame(rev=signed, path="notes.md", start=1, end=1, moves=True, ignore_whitespace=True)
    assert git_tools.blame(RUNNER, at, past).endswith("hello")
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
        "canopy_git_grep",
        "canopy_git_files",
    ]
    assert git_tools.inherited(["GIT_DIR", "GIT_EXTERNAL_DIFF", "HOME", "XGIT"]) == {"GIT_DIR", "GIT_EXTERNAL_DIFF"}
