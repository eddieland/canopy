"""Run an agent command inside `srt` with a policy made for this run (DESIGN §24).

A prefix on a command template in canopy's user config:

    canopy-sandbox ROLE [--read PATH]... [--] COMMAND [ARG]...

ROLE is `worker`, `setup`, `chore`, `review`, or `overseer`, and picks the policy template `ROLE.json` in
`$XDG_CONFIG_HOME/canopy/sandbox/` (`~/.config/canopy/sandbox/` when that is unset), where `canopy sandbox setup`
copies the templates in `templates/`.
`--read PATH`, which may repeat, names a path the command may read: pass the template's `{definitions_dir}`, so the
agent can load canopy's agent definitions. COMMAND and its arguments reach `srt` unchanged, after a `--`, so none of
them is ever read as an option of the wrapper's or of `srt`'s.

In order, it:

1. Drops from its own environment what would point git at another repository (`GIT_DIR` and its kind), every
   relative `PATH` entry, which would find `git` or `srt` in the checkout, and `BASH_ENV` and `ENV`, which the shell
   `srt` starts would source. The command inherits the same. On a Linux host whose kernel has no IPv6, it sets
   `SOCAT_DEFAULT_LISTEN_IP=4` there, unless the operator set it, so that srt's network bridge inside the sandbox can
   listen at all.
2. Finds the worktrees the run works in, and each one's own and shared git directories: for a worker or setup, the
   cwd, or each worktree a joint run's desk links to; for a review, the checkout its directory links to. A chore and
   the overseer have none. For the overseer, it checks that the cwd is a workspace root with its state directory, and
   makes the journal's locks there if canopy has yet to (Overseer, below).
3. Fills the template's placeholders with those paths and writes the policy to a private directory of its own, with
   the run's temp directory beside it, which is `srt`'s own TMPDIR too, so what `srt` leaves there goes with it.
   Whatever the template says, the policy denies reading the directory that holds every run's, so no run reads
   another's temp directory, and, for every role but the overseer, the workspace's `.canopy/` when the run's
   directories name it, in case the workspace is outside the HOME the template denies. A template that allows reading
   or writing one of these, or a directory that holds one, is refused, since `srt` would bind it back. It allows reading
   `srt`'s own `vendor/` directory, whose seccomp helper runs inside the sandbox, wherever `srt` is installed.
4. Points the command's caches at the role's own cache directory, `$XDG_CACHE_HOME/canopy/sandbox/ROLE/` (setup
   shares the worker's, which it warms): XDG_CACHE_HOME itself, and the variables of the tools whose caches do not
   follow it everywhere. Not the operator's: OpenCode imports packages and runs programs from its cache, the
   overseer's OpenCode, outside any sandbox, included, so a cache a run can write is code the host runs later. The
   policy denies reading the directory that holds every role's, as it does the run directories'.
5. For a worker or setup, puts a `git` of its own first on the command's PATH, in the run's directory, which the
   command may read but not write. It runs the real git, pointed at the run's object directory, `CANOPY_GIT_OBJECTS`,
   with each worktree's shared objects as alternates, when the repository git would act on is one of the run's
   worktrees, and unchanged anywhere else. Exported to every process, git's variables would reach a repository a tool
   keeps in a cache, such as OpenCode's snapshots or Go's module sources, whose objects would then go when the run's
   directory does. A git run by its absolute path gets neither, and in a worktree cannot write objects at all.
6. Runs `srt --settings POLICY -- COMMAND...`, waits for it, removes its directory, and exits with `srt`'s status.
   The `srt` is the one `canopy sandbox setup` installed, pinned by `runtime/package-lock.json`, in
   `$XDG_DATA_HOME/canopy/sandbox-runtime/` (`~/.local/share/canopy/sandbox-runtime/` when that is unset), or else
   the first on `PATH`.

A placeholder is a whole string in one of the template's lists, and expands to zero or more paths:

    @CWD@            the directory the command starts in: a slot, a joint run's desk, a chore's cwd, or a review's
                     directory
    @WORKTREES@      each worktree's top level
    @GIT_OWN@        each worktree's own git directory: its HEAD, index, and reflog
    @GIT_SHARED@     what each worktree's common git directory holds, which every slot shares (refs, objects,
                     config, hooks), entry by entry, leaving out the run's own git directories
    @GIT_PROTECTED@  each worktree's `.git` link, and the files in its own git directory that point git elsewhere:
                     `config.worktree`, `commondir`, and `gitdir`
    @OBJECTS@        the run's object directory
    @TMPDIR@         the run's temp directory, the command's TMPDIR
    @CACHE@          the role's cache directory, the command's XDG_CACHE_HOME
    @READ@           each `--read` path
    @JOURNAL@        for the overseer, what it writes in the workspace's state directory, each one there: the journal,
                     its WAL and shared-memory files, the tick's and the dispatch's locks, and canopy's log
    @WORKSPACE@      for the overseer, each entry of the workspace root but the state directory, then each entry of the
                     state directory but the journal's

`@GIT_SHARED@` names entries, not the directory, because of how `srt` (checked at 0.0.79) restores paths under a
denied directory such as HOME: it binds each `allowWrite` path back, then each `allowRead` path read-only, so a common
git directory in `allowRead` would cover the writable worktree directory inside it. An entry the common directory gains
after the run starts is not visible to the run. `@WORKSPACE@` names entries for the same reason, so that the journal's
files stay writable; an entry the workspace root or its state directory gains later is not visible either.

Overseer: canopy runs it in the workspace root (DESIGN §6), and it acts through canopy's tools, a server its runtime
starts inside the sandbox, which reads the config and the workspace and writes the journal (DESIGN §27). So its policy
reads the workspace and writes, of the state directory, only the journal's files: never the private config, the agent
definitions, the chores' agents and prompts, or a directory another run starts in, which canopy and its agents load
later. Nothing can be added to the state directory, so a lock canopy has yet to make could never be taken: the wrapper
makes the journal's locks first, as canopy would. No run the overseer asks for starts inside its sandbox: the tick
starts each once the overseer's run has ended (DESIGN §40), so none inherits this policy or ends with it.

A key that starts with `#` is a comment, and is left out of the policy. The wrapper refuses a template with an unknown
placeholder, a placeholder inside a longer string, no `filesystem.denyRead`, or no `network.allowedDomains`: `srt` runs
a command with no restrictions outside any sandbox at all. It refuses one whose `allowRead` or `allowWrite`, once
filled, names a directory the wrapper denies, or one that holds it, such as a chore's cwd above the role caches: `srt`
would bind it back, and one run could read another's.

The directory a run killed with SIGKILL leaves behind (canopy kills a timed-out run's whole process group) is removed
by the next run, once the process that made it is gone.

A program of its own, installed beside canopy, not part of the harness: canopy sees only the command template (D041).
Stdlib only.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, MutableMapping, Sequence

ROLES = ("worker", "setup", "chore", "review", "overseer")
# The roles that commit, and so get the run's object directory and the run's `git`. A review reads its checkout and
# writes nothing there; a chore has no worktree.
COMMITTING = ("worker", "setup")
# The policy templates `canopy sandbox setup` copies for each role, and the package and lockfile it installs srt from.
TEMPLATES = Path(__file__).resolve().parent / "templates"
RUNTIME_SPEC = Path(__file__).resolve().parent / "runtime"
OBJECTS_ENV = "CANOPY_GIT_OBJECTS"
# What canopy leaves in a joint run's desk (DESIGN §18); every other entry there links to a worktree.
DESK_MARKER = ".canopy-desk"
# The workspace's state directory, which holds the run directories canopy passes (D016), and the directories in it
# that hold one: a run's object directory, a chore's default cwd, and a review's directory.
STATE_DIR = ".canopy"
RUN_PARENTS = ("runs", "chores", "reviews")
PLACEHOLDER = re.compile(r"@[A-Z_]+@")
#: The workspace file, which marks the root of a workspace, where canopy runs the overseer (DESIGN §18).
WORKSPACE_FILE = "canopy-workspace.toml"
#: What the overseer writes in the workspace's state directory, through canopy's tools: the journal, its WAL and
#: shared-memory files, the tick's and the dispatch's locks, and canopy's log, by canopy's names for them, which
#: `tests/canopy_sandbox` holds to canopy's own. The journal comes first, and must be there.
JOURNAL = ("canopy.db", "canopy.db-wal", "canopy.db-shm", "lock", "dispatch.lock", "canopy.log")
#: The locks among them, which canopy makes when it first takes one.
LOCKS = ("lock", "dispatch.lock")
# What a worktree's own git directory holds that git reads as config or as where the rest of the repository is. With
# `commondir` rewritten, every git on the host in the slot, canopy's and treehouse's, reads a config and hooks the
# worker wrote (DESIGN §24).
GIT_OWN_PROTECTED = ("config.worktree", "commondir", "gitdir")
# The git the wrapper runs reads a slot a worker had, on the host: nothing from it may run (DESIGN §24).
SAFE_GIT = (
    "git",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "fetch.recurseSubmodules=false",
    "-c",
    "protocol.ext.allow=never",
)
# git reads a list of alternates split on colons, and names with a quote or a line break are quoted, so a path that
# holds one would name a directory of the worker's choosing.
UNSAFE_PATH = re.compile(r'[:"\n\r\\]')
# Read by the shell `srt` runs the command in: a non-interactive bash sources BASH_ENV, and sh in some modes ENV.
SHELL_STARTUP = ("BASH_ENV", "ENV")
# On Linux, srt runs socat inside the sandbox to carry its network to srt's proxy outside. socat listens on IPv6
# unless this says otherwise, and on a kernel without IPv6 exits at once, which srt does not report: every request from
# the sandbox then fails to connect.
SOCAT_LISTEN = "SOCAT_DEFAULT_LISTEN_IP"
# The `git` the command finds first on PATH, for a worker or setup (git_shim). POSIX sh, so that a git call costs one
# more git to find the repository, not a Python start.
GIT_SHIM = r"""#!/bin/sh
# canopy-sandbox's git, first on PATH (DESIGN §24). In the run's worktrees, git writes new objects to the
# run's object directory and reads each worktree's shared ones as well. Any other repository, such as a cache a tool
# keeps as a git repository, keeps its objects in its own directory, as it would without a sandbox.
real=@REAL@
objects=@OBJECTS@
dir= gitdir= worktree= want= command=
for arg do
    case $want in
        C) case $arg in /*) dir=$arg ;; ?*) dir=${dir:-.}/$arg ;; esac; want=; continue ;;
        gitdir) gitdir=$arg; want=; continue ;;
        worktree) worktree=$arg; want=; continue ;;
        value) want=; continue ;;
    esac
    case $arg in
        -C) want=C ;;
        --git-dir) want=gitdir ;;
        --git-dir=*) gitdir=${arg#--git-dir=} ;;
        --work-tree) want=worktree ;;
        --work-tree=*) worktree=${arg#--work-tree=} ;;
        -c|--namespace|--config-env|--attr-source) want=value ;;
        -*) ;;
        *) command=$arg; break ;;
    esac
done
case $command in
    # Each makes a repository, not the one around it.
    init|clone) common= ;;
    *) common=$(cd "${dir:-.}" 2>/dev/null &&
        "$real" ${gitdir:+"--git-dir=$gitdir"} ${worktree:+"--work-tree=$worktree"} \
            rev-parse --path-format=absolute --git-common-dir 2>/dev/null) ;;
esac
case $common in
    @COMMON@)
        GIT_OBJECT_DIRECTORY=$objects
        GIT_ALTERNATE_OBJECT_DIRECTORIES=@ALTERNATES@
        export GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
        ;;
    *)
        # Inherited from a git in a worktree, as by `git rebase --exec`: not for this repository.
        if [ "${GIT_OBJECT_DIRECTORY-}" = "$objects" ]; then
            unset GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
        fi
        ;;
esac
exec "$real" "$@"
"""
# Name a repository other than the one git finds from the cwd, for the wrapper's git and the command's alike.
GIT_LOCATION = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_GRAFT_FILE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_NAMESPACE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
)
# The npm package srt comes in; its `vendor/` holds the seccomp helper the sandbox runs (find_srt, vendor_dirs).
SRT_PACKAGE = "@anthropic-ai/sandbox-runtime"
# Where srt puts the sandbox's TMPDIR. Unset, it is /tmp/claude, which every sandboxed run shares.
SRT_TMPDIR = "CLAUDE_CODE_TMPDIR"
# On Linux, srt makes the Unix sockets that carry the sandbox's network in its own TMPDIR, which the wrapper sets to the
# run's temp directory, under names up to this long (checked at 0.0.79); a socket's path holds at most 107 bytes there.
SRT_SOCKET_NAME = "claude-socks-0123456789abcdef.sock"
SOCKET_PATH_MAX = 107
# The cache directory each role's runs share, under `$XDG_CACHE_HOME/canopy/sandbox/`. Setup warms the worker's.
CACHES = {"worker": "worker", "setup": "worker", "chore": "chore", "review": "review", "overseer": "overseer"}
# Where the command's tools keep their caches, each relative to the role's cache directory. XDG_CACHE_HOME moves
# OpenCode's, and most tools' on Linux; the rest are npm's, which never follows it, and Go's and pip's, which do not on
# macOS. Each is the directory the tool takes under XDG_CACHE_HOME on Linux, or else its own name.
CACHE_ENV = (
    ("XDG_CACHE_HOME", "."),
    ("npm_config_cache", "npm"),
    ("GOCACHE", "go-build"),
    ("GOMODCACHE", "go-mod"),
    ("PIP_CACHE_DIR", "pip"),
)


class SandboxError(Exception):
    """The command cannot be sandboxed as asked, so it does not run."""


class Worktree(NamedTuple):
    """A worktree the run works in, and its git directories."""

    top: Path
    own: Path
    shared: Path


def main() -> int:
    """The `canopy-sandbox` command.

    Returns:
        The exit status: `srt`'s, or 2 when the command could not be sandboxed and did not run.
    """
    return run(sys.argv[1:])


def run(argv: list[str]) -> int:
    """Run the command `argv` names in the sandbox, and return the exit status to exit with.

    Returns:
        `srt`'s exit status, or 2 when the command could not be sandboxed and did not run.
    """
    scrub(os.environ)
    listen_without_ipv6(os.environ)
    try:
        role, reads, command = parse(argv)
        objects = objects_dir(role)
        cwd = Path.cwd()
        trees = worktrees(role, cwd)
        state = workspace_state(role, cwd)
        journal = journal_files(state) if state is not None else []
        entries = workspace_entries(cwd, state, journal) if state is not None else []
        template = load_template(role)
        srt = find_srt()
        cache = cache_dir(role)
        run_dir = make_run_dir()
    except SandboxError as e:
        print(f"canopy-sandbox: {e}", file=sys.stderr)
        return 2
    try:
        tmp = run_dir / "tmp"
        check_socket_room(tmp)
        tmp.mkdir(mode=0o700)
        bin_dir = git_shim(run_dir, trees, objects) if objects is not None else None
        values = placeholders(cwd, trees, objects, tmp, cache=cache, reads=reads, journal=journal, workspace=entries)
        policy = fill(template, values)
        readable = [*vendor_dirs(srt), *([bin_dir] if bin_dir is not None else [])]
        # The overseer's own state directory holds the journal it writes: a rule for this role alone.
        states = state_dirs(objects, cwd) if state is None else []
        check(policy, [run_dir.parent, cache.parent, *states], readable)
        settings = run_dir / "policy.json"
        settings.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
        return run_srt(srt, settings, command, environment(os.environ, bin_dir, tmp, cache))
    except SandboxError as e:
        print(f"canopy-sandbox: {e}", file=sys.stderr)
        return 2
    finally:
        remove(run_dir)


def scrub(env: MutableMapping[str, str]) -> None:
    """Drop what would point git at another repository, and every relative `PATH` entry, from `env`.

    canopy starts the wrapper in a checkout, so a relative entry such as `.` would find a `git` or `srt` the branch
    committed, and run it on the host.
    """
    for name in (*GIT_LOCATION, *SHELL_STARTUP):
        env.pop(name, None)
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if Path(p).is_absolute())


def listen_without_ipv6(env: MutableMapping[str, str]) -> None:
    """Have srt's network bridge inside the sandbox listen on IPv4 on a Linux host without IPv6, unless `env` says.

    The sandbox's network namespace has IPv6 only when the host's kernel does. Off Linux, srt runs no such bridge.
    """
    if sys.platform == "linux" and ipv6_missing():
        env.setdefault(SOCAT_LISTEN, "4")


def ipv6_missing() -> bool:
    """Whether this kernel has no IPv6, so that no IPv6 socket can be opened, as socat opens one to listen.

    Returns:
        True when it has none.
    """
    try:
        socket.socket(socket.AF_INET6, socket.SOCK_STREAM).close()
    except OSError as e:
        return e.errno == errno.EAFNOSUPPORT
    return False


def parse(argv: list[str]) -> tuple[str, list[Path], list[str]]:
    """Split the wrapper's arguments into its role, the `--read` paths, and the command.

    Returns:
        The role, the paths to allow reading, and the command with its arguments.

    Raises:
        SandboxError: the role is unknown, a `--read` path is missing or relative, or there is no command.
    """
    if not argv or argv[0] not in ROLES:
        raise SandboxError(f"usage: canopy-sandbox {{{','.join(ROLES)}}} [--read PATH]... [--] COMMAND [ARG]...")
    role, rest = argv[0], argv[1:]
    reads: list[Path] = []
    while rest and rest[0] == "--read":
        option, *rest = rest
        if not rest or not Path(rest[0]).is_absolute():
            raise SandboxError(f"{option} takes an absolute path")
        reads.append(Path(rest.pop(0)))
    if rest and rest[0] == "--":
        rest = rest[1:]
    if not rest:
        raise SandboxError("no command to run")
    return role, reads, rest


def worktrees(role: str, cwd: Path) -> list[Worktree]:
    """Find the worktrees a run as `role` in `cwd` works in.

    A worker or setup works in `cwd`, or in each worktree a desk there links to. A review starts in a directory of
    canopy's, outside the checkout, which it reads through a link there (DESIGN §21); canopy made that directory
    private to the operator just before, so its links are canopy's. One with a `.git` is a checkout, whose links a
    branch committed. A chore and the overseer work in no worktree.

    Returns:
        Each worktree, in the order of the links.

    Raises:
        SandboxError: a review's directory is a checkout, a desk or a review's directory links to no worktree, or a
            place is not a linked worktree.
    """
    if role in {"chore", "overseer"}:
        return []
    if role == "review" and os.path.lexists(cwd / ".git"):
        raise SandboxError(f"{cwd} is a checkout: canopy-sandbox review runs only as canopy's review_cmd")
    if role == "review" or desk(cwd):
        places = sorted(p for p in cwd.iterdir() if p.is_symlink() and p.is_dir())
        if not places:
            raise SandboxError(f"{cwd} links to no worktree")
    else:
        places = [cwd]
    return [worktree(place) for place in places]


def desk(cwd: Path) -> bool:
    """Whether `cwd` is a desk canopy made: its marker, and no `.git`, which every slot has and git never checks out.

    A branch can commit a marker and links to other slots, so a marker in a slot must not make it a desk.

    Returns:
        True for a desk.
    """
    marker = cwd / DESK_MARKER
    return marker.is_file() and not marker.is_symlink() and not os.path.lexists(cwd / ".git")


def workspace_state(role: str, cwd: Path) -> Path | None:
    """Return the state directory of the workspace whose root the overseer starts in.

    canopy runs the overseer in the workspace root (DESIGN §6), and makes the state directory there private to the
    operator (D053), with the journal in it.

    Returns:
        The state directory, or None for any role but the overseer.

    Raises:
        SandboxError: `cwd` holds no workspace file, or no state directory private to this user with a journal in it.
    """
    if role != "overseer":
        return None
    usage = "canopy-sandbox overseer runs only as canopy's overseer_cmd, in the workspace root"
    if not stat.S_ISREG(mode(cwd / WORKSPACE_FILE)):
        raise SandboxError(f"{cwd} holds no {WORKSPACE_FILE}: {usage}")
    state = cwd / STATE_DIR
    try:
        info = state.lstat()
    except OSError:
        raise SandboxError(f"{cwd} holds no {STATE_DIR}: {usage}") from None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SandboxError(f"{state} is not a directory private to this user; remove it")
    if not stat.S_ISREG(mode(state / JOURNAL[0])):
        raise SandboxError(f"{state} holds no journal: {usage}")
    return state


def mode(path: Path) -> int:
    """Return the mode of `path` itself, a link's and not its target's.

    Returns:
        The mode, or 0 when there is nothing there or it cannot be read.
    """
    try:
        return path.lstat().st_mode
    except OSError:
        return 0


def journal_files(state: Path) -> list[Path]:
    """Make the journal's missing locks in `state`, and list the journal's files there, which the overseer writes.

    The overseer cannot add to the state directory, so it could never take a lock canopy has yet to make. The wrapper
    makes it as canopy would, empty and the operator's alone.

    Returns:
        Each of the journal's files there, in the order `JOURNAL` names them.

    Raises:
        SandboxError: a lock could not be made, or one of them is not a regular file: through a link, the policy would
            let the overseer write what it points at.
    """
    for name in LOCKS:
        try:
            os.close(os.open(state / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
        except FileExistsError:
            pass
        except OSError as e:
            raise SandboxError(f"the lock {state / name} could not be made: {e}") from None
    files: list[Path] = []
    for name in JOURNAL:
        kind = mode(state / name)
        if kind and not stat.S_ISREG(kind):
            raise SandboxError(f"{state / name} is not a regular file; remove it")
        if kind:
            files.append(state / name)
    return files


def workspace_entries(cwd: Path, state: Path, journal: Collection[Path]) -> list[Path]:
    """List what the overseer reads: the workspace root's entries but the state directory, then the state directory's.

    Entry by entry, and the journal's files left out, so that no read-only bind of a directory covers them.

    Returns:
        The workspace root's entries but `state`, then `state`'s but `journal`, each by name.
    """
    entries = sorted(p for p in cwd.iterdir() if p != state)
    entries.extend(sorted(p for p in state.iterdir() if p not in journal))
    return entries


def objects_dir(role: str) -> Path | None:
    """Return the run's object directory, which canopy passes to a worker and to setup.

    Returns:
        The directory, or None for a role that commits nothing: a chore or a review.

    Raises:
        SandboxError: a worker or setup has none, so it could commit nothing; or it is not a directory.
    """
    if role not in COMMITTING:
        return None
    value = os.environ.get(OBJECTS_ENV, "")
    if not value:
        raise SandboxError(f"{OBJECTS_ENV} is not set: canopy-sandbox {role} runs only as canopy's {role} command")
    path = Path(value)
    if not path.is_absolute() or not path.is_dir() or UNSAFE_PATH.search(value):
        raise SandboxError(f"{OBJECTS_ENV} is not an absolute path to a directory git can be given: {value!r}")
    return path


def load_template(role: str) -> object:
    """Read the policy template for `role`.

    Returns:
        The template, as JSON.

    Raises:
        SandboxError: it is missing, unreadable, or not JSON.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / "canopy" / "sandbox" / f"{role}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SandboxError(f"no policy template at {path}; run `canopy sandbox setup`") from None
    except (OSError, ValueError) as e:
        raise SandboxError(f"the policy template {path} could not be read: {e}") from None


def find_srt() -> Path:
    """Find the `srt` to run: the one `canopy sandbox setup` installed, or else the first on `PATH`.

    Returns:
        Its path.

    Raises:
        SandboxError: there is neither.
    """
    pinned = runtime_dir() / "node_modules" / ".bin" / "srt"
    if pinned.is_file():
        return pinned
    found = shutil.which("srt")
    if found is None:
        raise SandboxError("srt is not installed; run `canopy sandbox setup`")
    return Path(found).absolute()


def runtime_dir() -> Path:
    """Return where `canopy sandbox setup` installs `srt`: `$XDG_DATA_HOME/canopy/sandbox-runtime`.

    Returns:
        The directory, under `~/.local/share` when XDG_DATA_HOME is unset or empty. It may not exist.
    """
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base).expanduser() / "canopy" / "sandbox-runtime"


def cache_dir(role: str) -> Path:
    """Make, if it is missing, the private cache directory a run as `role` shares with the role's other runs.

    It is under the operator's XDG_CACHE_HOME, read before the wrapper sets the command's, or `~/.cache`.

    Returns:
        The directory, with every link in its path resolved.

    Raises:
        SandboxError: it cannot be made, or it is a link, or not a directory of this user's.
    """
    path = cache_root() / CACHES[role]
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.lstat()
    except OSError as e:
        raise SandboxError(f"the sandbox's cache directory {path} could not be made: {e}") from None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise SandboxError(f"{path} is not a directory of this user's; remove it")
    # mkdir sets the mode only on a directory it makes.
    path.chmod(0o700)
    return path.resolve()


def cache_root() -> Path:
    """The directory that holds each role's cache directory, where `canopy gc --caches` finds them.

    Returns:
        `canopy/sandbox` under the operator's XDG_CACHE_HOME when that is absolute, or else under `~/.cache`. It may not
        exist.
    """
    base = Path(os.environ.get("XDG_CACHE_HOME", ""))
    root = base if base.is_absolute() else Path.home() / ".cache"
    return root / "canopy" / "sandbox"


def make_run_dir() -> Path:
    """Make this run's own directory, for its policy and temp directory, after removing any a dead run left.

    Run directories live in one directory per user under the system temp directory, private to the user, so another
    user cannot plant a policy, and a link there is never followed.

    Returns:
        The new directory.

    Raises:
        SandboxError: the parent directory is not the user's own private directory.
    """
    root = Path(tempfile.gettempdir()) / f"canopy-sandbox-{os.getuid()}"
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        info = root.lstat()
    except OSError as e:
        raise SandboxError(f"{root} could not be made: {e}") from None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SandboxError(f"{root} is not a directory private to this user; remove it")
    for entry in root.iterdir():
        if entry.is_dir() and not entry.is_symlink() and not alive(entry / "pid"):
            remove(entry)
    run_dir = Path(tempfile.mkdtemp(prefix="run.", dir=root))
    # Whole or not there, never empty: a run sweeping at the same moment reads a missing file as a run starting.
    (run_dir / "pid.new").write_text(f"{os.getpid()}\n", encoding="utf-8")
    (run_dir / "pid.new").replace(run_dir / "pid")
    return run_dir


def check_socket_room(tmp: Path) -> None:
    """Refuse a temp directory too long for srt's sockets, which srt reports only as a failure to make them.

    Raises:
        SandboxError: on Linux, a socket in `tmp` would have a path too long to bind.
    """
    socket = tmp / SRT_SOCKET_NAME
    if sys.platform == "linux" and len(os.fsencode(socket)) > SOCKET_PATH_MAX:
        raise SandboxError(
            f"the temp directory {tempfile.gettempdir()} has too long a path for srt's sockets: set TMPDIR to a "
            "shorter one, such as /tmp",
        )


def placeholders(
    cwd: Path,
    trees: Collection[Worktree],
    objects: Path | None,
    tmp: Path,
    *,
    cache: Path,
    reads: list[Path],
    journal: list[Path],
    workspace: list[Path],
) -> dict[str, list[str]]:
    """Return what each placeholder expands to for this run.

    Returns:
        Each placeholder's paths, in order and without repeats.
    """
    values: dict[str, list[Path]] = {
        "@CWD@": [cwd],
        "@WORKTREES@": [t.top for t in trees],
        "@GIT_OWN@": [t.own for t in trees],
        "@GIT_SHARED@": shared_entries(trees),
        "@GIT_PROTECTED@": [p for t in trees for p in (t.top / ".git", *(t.own / n for n in GIT_OWN_PROTECTED))],
        "@OBJECTS@": [objects] if objects is not None else [],
        "@TMPDIR@": [tmp],
        "@CACHE@": [cache],
        "@READ@": reads,
        "@JOURNAL@": journal,
        "@WORKSPACE@": workspace,
    }
    return {name: list(dict.fromkeys(str(p) for p in paths)) for name, paths in values.items()}


def shared_entries(trees: Collection[Worktree]) -> list[Path]:
    """List what each worktree's common git directory holds, but the worktrees' own git directories.

    Returns:
        Each entry of each common directory but `worktrees`, then each entry of its `worktrees` but the run's own.
    """
    own = {t.own.resolve() for t in trees}
    entries: list[Path] = []
    for shared in dict.fromkeys(t.shared for t in trees):
        entries.extend(sorted(p for p in shared.iterdir() if p.name != "worktrees"))
        if (shared / "worktrees").is_dir():
            entries.extend(sorted(p for p in (shared / "worktrees").iterdir() if p.resolve() not in own))
    return entries


def fill(node: object, values: Mapping[str, Iterable[str]]) -> object:
    """Expand every placeholder in `node`, and drop every key that starts with `#`.

    A path a list already holds is not added again: in a slot, `@CWD@` and `@WORKTREES@` are the same directory.

    Returns:
        The policy.

    Raises:
        SandboxError: a placeholder is unknown, or is part of a longer string.
    """
    if isinstance(node, dict):
        items: dict[object, object] = node
        return {k: fill(v, values) for k, v in items.items() if not str(k).startswith("#")}
    if isinstance(node, list):
        filled: list[object] = []
        elements: list[object] = node
        for item in elements:
            if isinstance(item, str) and PLACEHOLDER.fullmatch(item):
                if item not in values:
                    raise SandboxError(f"the policy template names an unknown placeholder, {item}")
                filled.extend(p for p in values[item] if p not in filled)
            else:
                filled.append(fill(item, values))
        return filled
    if isinstance(node, str) and PLACEHOLDER.search(node):
        raise SandboxError(f"a placeholder must be a whole string in a list, not part of {node!r}")
    return node


def check(policy: object, denied: Collection[Path], readable: Iterable[Path]) -> None:
    """Refuse a policy `srt` would run without a sandbox, or with the network open; deny `denied`, allow `readable`.

    `denied` holds the directory of every run's directory: the system temp directory is outside HOME, so without it one
    run could read another's temp directory, a private ticket's included. It holds the directory of every role's cache
    directory, for an XDG_CACHE_HOME outside HOME, and the workspace's `.canopy/` too, when known, for a workspace
    outside HOME. The run's own directories in them are re-allowed by the template. `readable` holds what runs inside
    the sandbox from a denied directory: `srt`'s own helper, under the HOME the template may deny, and the run's `git`,
    in the run's directory.

    Raises:
        SandboxError: it denies no reads, has no network allowlist, its allowRead or allowWrite is not a list, or one
            of them names a directory in `denied`, or one that holds it, which `srt` would bind back.
    """
    sections: dict[object, object] = policy if isinstance(policy, dict) else {}
    filesystem = sections.get("filesystem")
    network = sections.get("network")
    if not isinstance(filesystem, dict) or not filesystem.get("denyRead"):
        raise SandboxError("the policy template denies no reads: give it a filesystem.denyRead")
    deny: object = filesystem["denyRead"]
    if not isinstance(deny, list):
        raise SandboxError("the policy template's filesystem.denyRead is not a list")
    if not isinstance(network, dict) or not isinstance(network.get("allowedDomains"), list):
        raise SandboxError("the policy template has no network.allowedDomains list")
    deny.extend(str(p) for p in denied if str(p) not in deny)
    for key in ("allowWrite", "allowRead"):
        entries: object = filesystem.get(key, [])
        if not isinstance(entries, list):
            raise SandboxError(f"the policy template's filesystem.{key} is not a list")
        for entry in entries:
            if isinstance(entry, str) and (held := _holds(entry, denied)) is not None:
                raise SandboxError(
                    f"the policy template's filesystem.{key} names {entry}, which holds {held}, denied to every "
                    "run so none reads another's: name the directories the command needs instead",
                )
    allow: object = filesystem.setdefault("allowRead", [])
    if not isinstance(allow, list):
        raise SandboxError("the policy template's filesystem.allowRead is not a list")
    allow.extend(str(p) for p in readable if str(p) not in allow)


def _holds(entry: str, denied: Collection[Path]) -> Path | None:
    """Return the directory of `denied` that `entry`, a path `srt` reads with `~` for HOME, is or holds, if any.

    Raises:
        SandboxError: `entry` is no path: it holds a NUL, or names the home of a user there is none of.
    """
    try:
        place = Path(os.path.realpath(Path(entry).expanduser()))
    except (RuntimeError, ValueError) as e:
        raise SandboxError(f"the policy template names {entry!r}, which is not a path: {e}") from e
    for directory in denied:
        real = Path(os.path.realpath(directory))
        if place == real or place in real.parents:
            return directory
    return None


def state_dirs(objects: Path | None, cwd: Path) -> list[Path]:
    """Find the workspace's `.canopy/` from a run's object directory, a chore's default cwd, or a review's directory.

    Returns:
        The state directory, or nothing when neither names one, as for a chore with a `cwd` of its own.
    """
    for place in (objects, cwd):
        if place is not None and place.parent.name in RUN_PARENTS and place.parent.parent.name == STATE_DIR:
            return [place.parent.parent]
    return []


def vendor_dirs(srt: Path) -> list[Path]:
    """Find the `vendor/` directory of the `srt` package at `srt`, whose seccomp helper runs inside the sandbox.

    Returns:
        The directory, or nothing when `srt` is not an installed copy of the package.
    """
    root = srt.resolve().parent.parent
    try:
        name = json.loads((root / "package.json").read_text(encoding="utf-8")).get("name")
    except (OSError, ValueError, AttributeError):
        return []
    vendor = root / "vendor"
    return [vendor] if name == SRT_PACKAGE and vendor.is_dir() else []


def environment(current: Mapping[str, str], bin_dir: Path | None, tmp: Path, cache: Path) -> dict[str, str]:
    """Return the command's environment: the wrapper's, scrubbed at start, plus the run's directories.

    Returns:
        The environment to run `srt` with: TMPDIR the run's, every cache the role's, whatever the operator set them to,
        and `bin_dir`, which holds the run's git, first on PATH.
    """
    env = dict(current)
    env[SRT_TMPDIR] = str(tmp)
    env["TMPDIR"] = str(tmp)
    env.update((name, str(cache / place)) for name, place in CACHE_ENV)
    if bin_dir is not None:
        env["PATH"] = os.pathsep.join(p for p in (str(bin_dir), env.get("PATH", "")) if p)
    return env


def git_shim(run_dir: Path, trees: Collection[Worktree], objects: Path) -> Path:
    """Write the run's `git`, which points git at `objects` in the run's worktrees only, into `run_dir/bin`.

    Returns:
        The directory that holds it, to put first on the command's PATH.

    Raises:
        SandboxError: there is no git, or a shared object directory has a name git's list of alternates cannot hold.
    """
    real = shutil.which("git")
    if real is None:
        raise SandboxError("git is not on PATH")
    shared = list(dict.fromkeys(str(t.shared / "objects") for t in trees))
    unsafe = [p for p in shared if UNSAFE_PATH.search(p)]
    if unsafe:
        raise SandboxError(f"git cannot be given these object directories as alternates: {unsafe}")
    values = {
        "@REAL@": shlex.quote(str(Path(real).absolute())),
        "@OBJECTS@": shlex.quote(str(objects)),
        "@COMMON@": "|".join(shlex.quote(str(c)) for c in dict.fromkeys(t.shared for t in trees)),
        "@ALTERNATES@": shlex.quote(":".join(shared)),
    }
    script = PLACEHOLDER.sub(lambda m: values[m.group()], GIT_SHIM)  # in one pass, so no path is read as a placeholder
    bin_dir = run_dir / "bin"
    bin_dir.mkdir(mode=0o700)
    shim = bin_dir / "git"
    shim.write_text(script, encoding="utf-8")
    shim.chmod(0o500)
    return bin_dir


def run_srt(srt: Path, settings: Path, command: Sequence[str], env: Mapping[str, str]) -> int:
    """Run `command` under `srt` with the policy at `settings`, passing on a signal the wrapper alone is sent.

    Returns:
        `srt`'s exit status, or 128 plus the signal that ended it.
    """
    child = subprocess.Popen([str(srt), "--settings", str(settings), "--", *command], env=env)  # noqa: S603

    def forward(signum: int, _frame: object) -> None:
        child.send_signal(signum)

    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(signum, forward)
    status = child.wait()
    return 128 - status if status < 0 else status


def worktree(place: Path) -> Worktree:
    """Return the worktree at `place` and its git directories.

    Returns:
        The worktree.

    Raises:
        SandboxError: git cannot read it, or it is not a linked worktree, whose HEAD and index are its own.
    """
    queries = ["--show-toplevel", "--git-dir", "--git-common-dir"]
    args = [*SAFE_GIT, "-C", str(place), "rev-parse", "--path-format=absolute", *queries]
    done = subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603
    paths = [Path(line) for line in done.stdout.splitlines()]
    if done.returncode != 0 or len(paths) != len(queries):
        raise SandboxError(f"git could not read the worktree at {place}: {done.stderr.strip()}")
    top, own, shared = paths
    if own == shared or not (top / ".git").is_file():
        raise SandboxError(f"{top} is not a linked worktree, so a sandboxed run cannot keep its HEAD and index apart")
    return Worktree(top, own, shared)


def remove(path: Path) -> None:
    """Delete a run's directory, after giving back the permissions its command may have taken from a directory in it.

    Every process of the run has ended by now, and nothing here follows a link.
    """
    for root, dirs, _ in os.walk(path):
        for name in dirs:
            child = Path(root) / name
            if not child.is_symlink():
                child.chmod(0o700)
    shutil.rmtree(path, ignore_errors=True)
    if os.path.lexists(path):
        print(f"canopy-sandbox: {path} could not be removed; remove it by hand", file=sys.stderr)


def alive(pid_file: Path) -> bool:
    """Whether the process a run directory's `pid` file names is still running.

    Returns:
        True when it is, or when the file cannot be read yet, as in a directory another run is still making.
    """
    try:
        pid = int(pid_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
