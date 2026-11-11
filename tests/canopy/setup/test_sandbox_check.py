"""`canopy sandbox check`: a script through the real wrapper, in a worktree made for it (docs/SANDBOX.md).

The fake `srt` sandboxes nothing, so under it every denial is let through and the controls pass: what the check must
say of a sandbox that does not hold. That it passes where one holds is the canary's to show, under the real `srt`
(`tests/canopy_sandbox/test_sandbox_canary.py`).
"""

import contextlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import canopy_sandbox
import pytest

from canopy.cli.main import main
from canopy.infra.procs import SubprocessRunner
from canopy.setup import sandbox_check
from tests.conftest import HERMETIC_GIT, CanopyEnv, executable, git

# Plays curl under srt's proxy: for the host the check expects refused it fails, and says the proxy answered 403 when
# asked how the CONNECT went ($FAKE_CURL_CONNECT says otherwise, as for a host that is down); it answers any other.
CURL = """\
#!{python}
import os, sys
if sys.argv[-1] != "https://example.com":
    sys.exit(0)
if "-w" in sys.argv:
    sys.stdout.write(os.environ.get("FAKE_CURL_CONNECT", "403"))
sys.exit(56)
"""


@pytest.fixture
def primary(canopy_env: CanopyEnv, fakes_on_path: Path) -> Iterator[Path]:
    """The workspace's primary clone with a commit, the shipped templates, the fake srt, and a short temp directory."""
    assert fakes_on_path.is_dir()
    templates = canopy_env.home / ".config" / "canopy" / "sandbox"
    templates.mkdir(parents=True)
    for role in canopy_sandbox.ROLES:
        shutil.copy(canopy_sandbox.TEMPLATES / f"{role}.json", templates)
    variables = {"XDG_CACHE_HOME": str(canopy_env.home / ".cache"), **HERMETIC_GIT}
    with (
        # Under /tmp: the wrapper refuses a temp directory too deep for the sockets srt would make in it.
        tempfile.TemporaryDirectory(prefix="check.", dir="/tmp") as tmp,
        mock.patch.dict(os.environ, {**variables, "TMPDIR": tmp}),
    ):
        git("init", "--quiet", "--initial-branch=main", cwd=canopy_env.repo)
        git("commit", "--quiet", "--allow-empty", "-m", "initial", cwd=canopy_env.repo)
        yield canopy_env.repo


@contextlib.contextmanager
def curl_on_path(tmp_path: Path) -> Iterator[None]:
    """Put the curl that plays srt's proxy first on PATH."""
    (tmp_path / "bin").mkdir()
    executable(tmp_path / "bin" / "curl", CURL.format(python=sys.executable))
    with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(tmp_path / "bin"), os.environ["PATH"]])}):
        yield


def left_behind(canopy_env: CanopyEnv) -> list[str]:
    """What the check left on the host: its files in HOME and the git directory, its branch, and its worktree."""
    names = [p.name for place in (canopy_env.home, canopy_env.repo / ".git") for p in place.iterdir()]
    refs = git("for-each-ref", "--format=%(refname)", cwd=canopy_env.repo).splitlines()
    worktrees = git("worktree", "list", "--porcelain", cwd=canopy_env.repo).count("worktree ") - 1
    return [n for n in (*names, *refs) if sandbox_check.PREFIX in n] + ["a worktree"] * worktrees


def test_a_sandbox_that_refuses_nothing_fails_every_denial_and_leaves_nothing_behind(
    canopy_env: CanopyEnv,
    primary: Path,
) -> None:
    report = sandbox_check.run_check(SubprocessRunner(), primary, network=False)

    assert report.error == ""
    assert not report.ok
    assert [(a.name, a.allowed) for a in report.attempts if not a.expected] == [
        ("read a file in your home directory", True),
        ("read canopy's config, config.toml", True),
        ("write a file in your home directory", True),
        ("write beside the repository's hooks and git config", True),
        ("make a branch, in the refs every slot shares", True),
    ]
    assert [(a.name, a.ok) for a in report.attempts if a.expected] == [
        ("commit in the worktree, its objects in the run's own directory", True),
    ]
    assert report.skipped == ("the network was not checked, as asked.",)
    assert report.left == ()
    assert left_behind(canopy_env) == []


def test_a_write_that_never_reached_the_host_is_refused_whatever_the_script_said(
    canopy_env: CanopyEnv,
    primary: Path,
) -> None:
    """Under a denied directory srt takes a write in a tmpfs and drops it: played by a script that writes elsewhere."""
    elsewhere = canopy_env.home / "elsewhere"
    elsewhere.mkdir()
    real_run = SubprocessRunner.run

    def run(self: SubprocessRunner, args: list[str], **kwargs: object) -> object:
        if Path(args[0]).name == "canopy-sandbox":
            # The script's third argument is the file it writes in HOME.
            args = [*args]
            at = args.index("sh", args.index("-c")) + 3
            args[at] = str(elsewhere / Path(args[at]).name)
        return real_run(self, args, **kwargs)  # type: ignore[arg-type]

    with mock.patch.object(SubprocessRunner, "run", autospec=True, side_effect=run):
        report = sandbox_check.run_check(SubprocessRunner(), primary, network=False)

    [write] = [a for a in report.attempts if a.name == "write a file in your home directory"]
    assert (write.allowed, write.ok) == (False, True)
    assert [p.name for p in elsewhere.iterdir() if sandbox_check.PREFIX in p.name] != []


def test_the_network_is_tried_with_a_host_off_the_allowlist_and_one_on_it(
    canopy_env: CanopyEnv,
    primary: Path,
    tmp_path: Path,
) -> None:
    with curl_on_path(tmp_path):
        report = sandbox_check.run_check(SubprocessRunner(), primary)

    network = [(a.name, a.allowed, a.expected) for a in report.attempts if a.name.startswith("reach")]
    assert network == [
        ("reach https://example.com, off the allowlist", False, False),
        ("reach https://github.com, on the allowlist", True, True),
    ]
    assert report.skipped == ()
    assert left_behind(canopy_env) == []


def test_a_template_that_allows_the_host_the_check_expects_refused_skips_that_attempt(
    canopy_env: CanopyEnv,
    primary: Path,
    tmp_path: Path,
) -> None:
    template = canopy_env.home / ".config" / "canopy" / "sandbox" / "worker.json"
    policy = json.loads(template.read_text())
    policy["network"]["allowedDomains"] = ["example.com"]
    template.write_text(json.dumps(policy))
    with curl_on_path(tmp_path):
        report = sandbox_check.run_check(SubprocessRunner(), primary)

    assert [a.name for a in report.attempts if a.name.startswith("reach")] == [
        "reach https://example.com, on the allowlist",
    ]
    assert report.skipped == ("a host off the allowlist was not tried: the template allows example.com.",)


def test_a_host_off_the_allowlist_that_is_down_shows_nothing_either_way(
    canopy_env: CanopyEnv,
    primary: Path,
    tmp_path: Path,
) -> None:
    """Only srt's own refusal counts as one: a host no one can reach would pass a sandbox that allows it."""
    assert canopy_env.home.is_dir()
    with curl_on_path(tmp_path), mock.patch.dict(os.environ, {"FAKE_CURL_CONNECT": "000"}):
        report = sandbox_check.run_check(SubprocessRunner(), primary)

    assert [a.name for a in report.attempts if a.name.startswith("reach")] == [
        "reach https://github.com, on the allowlist",
    ]
    assert report.skipped == (
        "https://example.com could not be reached, and not because the sandbox refused it: not checked.",
    )


@pytest.mark.parametrize("entry", ["example.com", "example.com:443", "*.com", "*"])
def test_an_entry_that_allows_the_host_by_a_wildcard_or_a_port_allows_it(entry: str) -> None:
    assert sandbox_check._matches(entry, "example.com")  # noqa: SLF001


@pytest.mark.parametrize("entry", ["*.example.com", "github.com", "notexample.com"])
def test_an_entry_for_another_host_does_not(entry: str) -> None:
    assert not sandbox_check._matches(entry, "example.com")  # noqa: SLF001


def test_the_worktree_has_no_files_checked_out_and_no_other_worktrees_record_is_pruned(
    canopy_env: CanopyEnv,
    primary: Path,
) -> None:
    """A stale record, of a worktree whose directory is gone, is the operator's to prune, not the check's."""
    stale = canopy_env.home / "stale"
    git("worktree", "add", "--quiet", "--detach", str(stale), cwd=primary)
    shutil.rmtree(stale)

    report = sandbox_check.run_check(SubprocessRunner(), primary, network=False)

    assert report.error == ""
    assert str(stale) in git("worktree", "list", "--porcelain", cwd=primary)


def test_a_wrapper_that_cannot_sandbox_is_an_error_not_a_pass(canopy_env: CanopyEnv, primary: Path) -> None:
    (canopy_env.home / ".config" / "canopy" / "sandbox" / "worker.json").unlink()

    report = sandbox_check.run_check(SubprocessRunner(), primary, network=False)

    assert not report.ok
    assert report.attempts == ()
    assert "no policy template at" in report.error
    assert "run `canopy sandbox setup`" in report.error
    assert left_behind(canopy_env) == []


def test_a_repository_with_no_commit_is_an_error(canopy_env: CanopyEnv, fakes_on_path: Path) -> None:
    assert fakes_on_path.is_dir()
    with mock.patch.dict(os.environ, HERMETIC_GIT):
        git("init", "--quiet", "--initial-branch=main", cwd=canopy_env.repo)
        report = sandbox_check.run_check(SubprocessRunner(), canopy_env.repo, network=False)

    assert report.error.startswith(f"a worktree of {canopy_env.repo} could not be made for the check:")
    assert left_behind(canopy_env) == []


@pytest.mark.usefixtures("primary")
def test_the_command_prints_each_attempt_and_exits_1_where_the_sandbox_did_not_hold(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["sandbox", "check", "--repo", "repo", "--offline"]) == 1

    printed = capsys.readouterr()
    assert "allowed  read a file in your home directory   <- should be refused\n" in printed.out
    assert "allowed  commit in the worktree, its objects in the run's own directory\n" in printed.out
    assert "Note: the network was not checked, as asked.\n" in printed.out
    assert "the sandbox did not hold at 5 of 6 attempts" in printed.err


@pytest.mark.usefixtures("primary")
def test_the_command_refuses_a_repository_the_workspace_does_not_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sandbox", "check", "--repo", "other"]) == 1

    assert "no repository named other in this workspace" in capsys.readouterr().err
