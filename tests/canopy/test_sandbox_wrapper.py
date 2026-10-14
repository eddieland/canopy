"""examples/sandbox/canopy-sandbox, the prefix a sandboxed run's command starts with (HOST_ISOLATION §4.1).

The fake `srt` on PATH records the policy and environment the wrapper hands it, then runs the command unsandboxed.
These tests check what the wrapper asks of the sandbox, not that the sandbox holds: that is the canary's job (§6).
"""

import json
import os
import shutil
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.infra import procs
from canopy.infra.procs import SubprocessRunner
from tests.canopy.helpers import InlineRunner, in_tick, journal, pool, slot_of, worker_does
from tests.conftest import HERMETIC_GIT, CanopyEnv, GitPool, git, user_toml

WRAPPER = Path(__file__).resolve().parents[2] / "examples" / "sandbox" / "canopy-sandbox"
ROLES = ("worker", "setup", "chore")
DEAD_PID = 4_194_305  # above Linux's largest pid_max
# Quotes, a line break, and what a shell would expand: the command must receive it as it was given (§5 item 3).
PROMPT = 'it\'s "quoted"\n$(touch pwned) `id` $HOME \\ ; | & *'
PRINT_ARG = ["sh", "-c", 'printf %s "$1"', "sh"]


@dataclass(frozen=True)
class Sandbox:
    """The fake srt's log, the templates the wrapper reads, and the temp directory it makes its run directories in."""

    log: Path
    templates: Path
    tmp: Path

    def only_call(self) -> dict[str, Any]:
        """What srt was given, for the one run of it there was."""
        [call] = [json.loads(line) for line in self.log.read_text().splitlines()]
        return call

    def runs_root(self) -> Path:
        return self.tmp / f"canopy-sandbox-{os.getuid()}"


@pytest.fixture
def sandbox(canopy_env: CanopyEnv, fakes_on_path: Path, tmp_path: Path) -> Iterator[Sandbox]:
    """The shipped templates where the wrapper reads them, the fake srt on PATH, and a temp directory of the test's."""
    templates = canopy_env.home / ".config" / "canopy" / "sandbox"
    templates.mkdir(parents=True)
    for role in ROLES:
        shutil.copy(WRAPPER.parent / f"{role}.json", templates)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    log = tmp_path / "srt.jsonl"
    with mock.patch.dict(os.environ, {"FAKE_SRT_LOG": str(log), "TMPDIR": str(tmp), **HERMETIC_GIT}):
        yield Sandbox(log, templates, tmp)


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


def objects_dir(tmp_path: Path) -> Path:
    objects = tmp_path / "runs" / "1.objects"
    objects.mkdir(parents=True)
    return objects


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
    assert filesystem["denyRead"] == ["~", str(sandbox.runs_root())]  # no run reads another's temp directory
    # The shared directory entry by entry, so that its read-only binds leave this slot's own directory writable.
    entries = [*sorted(p for p in shared.iterdir() if p.name != "worktrees"), shared / "worktrees" / "other"]
    paths = [str(p) for p in (slot, own, *entries, objects)]
    assert filesystem["allowRead"][: len(paths) + 2] == [*paths, tmp, str(definitions)]
    assert str(shared) not in filesystem["allowRead"]
    assert filesystem["allowWrite"][:4] == [str(slot), str(own), str(objects), tmp]
    assert filesystem["denyWrite"] == [str(slot / ".git"), str(own / "config.worktree")]
    assert "#" not in json.dumps(call["settings"])
    assert call["settings"]["network"]["allowedDomains"][0] == "api.anthropic.com"
    assert call["env"] == {
        "CANOPY_GIT_OBJECTS": str(objects),
        "CLAUDE_CODE_TMPDIR": tmp,
        "TMPDIR": tmp,
        "GIT_OBJECT_DIRECTORY": str(objects),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(shared / "objects"),
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

    done = wrap("worker", "true", cwd=desk, env={"CANOPY_GIT_OBJECTS": str(objects)})

    assert done.ok, done.stderr
    call = sandbox.only_call()
    filesystem = call["settings"]["filesystem"]
    assert filesystem["allowRead"][:3] == [str(desk.resolve()), *map(str, slots)]
    assert filesystem["allowWrite"][:2] == [str(s) for s in slots]
    alternates = ":".join(str(p / ".git" / "objects") for p in primaries)
    assert call["env"]["GIT_ALTERNATE_OBJECT_DIRECTORIES"] == alternates


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


@pytest.mark.parametrize("role", ["worker", "chore"])
def test_the_workspaces_state_is_denied_even_outside_home(sandbox: Sandbox, tmp_path: Path, role: str) -> None:
    """The templates deny HOME; a workspace elsewhere would leave `.canopy/` readable without this."""
    state = tmp_path / "elsewhere" / ".canopy"
    objects = state / "runs" / "7.objects"
    objects.mkdir(parents=True)
    _, slot = linked_worktree(tmp_path, "repo")
    cwd = slot if role == "worker" else state / "chores" / "build-health"
    cwd.mkdir(parents=True, exist_ok=True)

    done = wrap(role, "true", cwd=cwd, env={"CANOPY_GIT_OBJECTS": str(objects)} if role == "worker" else None)

    assert done.ok, done.stderr
    assert str(state) in sandbox.only_call()["settings"]["filesystem"]["denyRead"]


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
    conn: sqlite3.Connection = journal(canopy_env)
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
