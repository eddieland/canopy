"""`canopy-sandbox`, the prefix a sandboxed run's command starts with (DESIGN §24).

The fake `srt` on PATH records the policy and environment the wrapper hands it, then runs the command unsandboxed.
These tests check what the wrapper asks of the sandbox, not that the sandbox holds: that is the canary's job (§6).
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock

import canopy_sandbox
import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.infra import procs
from canopy.infra.procs import SubprocessRunner
from tests.canopy.helpers import DEAD_PID, InlineRunner, in_tick, pool, slot_of, worker_does
from tests.canopy.review_helpers import CLEAN, PR, reviewer_reports, run_inline
from tests.conftest import HERMETIC_GIT, CanopyEnv, GitPool, git, user_toml

# The command the install puts beside python, which is how canopy runs it: never `python -m`, which would put the
# slot's own directory first on the import path.
WRAPPER = Path(sys.executable).parent / "canopy-sandbox"
ROLES = ("worker", "setup", "chore", "review")
FAKES = Path(__file__).resolve().parents[1] / "fakes"
SRT_PACKAGE = "@anthropic-ai/sandbox-runtime"
# Quotes, a line break, and what a shell would expand: the command must receive it as it was given (§5 item 3).
PROMPT = 'it\'s "quoted"\n$(touch pwned) `id` $HOME \\ ; | & *'
PRINT_ARG = ["sh", "-c", 'printf %s "$1"', "sh"]


@dataclass(frozen=True)
class Sandbox:
    """The fake srt's log, the templates the wrapper reads, the temp directory it makes its run directories in, and
    the operator's XDG_CACHE_HOME."""

    log: Path
    templates: Path
    tmp: Path
    cache_home: Path

    def only_call(self) -> dict[str, Any]:
        """What srt was given, for the one run of it there was."""
        [call] = [json.loads(line) for line in self.log.read_text().splitlines()]
        return call

    def runs_root(self) -> Path:
        return self.tmp / f"canopy-sandbox-{os.getuid()}"

    def caches(self) -> Path:
        """The directory that holds each role's cache directory."""
        return self.cache_home / "canopy" / "sandbox"


@pytest.fixture
def sandbox(canopy_env: CanopyEnv, fakes_on_path: Path, tmp_path: Path) -> Iterator[Sandbox]:
    """The shipped templates where the wrapper reads them, the fake srt on PATH, a temp directory of the test's, and
    XDG_CACHE_HOME in the test's HOME.

    Under /tmp, not tmp_path, whose path is too long for the sockets srt would make in it, which the wrapper refuses.
    """
    templates = canopy_env.home / ".config" / "canopy" / "sandbox"
    templates.mkdir(parents=True)
    for role in ROLES:
        shutil.copy(canopy_sandbox.TEMPLATES / f"{role}.json", templates)
    log = tmp_path / "srt.jsonl"
    cache_home = canopy_env.home / ".cache"
    variables = {"FAKE_SRT_LOG": str(log), "XDG_CACHE_HOME": str(cache_home), **HERMETIC_GIT}
    with (
        tempfile.TemporaryDirectory(prefix="sandbox.", dir="/tmp") as tmp,
        mock.patch.dict(os.environ, {**variables, "TMPDIR": tmp}),
    ):
        yield Sandbox(log, templates, Path(tmp), cache_home)


def wrap(*args: str, cwd: Path, env: Mapping[str, str] | None = None) -> procs.Result:
    return SubprocessRunner().run([str(WRAPPER), *args], cwd=cwd, env=env)


def linked_worktree(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """A repository with one commit and a linked worktree of it, as a treehouse slot is: the primary and the slot."""
    primary = tmp_path / name / "primary"
    primary.mkdir(parents=True)
    git("init", "--quiet", "--initial-branch=main", cwd=primary)
    git("commit", "--quiet", "--allow-empty", "-m", "initial", cwd=primary)
    slot = tmp_path / name / "slot"
    git("worktree", "add", "--quiet", "--detach", str(slot), cwd=primary)
    return primary.resolve(), slot.resolve()


def reading(objects: Path, primary: Path) -> dict[str, str]:
    """git's variables that read a run's object directory as well as a slot's shared objects, as `_run` sets them."""
    return {"GIT_OBJECT_DIRECTORY": str(objects), "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(primary / ".git" / "objects")}


def objects_dir(tmp_path: Path) -> Path:
    objects = tmp_path / "runs" / "1.objects"
    objects.mkdir(parents=True)
    return objects


def caching(cache: Path) -> dict[str, str]:
    """The cache variables the wrapper sets for a run whose role's cache directory is `cache`."""
    return {
        "XDG_CACHE_HOME": str(cache),
        "npm_config_cache": str(cache / "npm"),
        "GOCACHE": str(cache / "go-build"),
        "GOMODCACHE": str(cache / "go-mod"),
        "PIP_CACHE_DIR": str(cache / "pip"),
    }


def review_dir(parent: Path, checkout: Path) -> Path:
    """A reviewer's directory as `_review` makes it, `<parent>/reviews/3/`, with its one link, to the checkout."""
    cwd = parent / "reviews" / "3"
    cwd.mkdir(parents=True, mode=0o700)
    (cwd / "checkout").symlink_to(checkout, target_is_directory=True)
    return cwd


def test_a_worker_runs_under_a_policy_made_for_its_slot(sandbox: Sandbox, tmp_path: Path) -> None:
    primary, slot = linked_worktree(tmp_path, "repo")
    git("worktree", "add", "--quiet", "--detach", str(tmp_path / "repo" / "other"), cwd=primary)
    objects = objects_dir(tmp_path)
    definitions = tmp_path / "definitions"
    planted = str(tmp_path / "planted.sh")  # what srt's `bash -c` would source
    env = {"CANOPY_GIT_OBJECTS": str(objects), "BASH_ENV": planted, "ENV": planted}

    done = wrap("worker", "--read", str(definitions), "--", *PRINT_ARG, PROMPT, cwd=slot, env=env)

    assert done.ok, done.stderr
    assert done.stdout == PROMPT
    call = sandbox.only_call()
    settings, tmp = call["argv"][1], call["env"]["CLAUDE_CODE_TMPDIR"]
    assert call["argv"] == ["--settings", settings, "--", *PRINT_ARG, PROMPT]
    own, shared = primary / ".git" / "worktrees" / "slot", primary / ".git"
    filesystem = call["settings"]["filesystem"]
    # No run reads another's temp directory, or another role's cache.
    assert filesystem["denyRead"] == ["~", str(sandbox.runs_root()), str(sandbox.caches())]
    # The shared directory entry by entry, so that its read-only binds leave this slot's own directory writable.
    entries = [*sorted(p for p in shared.iterdir() if p.name != "worktrees"), shared / "worktrees" / "other"]
    paths = [str(p) for p in (slot, own, *entries, objects)]
    assert filesystem["allowRead"][: len(paths) + 2] == [*paths, tmp, str(definitions)]
    assert str(shared) not in filesystem["allowRead"]
    assert filesystem["allowWrite"][:4] == [str(slot), str(own), str(objects), tmp]
    protected = [slot / ".git", own / "config.worktree", own / "commondir", own / "gitdir"]
    assert filesystem["denyWrite"] == [str(p) for p in protected]
    assert "#" not in json.dumps(call["settings"])
    assert call["settings"]["network"]["allowedDomains"][0] == "api.anthropic.com"
    # git's own variables are the run's git's to set, in the run's worktrees only; it is first on PATH, and readable.
    bin_dir = str(Path(tmp).parent / "bin")
    assert call["env"].pop("PATH").split(os.pathsep)[0] == bin_dir
    assert bin_dir in filesystem["allowRead"]
    assert bin_dir not in filesystem["allowWrite"]
    cache = sandbox.caches() / "worker"
    assert str(cache) in filesystem["allowRead"]
    assert str(cache) in filesystem["allowWrite"]
    assert call["env"] == {
        "CANOPY_GIT_OBJECTS": str(objects),
        "CLAUDE_CODE_TMPDIR": tmp,
        "TMPDIR": tmp,
        **caching(cache),
    }
    assert Path(tmp).parent.parent == sandbox.runs_root()
    assert list(sandbox.runs_root().iterdir()) == []  # the policy and the temp directory are gone


def test_a_joint_runs_desk_names_every_worktree_it_links_to(sandbox: Sandbox, tmp_path: Path) -> None:
    primaries, slots = zip(*(linked_worktree(tmp_path, name) for name in ("api", "web")), strict=True)
    desk = tmp_path / "desks" / "PROJ-1"
    desk.mkdir(parents=True)
    (desk / ".canopy-desk").write_text("canopy's desk\n")
    for name, slot in zip(("api", "web"), slots, strict=True):
        (desk / name).symlink_to(slot, target_is_directory=True)
    objects = objects_dir(tmp_path)

    commit = "git -C api commit --quiet --allow-empty -m api && git -C web commit --quiet --allow-empty -m web"

    done = wrap("worker", "sh", "-c", commit, cwd=desk, env={"CANOPY_GIT_OBJECTS": str(objects)})

    assert done.ok, done.stderr
    call = sandbox.only_call()
    filesystem = call["settings"]["filesystem"]
    assert filesystem["allowRead"][:3] == [str(desk.resolve()), *map(str, slots)]
    assert filesystem["allowWrite"][:2] == [str(s) for s in slots]
    for primary, slot in zip(primaries, slots, strict=True):  # each worktree's commit, in the run's directory only
        head = git("rev-parse", "HEAD", cwd=slot)
        assert not SubprocessRunner().run(["git", "cat-file", "-e", head], cwd=primary).ok
        assert SubprocessRunner().run(["git", "cat-file", "-e", head], cwd=slot, env=reading(objects, primary)).ok


@pytest.mark.parametrize(
    "script",
    [
        pytest.param(
            'git init --quiet "$1" && git -C "$1" commit --quiet --allow-empty -m cached', id="init-then-commit"
        ),
        pytest.param(
            'mkdir "$1" && cd "$1" && git init --quiet --bare && git fetch --quiet "$2" HEAD && '
            "git update-ref refs/heads/x FETCH_HEAD",
            id="go-module-source",
        ),
        pytest.param(
            'git --git-dir "$1" --work-tree . init --quiet && echo work > work.txt && '
            'git --git-dir "$1" --work-tree . add work.txt && git --git-dir="$1" --work-tree=. commit --quiet -m snap',
            id="opencode-snapshot",
        ),
        pytest.param(
            'export GIT_OBJECT_DIRECTORY="$CANOPY_GIT_OBJECTS" && git init --quiet "$1" && '
            'git -C "$1" commit --quiet --allow-empty -m inherited',
            id="inherited-from-a-worktrees-git",
        ),
    ],
)
def test_a_repository_a_tool_keeps_outside_the_worktree_keeps_its_own_objects(
    sandbox: Sandbox, tmp_path: Path, script: str
) -> None:
    """A cache a tool keeps as a git repository (DESIGN §24): with git's variables set for every process, its
    objects went to the run's directory and were gone with it. The worker's own commit still lands only there."""
    primary, slot = linked_worktree(tmp_path, "repo")
    objects = objects_dir(tmp_path)
    cache = tmp_path / "cache"
    work = f"git commit --quiet --allow-empty -m work && {script}"

    done = wrap(
        "worker", "sh", "-c", work, "sh", str(cache), str(primary), cwd=slot, env={"CANOPY_GIT_OBJECTS": str(objects)}
    )

    assert done.ok, done.stderr
    head = git("rev-parse", "HEAD", cwd=slot)
    assert not SubprocessRunner().run(["git", "cat-file", "-e", head], cwd=primary).ok
    assert SubprocessRunner().run(["git", "cat-file", "-e", head], cwd=slot, env=reading(objects, primary)).ok
    shutil.rmtree(objects)  # as `_run` does once the slot is tidied
    fsck = SubprocessRunner().run(["git", "fsck", "--no-dangling"], cwd=cache)
    assert fsck.ok, fsck.stderr
    assert git("for-each-ref", cwd=cache)  # something was kept, and is whole


def test_a_slot_that_commits_a_desk_marker_is_still_a_slot(sandbox: Sandbox, tmp_path: Path) -> None:
    """A branch can commit the marker and a link to another slot; only a desk canopy made, with no `.git`, is a desk."""
    primary, slot = linked_worktree(tmp_path, "repo")
    other = tmp_path / "repo" / "other"
    git("worktree", "add", "--quiet", "--detach", str(other), cwd=primary)
    (slot / ".canopy-desk").write_text("planted\n")
    (slot / "other").symlink_to(other, target_is_directory=True)

    done = wrap("worker", "true", cwd=slot, env={"CANOPY_GIT_OBJECTS": str(objects_dir(tmp_path))})

    assert done.ok, done.stderr
    allow_write = sandbox.only_call()["settings"]["filesystem"]["allowWrite"]
    assert str(slot) in allow_write
    assert str(other.resolve()) not in allow_write


def test_neither_git_nor_srt_is_pointed_elsewhere_by_the_environment(sandbox: Sandbox, tmp_path: Path) -> None:
    """`GIT_DIR` naming another slot, and a relative PATH entry that finds an `srt` the checkout committed."""
    primary, slot = linked_worktree(tmp_path, "repo")
    other = tmp_path / "repo" / "other"
    git("worktree", "add", "--quiet", "--detach", str(other), cwd=primary)
    planted = slot / "bin" / "srt"
    planted.parent.mkdir()
    planted.write_text(f"#!/bin/sh\ntouch {tmp_path / 'planted-ran'}\n")
    planted.chmod(0o755)
    env = {
        "CANOPY_GIT_OBJECTS": str(objects_dir(tmp_path)),
        "GIT_DIR": str(primary / ".git" / "worktrees" / "other"),
        "PATH": f"bin{os.pathsep}{os.environ['PATH']}",
    }

    done = wrap("worker", "true", cwd=slot, env=env)

    assert done.ok, done.stderr
    assert not (tmp_path / "planted-ran").exists()
    call = sandbox.only_call()
    assert "GIT_DIR" not in call["env"]
    assert call["settings"]["filesystem"]["allowWrite"][0] == str(slot)
    assert str(other.resolve()) not in call["settings"]["filesystem"]["allowWrite"]


@pytest.mark.parametrize("role", ["worker", "chore", "review"])
def test_the_workspaces_state_is_denied_even_outside_home(sandbox: Sandbox, tmp_path: Path, role: str) -> None:
    """The templates deny HOME; a workspace elsewhere would leave `.canopy/` readable without this."""
    state = tmp_path / "elsewhere" / ".canopy"
    objects = state / "runs" / "7.objects"
    objects.mkdir(parents=True)
    _, slot = linked_worktree(tmp_path, "repo")
    cwds = {"worker": slot, "chore": state / "chores" / "build-health"}
    cwd = cwds[role] if role in cwds else review_dir(state, slot)
    cwd.mkdir(parents=True, exist_ok=True)

    done = wrap(role, "true", cwd=cwd, env={"CANOPY_GIT_OBJECTS": str(objects)} if role == "worker" else None)

    assert done.ok, done.stderr
    assert str(state) in sandbox.only_call()["settings"]["filesystem"]["denyRead"]


def test_each_role_caches_in_a_directory_of_its_own_and_setup_in_the_workers(sandbox: Sandbox, tmp_path: Path) -> None:
    """Never in the operator's caches, whatever they set them to: OpenCode, the overseer's included, runs packages
    and programs from its cache, outside any sandbox. Setup warms the worker's."""
    _, slot = linked_worktree(tmp_path, "repo")
    write = ["sh", "-c", 'mkdir -p "$XDG_CACHE_HOME/tool" && echo "$1" > "$XDG_CACHE_HOME/tool/$1"', "sh"]
    operators = {"GOMODCACHE": str(tmp_path / "go-mod"), "npm_config_cache": str(tmp_path / "npm")}
    places = {"worker": slot, "setup": slot, "chore": tmp_path, "review": review_dir(tmp_path, slot)}

    for role, cwd in places.items():
        objects = {"CANOPY_GIT_OBJECTS": str(objects_dir(tmp_path / role))} if role in {"worker", "setup"} else {}
        done = wrap(role, *write, role, cwd=cwd, env={**objects, **operators})
        assert done.ok, done.stderr

    calls = [json.loads(line) for line in sandbox.log.read_text().splitlines()]
    for call, role in zip(calls, places, strict=True):
        cache = sandbox.caches() / ("worker" if role == "setup" else role)
        assert {k: call["env"][k] for k in caching(cache)} == caching(cache)
        assert str(cache) in call["settings"]["filesystem"]["allowWrite"]
        assert str(sandbox.caches()) in call["settings"]["filesystem"]["denyRead"]
    assert sorted(p.name for p in sandbox.caches().iterdir()) == ["chore", "review", "worker"]
    assert sorted(p.name for p in (sandbox.caches() / "worker" / "tool").iterdir()) == ["setup", "worker"]
    assert (sandbox.caches() / "review").stat().st_mode & 0o777 == 0o700


def test_a_cache_directory_already_there_is_made_private(sandbox: Sandbox, tmp_path: Path) -> None:
    (sandbox.caches() / "chore").mkdir(parents=True, mode=0o755)
    (sandbox.caches() / "chore").chmod(0o755)

    assert wrap("chore", "true", cwd=tmp_path).ok

    assert (sandbox.caches() / "chore").stat().st_mode & 0o777 == 0o700


def test_a_cache_directory_that_is_a_link_runs_nothing(sandbox: Sandbox, tmp_path: Path) -> None:
    sandbox.caches().mkdir(parents=True)
    (sandbox.caches() / "chore").symlink_to(sandbox.cache_home, target_is_directory=True)

    done = wrap("chore", "true", cwd=tmp_path)

    assert done.returncode == 2
    assert "is not a directory of this user's" in done.stderr
    assert not sandbox.log.exists()


def test_a_run_that_locks_its_temp_directory_still_has_it_removed(sandbox: Sandbox, tmp_path: Path) -> None:
    lock = 'mkdir -p "$TMPDIR/a/b" && chmod 000 "$TMPDIR/a" "$TMPDIR"'

    done = wrap("chore", "sh", "-c", lock, cwd=tmp_path)

    assert done.ok, done.stderr
    assert list(sandbox.runs_root().iterdir()) == []


def test_setup_gets_its_own_policy(sandbox: Sandbox, tmp_path: Path) -> None:
    _, slot = linked_worktree(tmp_path, "repo")
    (sandbox.templates / "setup.json").write_text(
        json.dumps({"network": {"allowedDomains": ["registry.npmjs.org"]}, "filesystem": {"denyRead": ["~"]}})
    )

    done = wrap("setup", "true", cwd=slot, env={"CANOPY_GIT_OBJECTS": str(objects_dir(tmp_path))})

    assert done.ok, done.stderr
    assert sandbox.only_call()["settings"]["network"]["allowedDomains"] == ["registry.npmjs.org"]


def test_a_chore_reads_its_cwd_and_gets_no_git(sandbox: Sandbox, tmp_path: Path) -> None:
    cwd = tmp_path / "chores" / "build-health"
    cwd.mkdir(parents=True)

    done = wrap("chore", "--read", "/defs", "true", cwd=cwd)

    assert done.ok, done.stderr
    call = sandbox.only_call()
    filesystem = call["settings"]["filesystem"]
    tmp = call["env"]["TMPDIR"]
    assert filesystem["allowRead"][:3] == [str(cwd.resolve()), tmp, "/defs"]
    assert str(cwd.resolve()) not in filesystem["allowWrite"]
    assert filesystem["denyWrite"] == []
    assert "GIT_OBJECT_DIRECTORY" not in call["env"]


def test_a_review_reads_its_checkout_and_writes_none_of_it(sandbox: Sandbox, tmp_path: Path) -> None:
    """The reviewer reads the PR's checkout through its directory's link, and writes nothing there: not the worktree,
    not its git directories, and no objects, so it gets neither an object directory nor the run's git."""
    primary, slot = linked_worktree(tmp_path, "repo")
    cwd = review_dir(tmp_path, slot)

    done = wrap("review", "--read", "/defs", "git", "-C", "checkout", "rev-parse", "HEAD", cwd=cwd)

    assert done.ok, done.stderr
    assert done.stdout.strip() == git("rev-parse", "HEAD", cwd=slot)
    call = sandbox.only_call()
    filesystem = call["settings"]["filesystem"]
    tmp = call["env"]["TMPDIR"]
    own, shared = primary / ".git" / "worktrees" / "slot", primary / ".git"
    entries = sorted(p for p in shared.iterdir() if p.name != "worktrees")
    paths = [str(p) for p in (cwd.resolve(), slot, own, *entries)]
    assert filesystem["allowRead"][: len(paths) + 2] == [*paths, tmp, "/defs"]
    cache = sandbox.caches() / "review"
    assert [p for p in filesystem["allowWrite"] if p.startswith(str(tmp_path))] == [str(cache)]
    assert filesystem["allowWrite"][0] == tmp
    assert filesystem["denyWrite"] == []
    assert "github.com" not in call["settings"]["network"]["allowedDomains"]  # it pushes and fetches nothing
    assert call["env"] == {"CLAUDE_CODE_TMPDIR": tmp, "PATH": os.environ["PATH"], "TMPDIR": tmp, **caching(cache)}


@pytest.mark.parametrize("place", ["empty", "slot"])
def test_a_review_outside_a_review_directory_runs_nothing(sandbox: Sandbox, tmp_path: Path, place: str) -> None:
    """A review's directory links to its checkout. A slot is not one: a branch can commit a link to another slot."""
    primary, slot = linked_worktree(tmp_path, "repo")
    other = tmp_path / "repo" / "other"
    git("worktree", "add", "--quiet", "--detach", str(other), cwd=primary)
    (slot / "other").symlink_to(other, target_is_directory=True)
    cwd = slot if place == "slot" else tmp_path / "reviews" / "3"
    cwd.mkdir(parents=True, exist_ok=True)

    done = wrap("review", "true", cwd=cwd)

    assert done.returncode == 2
    assert ("is a checkout" if place == "slot" else "links to no worktree") in done.stderr
    assert not sandbox.log.exists()


def test_the_srt_canopy_installed_runs_and_reads_its_own_vendor_directory(
    sandbox: Sandbox, canopy_env: CanopyEnv, tmp_path: Path
) -> None:
    """`canopy sandbox setup`'s srt wins over PATH's, and the seccomp helper under the denied HOME stays runnable."""
    package = canopy_env.home / ".local" / "share" / "canopy" / "sandbox-runtime" / "node_modules" / SRT_PACKAGE
    (package / "dist").mkdir(parents=True)
    (package / "vendor" / "seccomp").mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"name": SRT_PACKAGE, "version": "0.0.79"}))
    shutil.copy(FAKES / "srt", package / "dist" / "cli.js")
    link = package.parents[1] / ".bin" / "srt"
    link.parent.mkdir()
    link.symlink_to(Path("..") / SRT_PACKAGE / "dist" / "cli.js")

    assert wrap("chore", "true", cwd=tmp_path).ok

    call = sandbox.only_call()
    assert call["settings"]["filesystem"]["allowRead"][-1] == str((package / "vendor").resolve())


@pytest.mark.usefixtures("sandbox")
def test_without_srt_nothing_runs(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    done = wrap("chore", "touch", str(tmp_path / "ran"), cwd=tmp_path, env={"PATH": str(empty)})

    assert done.returncode == 2
    assert "srt is not installed; run `canopy sandbox setup`" in done.stderr
    assert not (tmp_path / "ran").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="srt bridges the network over Unix sockets on Linux")
def test_a_temp_directory_too_deep_for_srts_sockets_runs_nothing(sandbox: Sandbox, tmp_path: Path) -> None:
    """srt makes its sockets in the run's temp directory, and says only that it could not when the path is too long."""
    deep = sandbox.tmp / ("d" * 60)
    deep.mkdir()

    done = wrap("chore", "touch", str(tmp_path / "ran"), cwd=tmp_path, env={"TMPDIR": str(deep)})

    assert done.returncode == 2
    assert f"the temp directory {deep} has too long a path for srt's sockets" in done.stderr
    assert not sandbox.log.exists()
    assert list((deep / f"canopy-sandbox-{os.getuid()}").iterdir()) == []


def test_the_commands_exit_status_is_the_wrappers(sandbox: Sandbox, tmp_path: Path) -> None:
    done = wrap("chore", "sh", "-c", "exit 7", cwd=tmp_path)

    assert done.returncode == 7


def test_a_run_directory_whose_process_is_gone_is_removed_by_the_next_run(sandbox: Sandbox, tmp_path: Path) -> None:
    root = sandbox.runs_root()
    root.mkdir(mode=0o700)
    for name, pid in (("run.dead", DEAD_PID), ("run.live", os.getpid())):
        (root / name / "tmp").mkdir(parents=True)
        (root / name / "pid").write_text(f"{pid}\n")

    assert wrap("chore", "true", cwd=tmp_path).ok

    assert [p.name for p in root.iterdir()] == ["run.live"]


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (["sandbox", "true"], "usage: canopy-sandbox"),
        (["chore"], "no command to run"),
        (["chore", "--"], "no command to run"),
        (["chore", "--read"], "--read takes an absolute path"),
        (["chore", "--read", "relative", "true"], "--read takes an absolute path"),
        (["worker", "true"], "CANOPY_GIT_OBJECTS is not set"),
    ],
)
def test_bad_arguments_run_nothing(sandbox: Sandbox, tmp_path: Path, args: list[str], error: str) -> None:
    done = wrap(*args, cwd=tmp_path)

    assert done.returncode == 2
    assert error in done.stderr
    assert not sandbox.log.exists()


@pytest.mark.parametrize("place", ["primary", "plain"])
def test_a_worker_outside_a_linked_worktree_runs_nothing(sandbox: Sandbox, tmp_path: Path, place: str) -> None:
    """A clone's HEAD and index are in the git directory its slots share, which the sandbox cannot let it write."""
    primary, _ = linked_worktree(tmp_path, "repo")
    cwd = primary if place == "primary" else tmp_path / "plain"
    cwd.mkdir(exist_ok=True)

    done = wrap("worker", "true", cwd=cwd, env={"CANOPY_GIT_OBJECTS": str(objects_dir(tmp_path))})

    assert done.returncode == 2
    assert not sandbox.log.exists()


@pytest.mark.parametrize(
    ("template", "error"),
    [
        (None, "no policy template at"),
        ("{", "could not be read"),
        ({"network": {"allowedDomains": []}, "filesystem": {"denyRead": ["@HOME@"]}}, "unknown placeholder, @HOME@"),
        ({"network": {"allowedDomains": []}, "filesystem": {"denyRead": ["@CWD@/x"]}}, "must be a whole string"),
        ({"network": {"allowedDomains": []}, "filesystem": {"denyRead": []}}, "denies no reads"),
        ({"network": {"allowedDomains": []}, "filesystem": {"denyRead": ["@READ@"]}}, "denies no reads"),
        ({"network": {}, "filesystem": {"denyRead": ["~"]}}, "no network.allowedDomains list"),
        ({"network": {"allowedDomains": []}, "filesystem": {"denyRead": "~"}}, "denyRead is not a list"),
        ([], "denies no reads"),
    ],
)
def test_a_template_that_would_not_confine_the_command_runs_nothing(
    sandbox: Sandbox, tmp_path: Path, template: object, error: str
) -> None:
    path = sandbox.templates / "chore.json"
    if template is None:
        path.unlink()
    else:
        path.write_text(template if isinstance(template, str) else json.dumps(template))

    done = wrap("chore", "true", cwd=tmp_path)

    assert done.returncode == 2
    assert error in done.stderr
    assert not sandbox.log.exists()
    assert list(sandbox.runs_root().glob("run.*")) == []


def test_canopys_sandboxed_worker_commits_through_the_wrapper_and_is_pushed(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    worktree_pool: tuple[Path, list[Path]],
    agent_log: Path,
    treehouse_state: Path,
    sandbox: Sandbox,
) -> None:
    """`_run` with the wrapper as `worker_cmd`'s prefix: the worker's commit lands in the run's object directory only,
    `_run` pushes it from there, and the slot is tidied (DESIGN §8)."""
    primary, _ = worktree_pool
    prefix = f"{WRAPPER} worker --read {{definitions_dir}} -- env"
    canopy_env.write_user(user_toml().replace("\nworker_cmd = 'env", f"\nworker_cmd = '{prefix}"))
    conn: sqlite3.Connection = canopy_env.journal()
    commit = ["git", "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: work"]
    with worker_does(commit):
        runner = InlineRunner()
        with in_tick(conn) as tick_id:
            args = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
            assert main([*args, "--slug", "work"], runner=runner) == 0
            db.finish_tick(conn, tick_id, "ok", "test")
        run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
        assert main(["_run", str(run_id)], runner=runner) == 0

    run = db.get_run(conn, run_id)
    assert run is not None
    assert run["status"] == "done"
    call = sandbox.only_call()
    definitions = call["argv"][call["argv"].index("--") + 2].removeprefix("OPENCODE_CONFIG_DIR=")
    assert definitions in call["settings"]["filesystem"]["allowRead"]
    pushed = git_pool.remote_head("agent/PROJ-1-work")
    assert pushed is not None
    assert not SubprocessRunner().run(["git", "cat-file", "-e", pushed], cwd=primary).ok  # never in the shared one
    slot = Path(slot_of(conn, run_id)["slot_path"])
    assert git("rev-parse", "HEAD", cwd=slot) == git_pool.remote_head("main")
    assert not (canopy_env.state_dir / "runs" / f"{run_id}.objects").exists()
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_canopys_sandboxed_reviewer_reads_the_checkout_through_the_wrapper(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    worktree_pool: tuple[Path, list[Path]],
    treehouse_state: Path,
    sandbox: Sandbox,
) -> None:
    """`_review` with the wrapper as `review_cmd`'s prefix: the policy reads the slot it leased, and writes none."""
    template = f"{WRAPPER} review --read {{definitions_dir}} -- env OPENCODE_CONFIG_DIR={{definitions_dir}} agent run"
    review_cmd = f"review_cmd = '{template} --agent canopy-reviewer {{prompt}}'"
    user = canopy_env.user_file.read_text().replace("[runtime]\n", f"[runtime]\n{review_cmd}\n", 1)
    canopy_env.write_user(user + "\n[review]\nagent_prs = true\n")
    conn: sqlite3.Connection = canopy_env.journal()
    db.set_unit(conn, "PROJ-1", str(canopy_env.root), "repo", pr_url=PR)
    sha = git("rev-parse", "main", cwd=git_pool.origin)

    with reviewer_reports(CLEAN, ["git", "-C", "checkout", "rev-parse", "HEAD"]):
        run_id = run_inline(conn, "--ticket", "PROJ-1", sha=sha)

    row = db.get_review_run(conn, run_id)
    assert row is not None
    assert row["status"] == "done", Path(row["log_path"]).read_text()
    call = sandbox.only_call()
    assert call["cwd"] == str(canopy_env.state_dir / "reviews" / str(run_id))
    filesystem = call["settings"]["filesystem"]
    [slot] = [s for s in worktree_pool[1] if str(s.resolve()) in filesystem["allowRead"]]
    assert not [p for p in filesystem["allowWrite"] if p.startswith(str(slot.parent))]
    assert "CANOPY_GIT_OBJECTS" not in call["env"]
    assert all(s["status"] == "available" for s in pool(treehouse_state))
