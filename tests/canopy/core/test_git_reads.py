"""The reviewer's and the planner's read-only git tools, on a repository made here (DESIGN §27)."""

import json
from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

from canopy.core import git_reads
from canopy.infra import procs
from canopy.runtime import servers
from tests.canopy.helpers import History, history_repo
from tests.conftest import executable, git

RUNNER = procs.SubprocessRunner()


@pytest.fixture
def repo(tmp_path: Path) -> History:
    return history_repo(tmp_path / "repo")


def reading(*checkouts: tuple[str, Path]) -> dict[str, str]:
    """The environment of a run that may read `checkouts`, by name, as canopy sets it."""
    return {git_reads.CHECKOUTS_ENV: json.dumps({name: str(path) for name, path in checkouts})}


def one(repo: History) -> dict[str, str]:
    """The environment of a review's run, which reads its one checkout."""
    return reading(("checkout", repo.root))


def commit(repo: History, files: dict[str, bytes], message: str = "more") -> str:
    """Commit `files` on `feature`, and return the commit."""
    for name, data in files.items():
        (repo.root / name).write_bytes(data)
    git("add", ".", cwd=repo.root)
    git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", message, cwd=repo.root)
    return git("rev-parse", "HEAD", cwd=repo.root)


def test_merge_base_finds_where_a_branch_leaves_its_base(repo: History) -> None:
    request = git_reads.MergeBase(base="main", head="feature")
    assert git_reads.merge_base(RUNNER, request, one(repo)) == repo.first


def test_two_histories_that_never_meet_have_no_merge_base(repo: History) -> None:
    git("checkout", "--quiet", "--orphan", "other", cwd=repo.root)
    lone = commit(repo, {"LONE": b"lone\n"})
    with pytest.raises(git_reads.Refused, match=r"\(no_merge_base\): main and .* share no history"):
        git_reads.merge_base(RUNNER, git_reads.MergeBase(base="main", head=lone), one(repo))


def test_diff_is_between_two_commits_each_files_count_first(repo: History) -> None:
    said = git_reads.diff(RUNNER, git_reads.Diff(base=repo.first, head="feature"), one(repo))
    stat, _, patch = said.partition("\n\n")
    assert "src/app.py   | 2 +-" in stat
    assert "src/retry.py | 2 ++" in stat
    assert "2 files changed, 3 insertions(+), 1 deletion(-)" in stat
    assert "-print(1)\n+print(2)" in patch
    assert "+while True:\n+    call()" in patch
    # main's own change is not the branch's.
    assert "README.md" not in said


def test_diff_of_some_paths_holds_only_theirs(repo: History) -> None:
    request = git_reads.Diff(base=repo.first, head="feature", paths=("./src//retry.py",))
    said = git_reads.diff(RUNNER, request, one(repo))
    assert "src/retry.py" in said
    assert "src/app.py" not in said
    unchanged = git_reads.Diff(base=repo.first, head="feature", paths=("README.md",))
    assert git_reads.diff(RUNNER, unchanged, one(repo)) == f"No changes between {repo.first} and feature in README.md."


def test_log_lists_a_ranges_commits_newest_first(repo: History) -> None:
    said = git_reads.log(RUNNER, git_reads.Log(range="main..feature"), one(repo))
    assert said.startswith(f"commit {repo.feature}\nAuthor: ")
    assert "\n    retry forever" in said
    assert "first" not in said
    both = git_reads.log(RUNNER, git_reads.Log(range="main...feature"), one(repo))
    assert {"retry forever", "a second line"} <= {line.strip() for line in both.splitlines()}
    assert "    first" not in both


def test_log_takes_a_limit_and_paths(repo: History) -> None:
    said = git_reads.log(RUNNER, git_reads.Log(range="feature", limit=1), one(repo))
    assert said.count("\ncommit ") + said.startswith("commit ") == 1
    touching = git_reads.log(RUNNER, git_reads.Log(range="main", paths=("src",)), one(repo))
    assert "    first" in touching
    assert "a second line" not in touching
    assert git_reads.log(RUNNER, git_reads.Log(range="feature..main", paths=("src",)), one(repo)) == (
        "No commits in feature..main in src."
    )


def test_show_reads_a_file_at_a_commit_and_lists_a_directory(repo: History) -> None:
    assert git_reads.show(RUNNER, git_reads.Show(rev=repo.first, path="src/app.py"), one(repo)) == "print(1)"
    assert git_reads.show(RUNNER, git_reads.Show(rev="feature~0", path="src/app.py"), one(repo)) == "print(2)"
    assert git_reads.show(RUNNER, git_reads.Show(rev="feature", path="."), one(repo)) == "README.md\nsrc/"
    assert git_reads.show(RUNNER, git_reads.Show(rev="feature", path="src/"), one(repo)) == "app.py\nretry.py"
    with pytest.raises(git_reads.Refused, match=r"\(not_found\): src/retry.py is not in main"):
        git_reads.show(RUNNER, git_reads.Show(rev="main", path="src/retry.py"), one(repo))


def test_show_names_a_file_it_does_not_show(repo: History) -> None:
    commit(repo, {"blob.bin": b"\x00\x01\x02", "latin.txt": "caf\xe9\n".encode("latin-1")})
    said = git_reads.show(RUNNER, git_reads.Show(rev="feature", path="blob.bin"), one(repo))
    assert said == "blob.bin at feature is a binary file of 3 bytes: not shown."
    said = git_reads.show(RUNNER, git_reads.Show(rev="feature", path="latin.txt"), one(repo))
    assert said == "latin.txt at feature is 5 bytes and not UTF-8 text: not shown."
    with mock.patch.object(git_reads, "MAX_FILE_BYTES", 4):
        said = git_reads.show(RUNNER, git_reads.Show(rev="feature", path="README.md"), one(repo))
    assert said == "README.md at feature is 6 bytes, more than canopy shows (4): use diff."
    # A diff of a file that is not UTF-8 text fails nothing.
    diffed = git_reads.diff(RUNNER, git_reads.Diff(base="feature~1", head="feature"), one(repo))
    assert "+caf�" in diffed


def test_what_a_tool_returns_is_bounded_and_says_where_it_was_cut(repo: History) -> None:
    commit(repo, {"long.txt": "".join(f"line {n}\n" for n in range(50)).encode()})
    request = git_reads.Show(rev="feature", path="long.txt")
    with mock.patch.object(git_reads, "MAX_LINES", 3):
        said = git_reads.show(RUNNER, request, one(repo)).split("\n")
    assert said == ["line 0", "line 1", "line 2", git_reads.CUT_NOTE]
    with mock.patch.object(git_reads, "MAX_BYTES", 20):
        said = git_reads.diff(RUNNER, git_reads.Diff(base="feature~1", head="feature"), one(repo)).split("\n")
    # What git wrote is read only to the bound, and the line it cuts is dropped.
    assert said[-1] == git_reads.CUT_NOTE
    assert len("\n".join(said[:-1]).encode()) <= 20


def test_a_long_line_is_cut_and_a_hidden_character_named(repo: History) -> None:
    commit(repo, {"odd.txt": f"{'x' * 3000}\nevil{chr(0x202E)}right\ttabbed\r\n".encode()})
    said = git_reads.show(RUNNER, git_reads.Show(rev="feature", path="odd.txt"), one(repo)).split("\n")
    assert said[0] == f"{'x' * git_reads.MAX_LINE_CHARS} [line cut at {git_reads.MAX_LINE_CHARS} characters]"
    assert said[1] == "evil<U+202E>right\ttabbed"


@pytest.mark.parametrize(
    ("revision", "refused"),
    [
        ("-p", "starts with '-': a revision is never an option"),
        ("--output=/tmp/x", "starts with '-'"),
        ("main..feature", "is a range: give one revision"),
        ("HEAD@{1}", "is not a revision canopy takes"),
        ("HEAD:README.md", "is not a revision canopy takes"),
        (":/retry", "is not a revision canopy takes"),
        ("HEAD^{tree}", "is not a revision canopy takes"),
        ("main feature", "is not a revision canopy takes"),
        ("main\n", "is not a revision canopy takes"),
        ("", "is not a revision canopy takes"),
    ],
)
def test_a_revision_is_one_commits_name_and_nothing_else(revision: str, refused: str) -> None:
    for request, field in ((git_reads.MergeBase, "base"), (git_reads.Diff, "head"), (git_reads.Show, "rev")):
        arguments = {"base": "main", "head": "feature", "rev": "main", "path": "."}
        allowed = request.model_fields.keys()
        with pytest.raises(ValidationError, match=refused):
            request.model_validate({k: v for k, v in {**arguments, field: revision}.items() if k in allowed})


@pytest.mark.parametrize("taken", ["main", "main..feature", "main...feature", "HEAD~2", "v1.2^2", "origin/main"])
def test_a_log_takes_a_revision_or_a_range(taken: str) -> None:
    assert git_reads.Log(range=taken).range == taken


@pytest.mark.parametrize("refused", ["..feature", "main..", "a..b..c", "-n..main", "main....feature", "HEAD@{1}..x"])
def test_a_log_refuses_any_other_range(refused: str) -> None:
    with pytest.raises(ValidationError):
        git_reads.Log(range=refused)


@pytest.mark.parametrize(
    ("path", "refused"),
    [
        ("/etc/passwd", "is absolute"),
        ("../outside", "leaves the checkout"),
        ("src/../../outside", "leaves the checkout"),
        ("", "names no file"),
        ("./", "names no file"),
        ("src/\x1b[2J", "a hidden character in it"),
        ("x" * 5000, "too long"),
    ],
)
def test_a_path_stays_inside_the_checkout(path: str, refused: str) -> None:
    with pytest.raises(ValidationError, match=refused):
        git_reads.Diff(base="main", head="feature", paths=(path,))
    if path not in {"", "./"}:
        with pytest.raises(ValidationError, match=refused):
            git_reads.Show(rev="main", path=path)


def test_a_read_refuses_what_its_run_does_not_name(repo: History, tmp_path: Path) -> None:
    request = git_reads.Show(rev="feature", path=".")
    unset = r"\(no_checkouts\): CANOPY_GIT_CHECKOUTS is unset: these tools serve a review's or a plan's run alone"
    with pytest.raises(git_reads.Refused, match=unset):
        git_reads.show(RUNNER, request, {})
    for value in ("{", "{}", '{"checkout": "relative/path"}', '{"../up": "/tmp"}', '["/tmp"]'):
        with pytest.raises(git_reads.Refused, match=r"\(no_checkouts\)"):
            git_reads.show(RUNNER, request, {git_reads.CHECKOUTS_ENV: value})
    two = reading(("api", repo.root), ("web", tmp_path))
    with pytest.raises(git_reads.Refused, match=r"\(which_checkout\): name a checkout: this run reads api, web"):
        git_reads.show(RUNNER, request, two)
    with pytest.raises(git_reads.Refused, match=r"\(unknown_checkout\): no checkout 'ui': this run reads api, web"):
        git_reads.show(RUNNER, request.model_copy(update={"checkout": "ui"}), two)
    assert git_reads.show(RUNNER, request.model_copy(update={"checkout": "api"}), two) == "README.md\nsrc/"
    with pytest.raises(git_reads.Refused, match=r"\(unknown_revision\): nope names no commit in api"):
        git_reads.show(RUNNER, git_reads.Show(rev="nope", path=".", checkout="api"), two)
    # A checkout that is no repository is never read from a repository above it.
    inner = reading(("inner", repo.root / "src"))
    with pytest.raises(git_reads.Refused, match=r"\(unknown_revision\)"):
        git_reads.show(RUNNER, git_reads.Show(rev="HEAD", path=".", checkout="inner"), inner)
    gone = reading(("checkout", tmp_path / "gone"))
    with pytest.raises(git_reads.Refused, match=r"\(git_failed\): git rev-parse in checkout: cannot use"):
        git_reads.show(RUNNER, request, gone)


def plant(repo: History, tmp_path: Path) -> Path:
    """Set every program the repository's config and a commit's attributes could make git run, each recording that it
    ran in the file returned, and sign `feature`'s head, so a signature check would run one."""
    fired = tmp_path / "fired"

    def program(name: str) -> str:
        return str(executable(tmp_path / name, f'#!/bin/sh\necho {name} >> {fired}\ncat "$1" 2>/dev/null\n'))

    commit(repo, {".gitattributes": b"* diff=planted\n", "src/app.py": b"print(3)\n"}, "attributes")
    for key, name in (
        ("diff.external", "external"),
        ("diff.planted.command", "driver"),
        ("diff.planted.textconv", "textconv"),
        ("core.pager", "pager"),
        ("pager.log", "pager"),
        ("pager.diff", "pager"),
        ("core.fsmonitor", "fsmonitor"),
        ("gpg.program", "gpg"),
        ("core.hooksPath", "hooks"),
    ):
        git("config", key, program(name), cwd=repo.root)
    for key, value in (("log.showSignature", "true"), ("gpg.format", "openpgp")):
        git("config", key, value, cwd=repo.root)
    raw = git("cat-file", "commit", "HEAD", cwd=repo.root)
    head, _, message = raw.partition("\n\n")
    signature = " -----BEGIN PGP SIGNATURE-----\n \n iQ==\n -----END PGP SIGNATURE-----"
    signed = f"{head}\ngpgsig{signature}\n\n{message}\n"
    made = RUNNER.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"], cwd=repo.root, stdin=signed)
    git("update-ref", "refs/heads/feature", made.stdout.strip(), cwd=repo.root)
    return fired


def test_the_planted_programs_run_for_plain_git(repo: History, tmp_path: Path) -> None:
    """The control for the test below: git without the tools' flags runs them."""
    fired = plant(repo, tmp_path)
    git("diff", repo.first, "feature", cwd=repo.root)
    git("diff", "--no-ext-diff", repo.first, "feature", cwd=repo.root)
    git("log", "-1", "feature", cwd=repo.root)
    # The attribute's driver runs in place of diff.external, which the tools turn off as well.
    assert {"driver", "textconv", "gpg"} <= set(fired.read_text().split())


def test_the_tools_run_nothing_the_repository_or_a_commit_names(repo: History, tmp_path: Path) -> None:
    fired = plant(repo, tmp_path)
    env = one(repo)
    said = git_reads.diff(RUNNER, git_reads.Diff(base=repo.first, head="feature"), env)
    assert "-print(1)\n+print(3)" in said
    said = git_reads.log(RUNNER, git_reads.Log(range="feature", limit=1), env)
    assert "    attributes" in said
    assert "gpg" not in said
    assert git_reads.show(RUNNER, git_reads.Show(rev="feature", path="src/app.py"), env) == "print(3)"
    assert git_reads.merge_base(RUNNER, git_reads.MergeBase(base="main", head="feature"), env) == repo.first
    assert not fired.exists()


def test_git_inherits_no_variable_that_would_choose_its_repository_a_program_or_config() -> None:
    environ = {
        "GIT_DIR": "/elsewhere",
        "GIT_EXTERNAL_DIFF": "/bin/false",
        "GIT_CONFIG_PARAMETERS": "'diff.external'='/bin/false'",
        "GIT_TERMINAL_PROMPT": "1",
        "GIT_CEILING_DIRECTORIES": "/",
        "HOME": "/home/op",
    }
    assert git_reads.inherited(environ) == {"GIT_DIR", "GIT_EXTERNAL_DIFF", "GIT_CONFIG_PARAMETERS"}


def test_a_run_is_given_its_checkouts_and_the_server(tmp_path: Path) -> None:
    env = git_reads.run_env({"api": tmp_path / "api", "web": tmp_path / "web"}, cwd=tmp_path)
    assert json.loads(env[git_reads.CHECKOUTS_ENV]) == {"api": str(tmp_path / "api"), "web": str(tmp_path / "web")}
    given = servers.env(git_reads.SERVER, git_reads.SERVER_COMMAND, cwd=tmp_path)
    assert {name: env[name] for name in given} == given
    assert git_reads.tool_names() == ("canopy_git_merge-base", "canopy_git_diff", "canopy_git_log", "canopy_git_show")
