"""`canopy-sandbox`, the prefix a sandboxed run's command starts with (DESIGN §24).

The fake `srt` on PATH records the policy and environment the wrapper hands it, then runs the command unsandboxed.
These tests check what the wrapper asks of the sandbox, not that the sandbox holds: that is the canary's job (§6).
"""

import hashlib
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
from tests.canopy.helpers import DEAD_PID, InlineRunner, in_tick, pool, present, slot_of, worker_does
from tests.canopy.review_helpers import CLEAN, PR, reviewer_reports, run_inline
from tests.conftest import HERMETIC_GIT, CanopyEnv, GitPool, executable, git, user_toml

# The command the install puts beside python, which is how canopy runs it: never `python -m`, which would put the
# slot's own directory first on the import path.
WRAPPER = Path(sys.executable).parent / "canopy-sandbox"
ROLES = ("worker", "setup", "chore", "review")
FAKES = Path(__file__).resolve().parents[1] / "fakes"
SRT_PACKAGE = "@anthropic-ai/sandbox-runtime"
# Quotes, a line break, and what a shell would expand: the command must receive it as it was given (§5 item 3).
PROMPT = 'it\'s "quoted"\n$(touch pwned) `id` $HOME \\ ; | & *'
PRINT_ARG = ["sh", "-c", 'printf %s "$1"', "sh"]
# The operator's OpenCode logins, as OpenCode 1.19.3 writes them: a provider's OAuth login, whose `expires` is in
# milliseconds, and a remote MCP server's, whose `expiresAt` is in seconds.
OAUTH = {
    "type": "oauth",
    "refresh": "refresh-1",
    "access": "access-1",
    "expires": 1_000,
    "accountId": "mine",
    "enterpriseUrl": "https://ghe.example.com",
}
API = {"type": "api", "key": "key-mine"}
MCP = {
    "tokens": {"accessToken": "mcp-1", "refreshToken": "mcp-refresh-1", "expiresAt": 100.5, "scope": "read"},
    "clientInfo": {"clientId": "mine"},
    "serverUrl": "https://mcp.example.com/mcp",
}


@dataclass(frozen=True)
class Sandbox:
    """The fake srt's log, the templates the wrapper reads, the temp directory it makes its run directories in, and
    the operator's XDG_CACHE_HOME and XDG_DATA_HOME."""

    log: Path
    templates: Path
    tmp: Path
    cache_home: Path
    data_home: Path

    def only_call(self) -> dict[str, Any]:
        """What srt was given, for the one run of it there was."""
        [call] = [json.loads(line) for line in self.log.read_text().splitlines()]
        return call

    def runs_root(self) -> Path:
        return self.tmp / f"canopy-sandbox-{os.getuid()}"

    def caches(self) -> Path:
        """The directory that holds each role's cache directory."""
        return self.cache_home / "canopy" / "sandbox"

    def datas(self) -> Path:
        """The directory that holds each role's data directory."""
        return self.data_home / "canopy" / "sandbox"

    def operators(self) -> Path:
        """The operator's own OpenCode data directory."""
        return self.data_home / "opencode"


@pytest.fixture
def sandbox(canopy_env: CanopyEnv, fakes_on_path: Path, tmp_path: Path) -> Iterator[Sandbox]:
    """The shipped templates where the wrapper reads them, the fake srt on PATH, a temp directory of the test's, and
    XDG_CACHE_HOME in the test's HOME, as XDG_DATA_HOME is already.

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
        # The operator's own, which the wrapper keeps: CI's runners set one.
        for name in ("UV_PYTHON_INSTALL_DIR", "UV_TOOL_DIR"):
            os.environ.pop(name, None)
        yield Sandbox(log, templates, Path(tmp), cache_home, Path(os.environ["XDG_DATA_HOME"]))


def wrap(*args: str, cwd: Path, env: Mapping[str, str] | None = None) -> procs.Result:
    return SubprocessRunner().run([str(WRAPPER), *args], cwd=cwd, env=env, timeout=60)


def logins(sandbox: Sandbox, auth: Mapping[str, object], mcp: Mapping[str, object] | None = None) -> None:
    """Give the operator these OpenCode logins, in their own data directory, as OpenCode keeps them."""
    sandbox.operators().mkdir(parents=True, exist_ok=True)
    for name, content in (("auth.json", auth), ("mcp-auth.json", mcp)):
        if content is not None:
            (sandbox.operators() / name).write_text(json.dumps(content, indent=2))
            (sandbox.operators() / name).chmod(0o600)


def operators(sandbox: Sandbox, name: str = "auth.json") -> object:
    return json.loads((sandbox.operators() / name).read_text())


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


def storing(data: Path, data_home: Path) -> dict[str, str]:
    """The data variables the wrapper sets for a run whose role's data directory is `data`, the operator's being
    `data_home`."""
    return {
        "XDG_DATA_HOME": str(data),
        "UV_PYTHON_INSTALL_DIR": str(data_home / "uv" / "python"),
        "UV_TOOL_DIR": str(data_home / "uv" / "tools"),
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
    # No run reads another's temp directory, or another role's cache or data.
    assert filesystem["denyRead"] == ["~", str(sandbox.runs_root()), str(sandbox.caches()), str(sandbox.datas())]
    # The shared directory entry by entry, so that its read-only binds leave this slot's own directory writable.
    entries = [*sorted(p for p in shared.iterdir() if p.name != "worktrees"), shared / "worktrees" / "other"]
    paths = [str(p) for p in (slot, own, *entries, objects)]
    assert filesystem["allowRead"][: len(paths) + 2] == [*paths, tmp, str(definitions)]
    assert str(shared) not in filesystem["allowRead"]
    assert filesystem["allowWrite"][:4] == [str(slot), str(own), str(objects), tmp]
    protected = [slot / ".git", own / "config.worktree", own / "commondir", own / "gitdir", sandbox.operators()]
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
        **storing(sandbox.datas() / "worker", sandbox.data_home),
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
    executable(planted, f"#!/bin/sh\ntouch {tmp_path / 'planted-ran'}\n")
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


@pytest.mark.parametrize("role", ROLES)
def test_each_role_starts_with_the_operators_logins_in_a_data_directory_of_its_own(
    sandbox: Sandbox, tmp_path: Path, role: str
) -> None:
    """OpenCode's data directory is the role's, and the wrapper copies the operator's logins into it: the operator's
    OpenCode, and the overseer's, run code their own names, so no run writes it, whatever the template says. Setup
    shares the worker's; uv, which the templates let a run read, still finds its own where the operator keeps it."""
    _, slot = linked_worktree(tmp_path, "repo")
    logins(sandbox, {"anthropic": OAUTH, "openai": API}, {"jira": MCP})
    places = {"worker": slot, "setup": slot, "chore": tmp_path, "review": review_dir(tmp_path, slot)}
    objects = {"CANOPY_GIT_OBJECTS": str(objects_dir(tmp_path))} if role in {"worker", "setup"} else {}
    read = 'cat "$XDG_DATA_HOME/opencode/auth.json" "$XDG_DATA_HOME/opencode/mcp-auth.json"'

    done = wrap(role, "sh", "-c", read, cwd=places[role], env={**objects, "UV_TOOL_DIR": "/opt/uv-tools"})

    assert done.ok, done.stderr
    assert done.stdout == "".join((sandbox.operators() / n).read_text() for n in ("auth.json", "mcp-auth.json"))
    call = sandbox.only_call()
    data = sandbox.datas() / ("worker" if role == "setup" else role)
    assert call["env"]["XDG_DATA_HOME"] == str(data)
    assert call["env"]["UV_TOOL_DIR"] == "/opt/uv-tools"
    assert call["env"]["UV_PYTHON_INSTALL_DIR"] == str(sandbox.data_home / "uv" / "python")
    filesystem = call["settings"]["filesystem"]
    assert str(sandbox.datas()) in filesystem["denyRead"]
    assert str(sandbox.operators()) in filesystem["denyWrite"]
    assert not [p for p in [*filesystem["allowRead"], *filesystem["allowWrite"]] if "share/opencode" in p]
    if role != "setup":  # setup runs no OpenCode
        assert str(data) in filesystem["allowRead"]
        assert str(data) in filesystem["allowWrite"]
    assert data.stat().st_mode & 0o777 == 0o700
    assert (data / "opencode" / "auth.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("place", ["missing", "link"])
def test_the_operators_opencode_data_is_denied_writing_wherever_it_leads(
    sandbox: Sandbox, tmp_path: Path, place: str
) -> None:
    """Missing, it is made, as OpenCode would at its first start, so that it is denied before a run could make it.
    A link, as a dotfile manager makes, is denied with where it leads."""
    target = tmp_path / "dotfiles" / "opencode"
    if place == "link":
        target.mkdir(parents=True)
        sandbox.data_home.mkdir(parents=True, exist_ok=True)
        sandbox.operators().symlink_to(target, target_is_directory=True)

    assert wrap("chore", "true", cwd=tmp_path).ok

    deny_write = sandbox.only_call()["settings"]["filesystem"]["denyWrite"]
    assert sandbox.operators().is_dir()
    assert deny_write == [str(sandbox.operators()), *([str(target)] if place == "link" else [])]


def test_a_refreshed_token_is_copied_back_and_nothing_else(sandbox: Sandbox, tmp_path: Path) -> None:
    """Only the tokens and expiry of a login the operator has, of the same kind, and later: never a new login, a
    `wellknown` one, an API key, where a token is sent, or whose account it is."""
    logins(sandbox, {"anthropic": OAUTH, "openai": API, "github-copilot": OAUTH}, {"jira": MCP, "linear": MCP})
    refreshed = {"refresh": "refresh-2", "access": "access-2", "expires": 2_000}
    theirs = {
        "anthropic": {**OAUTH, **refreshed, "accountId": "theirs", "enterpriseUrl": "https://evil.example.com"},
        "openai": {**API, "key": "key-theirs"},
        "github-copilot": {**OAUTH, "refresh": "refresh-older", "expires": 999},
        "planted": {"type": "wellknown", "key": "https://evil.example.com", "token": "t"},
    }
    tokens = {"accessToken": "mcp-2", "expiresAt": 200, "scope": "write"}
    theirs_mcp = {
        "jira": {**MCP, "tokens": tokens, "clientInfo": {"clientId": "theirs"}},
        "linear": {**MCP, "tokens": tokens, "serverUrl": "https://evil.example.com/mcp"},
        "planted": MCP,
    }
    write = 'cd "$XDG_DATA_HOME/opencode" && printf %s "$1" > auth.json && printf %s "$2" > mcp-auth.json'

    done = wrap("chore", "sh", "-c", write, "sh", json.dumps(theirs), json.dumps(theirs_mcp), cwd=tmp_path)

    assert done.ok, done.stderr
    assert operators(sandbox) == {"anthropic": {**OAUTH, **refreshed}, "openai": API, "github-copilot": OAUTH}
    jira = {**MCP, "tokens": {**tokens, "refreshToken": "mcp-refresh-1"}}  # a refresh that sends none keeps it
    assert operators(sandbox, "mcp-auth.json") == {"jira": jira, "linear": MCP}
    assert "copied back the refreshed tokens of auth.json: anthropic, mcp-auth.json: jira" in done.stderr
    assert (sandbox.operators() / "auth.json").stat().st_mode & 0o777 == 0o600


def test_a_killed_runs_refreshed_token_is_copied_back_by_its_roles_next_run(sandbox: Sandbox, tmp_path: Path) -> None:
    """canopy kills a timed-out run, wrapper and all: the next run of its role takes back what it left, and then
    starts from the operator's logins, not from what the killed run left."""
    logins(sandbox, {"anthropic": OAUTH})
    left = sandbox.datas() / "chore" / "opencode" / "auth.json"
    left.parent.mkdir(parents=True)
    refreshed = {**OAUTH, "refresh": "refresh-2", "access": "access-2", "expires": 2_000}
    left.write_text(json.dumps({"anthropic": refreshed, "planted": {"type": "wellknown", "key": "k", "token": "t"}}))

    done = wrap("chore", "cat", str(left), cwd=tmp_path)

    assert done.ok, done.stderr
    assert operators(sandbox) == {"anthropic": refreshed}
    assert json.loads(done.stdout) == {"anthropic": refreshed}


def test_a_login_the_operator_no_longer_has_is_gone_from_the_roles(sandbox: Sandbox, tmp_path: Path) -> None:
    logins(sandbox, {"anthropic": OAUTH})
    left = sandbox.datas() / "chore" / "opencode" / "mcp-auth.json"
    left.parent.mkdir(parents=True)
    left.write_text(json.dumps({"jira": MCP}))

    assert wrap("chore", "true", cwd=tmp_path).ok

    assert not left.exists()


@pytest.mark.parametrize(
    "script",
    [
        pytest.param('rm -r "$XDG_DATA_HOME/opencode" && ln -s "$1" "$XDG_DATA_HOME/opencode"', id="runtime-link"),
        pytest.param('ln -sf "$1/auth.json" "$XDG_DATA_HOME/opencode/auth.json"', id="file-link"),
        pytest.param('rm "$XDG_DATA_HOME/opencode/auth.json" && mkfifo "$XDG_DATA_HOME/opencode/auth.json"', id="fifo"),
        pytest.param(
            'rm "$XDG_DATA_HOME/opencode/auth.json" && cp -r "$1" "$XDG_DATA_HOME/opencode/auth.json"', id="dir"
        ),
        pytest.param('cp "$1/big.json" "$XDG_DATA_HOME/opencode/auth.json"', id="too-big"),
    ],
)
def test_what_a_run_leaves_in_place_of_its_logins_is_never_followed(
    sandbox: Sandbox, tmp_path: Path, script: str
) -> None:
    """The host reads what a run left in its data directory: a link is not followed, a fifo does not hang the
    wrapper, and a file bigger than any login file is not read. The next run of the role starts from the operator's
    logins all the same."""
    logins(sandbox, {"anthropic": OAUTH})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    refreshed = {"anthropic": {**OAUTH, "refresh": "refresh-2", "access": "access-2", "expires": 2_000}}
    (elsewhere / "auth.json").write_text(json.dumps(refreshed))
    (elsewhere / "big.json").write_text(json.dumps({**refreshed, "padding": "x" * (1 << 20)}))
    before = {p.name: p.read_bytes() for p in elsewhere.iterdir()}

    done = wrap("chore", "sh", "-c", script, "sh", str(elsewhere), cwd=tmp_path)
    again = wrap("chore", "cat", str(sandbox.datas() / "chore" / "opencode" / "auth.json"), cwd=tmp_path)

    assert done.ok, done.stderr
    assert again.ok, again.stderr
    assert operators(sandbox) == {"anthropic": OAUTH}
    assert json.loads(again.stdout) == {"anthropic": OAUTH}
    assert {p.name: p.read_bytes() for p in elsewhere.iterdir()} == before


@dataclass(frozen=True)
class Bazel:
    """A `bazel` on PATH that prints its arguments and the rc file it is given, and the operator's repository cache."""

    operator: Path
    farm: Path

    def entry(self, content: bytes, algorithm: str = "sha256") -> Path:
        """Put `content` in the operator's cache, as Bazel stores a download, and return its entry."""
        entry = self.operator / "content_addressable" / algorithm / hashlib.new(algorithm, content).hexdigest()
        entry.mkdir(parents=True)
        (entry / "file").write_bytes(content)
        return entry

    def mine(self, name: str, algorithm: str = "sha256") -> Path:
        """The role's entry `name`."""
        return self.farm / "content_addressable" / algorithm / name


@pytest.fixture
def fake_bazel(sandbox: Sandbox, tmp_path: Path) -> Iterator[Bazel]:
    """A fake `bazel` first on PATH, and an empty repository cache of the operator's, outside the sandbox's caches."""
    bin_dir = tmp_path / "bazel-bin"
    bin_dir.mkdir()
    executable(bin_dir / "bazel", '#!/bin/sh\nprintf "%s\\n" "$@"\ncat "${1#--bazelrc=}"\n')
    with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}):
        yield Bazel(tmp_path / "bazel-repository-cache", sandbox.caches() / "chore" / "bazel" / "repository-cache")


def adds_download(content: bytes, *, name: str | None = None, algorithm: str = "sha256") -> list[str]:
    """A command that adds `content` to the role's repository cache as Bazel would, under its checksum or `name`."""
    key = name or hashlib.new(algorithm, content).hexdigest()
    entry = f'"$XDG_CACHE_HOME/bazel/repository-cache/content_addressable/{algorithm}/{key}"'
    marker = "id-" + "b" * 64
    script = f'mkdir -p {entry} && printf %s "$1" > {entry}/file && touch {entry}/{marker}'
    return ["sh", "-c", script, "sh", content.decode()]


def test_bazel_runs_with_the_roles_caches_and_reads_the_operators_downloads(
    sandbox: Sandbox, fake_bazel: Bazel, tmp_path: Path
) -> None:
    """The run's `bazel` reads an rc file of the run's after the repository's: the role's own caches, its repository
    cache a link to each of the operator's downloads, which the run may read and not write."""
    entry = fake_bazel.entry(b"torch")
    options = ["--bazel-repository-cache", str(fake_bazel.operator)]

    done = wrap("chore", *options, "--", "bazel", "build", "//:all", cwd=tmp_path)

    assert done.ok, done.stderr
    call = sandbox.only_call()
    bin_dir = call["env"]["PATH"].split(os.pathsep)[0]
    rc, *args = done.stdout.splitlines()[:3]
    assert rc == f"--bazelrc={bin_dir}/bazelrc"
    assert args == ["build", "//:all"]
    root = sandbox.caches() / "chore" / "bazel"
    assert done.stdout.splitlines()[3:] == [
        f"startup --output_user_root={root / 'output'}",
        f"common --repository_cache={root / 'repository-cache'}",
        f"common --disk_cache={root / 'disk-cache'}",
    ]
    assert fake_bazel.mine(entry.name).readlink() == entry
    filesystem = call["settings"]["filesystem"]
    assert str(fake_bazel.operator) in filesystem["allowRead"]
    assert str(fake_bazel.operator) in filesystem["denyWrite"]
    assert bin_dir in filesystem["allowRead"]


def test_a_download_a_run_adds_is_copied_into_the_operators_cache_once_checked(
    sandbox: Sandbox, fake_bazel: Bazel, tmp_path: Path
) -> None:
    """From a copy the run cannot reach, and only when that copy has the checksum it is named by. The role's entry
    then links to the operator's, so the download is kept once."""
    options = ["--bazel-repository-cache", str(fake_bazel.operator)]
    key = hashlib.sha256(b"cuda").hexdigest()

    done = wrap("chore", *options, "--", *adds_download(b"cuda"), cwd=tmp_path)

    assert done.ok, done.stderr
    operator = fake_bazel.operator / "content_addressable" / "sha256" / key
    assert (operator / "file").read_bytes() == b"cuda"
    assert (operator / ("id-" + "b" * 64)).exists()
    assert fake_bazel.mine(key).readlink() == operator
    assert "copied 1 Bazel downloads" in done.stderr
    assert [p.name for p in operator.parent.iterdir()] == [key]  # no copy left behind


@pytest.mark.parametrize(
    ("command", "algorithm"),
    [
        pytest.param(adds_download(b"cuda", name="0" * 64), "sha256", id="not-its-checksum"),
        pytest.param(adds_download(b"cuda", algorithm="sha1"), "sha1", id="sha1"),
    ],
)
def test_a_download_whose_checksum_cannot_be_trusted_stays_the_roles(
    sandbox: Sandbox, fake_bazel: Bazel, tmp_path: Path, command: list[str], algorithm: str
) -> None:
    """SHA-1 has known collisions: a run could make two files with one name."""
    options = ["--bazel-repository-cache", str(fake_bazel.operator)]

    done = wrap("chore", *options, "--", *command, cwd=tmp_path)

    assert done.ok, done.stderr
    assert not [p for p in fake_bazel.operator.rglob("*") if not p.is_dir()]
    [mine] = (fake_bazel.farm / "content_addressable" / algorithm).iterdir()
    assert mine.is_dir()
    assert not mine.is_symlink()


def test_a_killed_runs_download_is_copied_back_by_its_roles_next_run(
    sandbox: Sandbox, fake_bazel: Bazel, tmp_path: Path
) -> None:
    key = hashlib.sha256(b"cuda").hexdigest()
    left = fake_bazel.mine(key)
    left.mkdir(parents=True)
    (left / "file").write_bytes(b"cuda")
    gone = fake_bazel.mine("1" * 64)
    gone.symlink_to(fake_bazel.operator / "content_addressable" / "sha256" / ("1" * 64))

    assert wrap("chore", "--bazel-repository-cache", str(fake_bazel.operator), "--", "true", cwd=tmp_path).ok

    assert (fake_bazel.operator / "content_addressable" / "sha256" / key / "file").read_bytes() == b"cuda"
    assert left.is_symlink()
    assert not gone.is_symlink()  # a link to a download the operator's cache no longer has


def test_a_download_the_operator_fetched_meanwhile_is_linked_and_not_copied(
    sandbox: Sandbox, fake_bazel: Bazel, tmp_path: Path
) -> None:
    entry = fake_bazel.entry(b"cuda")
    left = fake_bazel.mine(entry.name)
    left.mkdir(parents=True)
    (left / "file").write_bytes(b"cuda")

    done = wrap("chore", "--bazel-repository-cache", str(fake_bazel.operator), "--", "true", cwd=tmp_path)

    assert done.ok, done.stderr
    assert left.readlink() == entry
    assert "copied" not in done.stderr


@pytest.mark.parametrize(
    "script",
    [
        pytest.param('rm -r "$1/content_addressable" && ln -s "$2" "$1/content_addressable"', id="cas-link"),
        pytest.param('mkdir -p "$4" && ln -s "$2/sha256/$3/file" "$4/file"', id="file-link"),
        pytest.param('mkdir -p "$4" && mkfifo "$4/file"', id="fifo"),
    ],
)
def test_what_a_run_leaves_in_its_repository_cache_is_never_followed(
    sandbox: Sandbox, fake_bazel: Bazel, tmp_path: Path, script: str
) -> None:
    """The host reads the role's repository cache: a link the run left is not followed, and a fifo does not hang it."""
    elsewhere = tmp_path / "elsewhere"
    key = hashlib.sha256(b"cuda").hexdigest()
    (elsewhere / "sha256" / key).mkdir(parents=True)
    (elsewhere / "sha256" / key / "file").write_bytes(b"cuda")
    options = ["--bazel-repository-cache", str(fake_bazel.operator)]
    farm = str(fake_bazel.farm)

    entry = str(fake_bazel.mine(key))
    done = wrap("chore", *options, "--", "sh", "-c", script, "sh", farm, str(elsewhere), key, entry, cwd=tmp_path)
    again = wrap("chore", *options, "--", "true", cwd=tmp_path)

    assert done.ok, done.stderr
    assert again.ok, again.stderr
    assert not (fake_bazel.operator / "content_addressable" / "sha256" / key).exists()
    assert (elsewhere / "sha256" / key / "file").read_bytes() == b"cuda"
    assert not (fake_bazel.farm / "content_addressable").is_symlink()


@pytest.mark.parametrize("place", ["inside", "holding"])
def test_a_bazel_repository_cache_that_overlaps_the_sandboxs_caches_runs_nothing(
    sandbox: Sandbox, fake_bazel: Bazel, tmp_path: Path, place: str
) -> None:
    operator = sandbox.caches() / "x" if place == "inside" else sandbox.cache_home

    done = wrap("chore", "--bazel-repository-cache", str(operator), "--", "true", cwd=tmp_path)

    assert done.returncode == 2
    assert "overlaps the sandbox's caches" in done.stderr
    assert not sandbox.log.exists()


@pytest.mark.usefixtures("sandbox")
def test_a_bazel_repository_cache_without_bazel_runs_nothing(tmp_path: Path) -> None:
    done = wrap("chore", "--bazel-repository-cache", str(tmp_path / "cache"), "--", "true", cwd=tmp_path)

    assert done.returncode == 2
    assert "--bazel-repository-cache was given, but bazel is not on PATH" in done.stderr


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
    assert filesystem["denyWrite"] == [str(sandbox.operators())]
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
    cache, data = sandbox.caches() / "review", sandbox.datas() / "review"
    assert [p for p in filesystem["allowWrite"] if p.startswith(str(tmp_path))] == [str(data), str(cache)]
    assert filesystem["allowWrite"][0] == tmp
    assert filesystem["denyWrite"] == [str(sandbox.operators())]
    assert "github.com" not in call["settings"]["network"]["allowedDomains"]  # it pushes and fetches nothing
    assert call["env"] == {
        "CLAUDE_CODE_TMPDIR": tmp,
        "PATH": os.environ["PATH"],
        "TMPDIR": tmp,
        **caching(cache),
        **storing(data, sandbox.data_home),
    }


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
        (["chore", "--bazel-repository-cache", "relative", "true"], "--bazel-repository-cache takes an absolute path"),
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
        with in_tick(conn, ends_ok=True):
            args = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
            assert main([*args, "--slug", "work"], runner=runner) == 0
        run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
        assert main(["_run", str(run_id)], runner=runner) == 0

    run = present(db.get_run(conn, run_id))
    assert run["status"] == "done"
    call = sandbox.only_call()
    definitions = call["argv"][call["argv"].index("--") + 2].removeprefix("OPENCODE_CONFIG_DIR=")
    assert definitions in call["settings"]["filesystem"]["allowRead"]
    pushed = present(git_pool.remote_head("agent/PROJ-1-work"))
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

    row = present(db.get_review_run(conn, run_id))
    assert row.status == "done", Path(row.log_path).read_text()
    call = sandbox.only_call()
    assert call["cwd"] == str(canopy_env.state_dir / "reviews" / str(run_id))
    filesystem = call["settings"]["filesystem"]
    [slot] = [s for s in worktree_pool[1] if str(s.resolve()) in filesystem["allowRead"]]
    assert not [p for p in filesystem["allowWrite"] if p.startswith(str(slot.parent))]
    assert "CANOPY_GIT_OBJECTS" not in call["env"]
    assert all(s["status"] == "available" for s in pool(treehouse_state))
