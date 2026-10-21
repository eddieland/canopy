"""Read-only git for the reviewer and the planner, served as the tools of canopy's `canopy_git` server (DESIGN §27).

The reviewer and the planner have no shell. These four tools read a checkout's history instead: where two commits'
histories meet (`merge-base`), the diff between two commits (`diff`), the commits of a range (`log`), and a file or a
directory at a commit (`show`). `canopy _mcp --git` serves them to a review's or a plan's run alone, whose environment
names the checkouts it may read (`CHECKOUTS_ENV`). canopy sets that per run, never from an agent's arguments: an
argument only picks one of those checkouts by the name its agent knows it by.

Every argument is checked before git runs. A revision is a branch, tag, or commit id with `~N` or `^N` after it at most:
never an option, a path, a reflog, or a search, and a range only where `log` takes one. A path is relative and stays
inside the checkout. Each revision is resolved to a commit first, so the commands after it see commit ids. git reads
objects alone, never the worktree, with what the repository's config or a commit's `.gitattributes` could make it run
turned off (`ENV`, `_GLOBAL_FLAGS`, and each command's own flags), and nothing it prints reaches the agent past a
bound, every hidden character named.

Rejected: a shell with git allowed by pattern. The runtime matches a command's words, not its redirections or a
leading variable assignment, so an allowed git could overwrite a file or run any program.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, StrictStr

from canopy.core import hostgit
from canopy.core.memory_text import hidden_char, visible
from canopy.infra import procs
from canopy.runtime import servers

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The MCP server canopy gives a review's or a plan's run, as its inline config names it, and its tools. The runtime
#: joins the two as `canopy_git_diff` and so on; no tool's name holds an underscore, as none of canopy's does (§27).
SERVER = "canopy_git"
MERGE_BASE, DIFF, LOG, SHOW = "merge-base", "diff", "log", "show"
TOOLS = (MERGE_BASE, DIFF, LOG, SHOW)
#: How the runtime starts that server: this interpreter's canopy. `-P` keeps the working directory off the import path,
#: so no file there can stand in for canopy's own modules (TRUST_MODEL T7).
SERVER_COMMAND = (sys.executable, "-P", "-m", "canopy", "_mcp", "--git")
#: Set for a review's or a plan's agent, and so for its server: a JSON object of each checkout's name, as its agent
#: knows it, to its absolute path.
CHECKOUTS_ENV = "CANOPY_GIT_CHECKOUTS"
#: How many commits `log` lists unless it asks for another number, and the most it may ask for.
DEFAULT_LIMIT = 20
MAX_LIMIT = 200
#: The most paths one call may name.
MAX_PATHS = 50
#: What an answer holds at most: bytes of git's output read, lines kept of it, and characters kept of a line.
MAX_BYTES = 64 * 1024
MAX_LINES = 2000
MAX_LINE_CHARS = 1000
#: The largest file `show` reads; a larger one is named, not shown.
MAX_FILE_BYTES = 1024 * 1024
#: How long one git command may run.
TIMEOUT_SECONDS = 60
#: What an answer cut at a bound ends with.
CUT_NOTE = (
    f"[canopy cut this at {MAX_LINES} lines or {MAX_BYTES} bytes: ask for less, such as fewer paths, a narrower range, "
    "or a lower limit]"
)
#: Set on every git these tools run. No system config or attributes; no lazy fetch of a missing object, nor a
#: replacement object standing in for one; no lock it could take to refresh an index; no prompt; and none of the config
#: a `GIT_CONFIG_COUNT` inherited from the operator's environment would add.
ENV = {
    **hostgit.ENV,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_CONFIG_COUNT": "0",
}
#: Set on each call to the checkout's parent, so git never reads a repository above a checkout that has none.
CEILING_ENV = "GIT_CEILING_DIRECTORIES"

# Config each git runs with, which overrides the repository's: no external diff, no signature checks and so no GPG
# program, and no mailmap or order file. Paths are quoted, so a name that is not UTF-8 reaches canopy as text.
_CONFIG = (
    ("diff.external", ""),
    ("diff.orderFile", "/dev/null"),
    ("log.showSignature", "false"),
    ("log.mailmap", "false"),
    ("core.quotePath", "true"),
)
# Before the subcommand: no pager, every pathspec literal, so `:(...)` magic and wildcards are plain names, and every
# transport refused.
_GLOBAL_FLAGS = (
    "--no-pager",
    "--literal-pathspecs",
    "--no-optional-locks",
    *(arg for key, value in _CONFIG for arg in ("-c", f"{key}={value}")),
    *hostgit.NO_TRANSPORT,
)
# A revision: a name, then `~N` and `^N` suffixes. No `:` (a path or a search), `@` (a reflog), braces, or whitespace.
_REVISION_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./+~^-]{0,254}")
_CHECKOUT_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_MAX_PATH_CHARS = 4096
_SHOWN_CHARS = 80


class Refused(Exception):  # noqa: N818  (an outcome the agent is told about, not an error)
    """A read cannot be done as asked. `guard` names why; its text is what the tool says."""

    def __init__(self, guard: str, reason: str) -> None:
        """Name the guard and say why it refused."""
        super().__init__(f"git read refused ({guard}): {reason}")
        self.guard = guard
        self.reason = reason


def _revision(value: str) -> str:
    if value.startswith("-"):
        raise ValueError(f"{_shown(value)} starts with '-': a revision is never an option")
    if ".." in value:
        raise ValueError(f"{_shown(value)} is a range: give one revision")
    if not _REVISION_RE.fullmatch(value):
        raise ValueError(
            f"{_shown(value)} is not a revision canopy takes: a branch, tag, or commit id, with ~N or ^N after it at "
            "most; no whitespace, ':', '@', or braces",
        )
    return value


def _range(value: str) -> str:
    for between in ("...", ".."):
        if between in value:
            left, _, right = value.partition(between)
            _revision(left)
            _revision(right)
            return value
    return _revision(value)


def _path(value: str) -> str:
    """A path inside the checkout, relative to its root, with `.` and empty parts dropped.

    Returns:
        The path, its parts joined by `/`.

    Raises:
        ValueError: It is empty, absolute, holds a hidden character, or leaves the checkout.
    """
    if len(value) > _MAX_PATH_CHARS or any(hidden_char(c) for c in value):
        raise ValueError(f"{_shown(value)} is not a path canopy takes: too long, or a hidden character in it")
    if value.startswith("/"):
        raise ValueError(f"{_shown(value)} is absolute: give a path inside the checkout, relative to its root")
    parts = [part for part in value.split("/") if part not in {"", "."}]
    if ".." in parts:
        raise ValueError(f"{_shown(value)} leaves the checkout: '..' is not taken")
    if not parts:
        raise ValueError(f"{_shown(value)} names no file: give a path inside the checkout")
    return "/".join(parts)


def _place(value: str) -> str:
    """A path for `show`, which may also be the checkout's root, `.` or empty.

    Returns:
        The path, or the empty string for the root.
    """
    root = not value.startswith("/") and all(part in {"", "."} for part in value.split("/"))
    return "" if root else _path(value)


type Revision = Annotated[StrictStr, AfterValidator(_revision)]
type Paths = Annotated[
    tuple[Annotated[StrictStr, AfterValidator(_path)], ...],
    Field(
        max_length=MAX_PATHS,
        description="Only these files or directories, each relative to the checkout's root. Omit for all.",
    ),
]


class _Read(BaseModel):
    """What every read names: the checkout it reads."""

    # An unknown field is refused, as the overseer's requests refuse one (`loop.tools`).
    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    #: The checkout to read, by the name its agent knows it by; None when the run has one.
    checkout: Annotated[
        StrictStr | None,
        Field(
            description="The checkout to read, by its name in your working directory, where a link of that name leads "
            "to it. Omit it when your run has one.",
        ),
    ] = None


class MergeBase(_Read):
    """Where two revisions' histories meet."""

    #: One revision, such as the base branch.
    base: Annotated[Revision, Field(description="A branch, tag, or commit, such as origin/main.")]
    #: The other, such as the reviewed commit.
    head: Annotated[Revision, Field(description="A branch, tag, or commit, such as HEAD.")]


class Diff(_Read):
    """The diff between two commits."""

    #: The commit to diff from.
    base: Annotated[Revision, Field(description="The commit to diff from: a branch, tag, or commit.")]
    #: The commit to diff to.
    head: Annotated[Revision, Field(description="The commit to diff to: a branch, tag, or commit.")]
    #: Only these paths, if any.
    paths: Paths = ()


class Log(_Read):
    """The commits of a range, newest first."""

    #: A revision, for its history, or `A..B` or `A...B`.
    range: Annotated[
        StrictStr,
        AfterValidator(_range),
        Field(
            description="A revision, for the commits it has; A..B for those B has and A does not; or A...B for those "
            "either has and the other does not.",
        ),
    ]
    #: Only the commits that touch these paths, if any.
    paths: Paths = ()
    #: The most commits to list.
    limit: Annotated[StrictInt, Field(ge=1, le=MAX_LIMIT, description="List at most this many commits.")] = (
        DEFAULT_LIMIT
    )


class Show(_Read):
    """A file or a directory at a commit."""

    #: The commit to read it at.
    rev: Annotated[Revision, Field(description="The commit to read it at: a branch, tag, or commit.")]
    #: The file or directory.
    path: Annotated[
        StrictStr,
        AfterValidator(_place),
        Field(description="The file, or a directory to list, relative to the checkout's root; . for the root."),
    ]


def run_env(checkouts: Mapping[str, Path], *, cwd: Path) -> dict[str, str]:
    """The environment that gives a run canopy's git tools over `checkouts`, each by the name its agent knows it by.

    Returns:
        The variables to set on the run's agent: the checkouts, and the server in the runtime's config, run in `cwd`.
    """
    named = {name: str(path.absolute()) for name, path in checkouts.items()}
    return {CHECKOUTS_ENV: json.dumps(named), **servers.env(SERVER, SERVER_COMMAND, cwd=cwd.absolute())}


def tool_names() -> tuple[str, ...]:
    """The names an agent, and the definitions' rules, know the tools by.

    Returns:
        `canopy_git_merge-base` and the rest, as the runtime names them.
    """
    return tuple(servers.tool_name(SERVER, tool) for tool in TOOLS)


def inherited(environ: Mapping[str, str]) -> frozenset[str]:
    """The variables of git's in `environ` that git must not inherit here: every one these tools do not set.

    Returns:
        Their names, for the server's runner to remove: `GIT_DIR`, `GIT_EXTERNAL_DIFF`, `GIT_CONFIG_PARAMETERS`, and
        the like would otherwise choose the repository, a program, or config.
    """
    return frozenset(name for name in environ if name.startswith("GIT_") and name not in {*ENV, CEILING_ENV})


def checkouts(environ: Mapping[str, str]) -> dict[str, Path]:
    """The checkouts this run may read, as canopy named them in its environment.

    Returns:
        Each checkout's name, as its agent knows it, and its path.

    Raises:
        Refused: (`no_checkouts`) The variable is unset, or not what canopy writes.
    """
    raw = environ.get(CHECKOUTS_ENV)
    if not raw:
        raise Refused("no_checkouts", f"{CHECKOUTS_ENV} is unset: these tools serve a review's or a plan's run alone")
    try:
        named: object = json.loads(raw)
    except ValueError:
        named = None
    if not isinstance(named, dict) or not named:
        raise Refused("no_checkouts", f"{CHECKOUTS_ENV} names no checkout")
    found = {
        name: Path(path)
        for name, path in named.items()
        if isinstance(name, str) and _CHECKOUT_RE.fullmatch(name) and isinstance(path, str) and Path(path).is_absolute()
    }
    if len(found) != len(named):
        raise Refused("no_checkouts", f"{CHECKOUTS_ENV} is not canopy's: each checkout is a name and an absolute path")
    return found


def merge_base(runner: procs.Runner, request: MergeBase, environ: Mapping[str, str]) -> str:
    """Find where `request`'s two revisions' histories meet.

    Returns:
        The commit's id.

    Raises:
        Refused: The checkout is not this run's, a revision names no commit, git failed, or they share no history.
    """
    git = _Git.of(runner, request, environ)
    base, head = git.commit(request.base), git.commit(request.head)
    done = git.result("merge-base", "--end-of-options", base, head)
    if done.returncode == 1 and not done.stdout.strip():
        raise Refused("no_merge_base", f"{request.base} and {request.head} share no history")
    return git.ok(done, MERGE_BASE).strip()


def diff(runner: procs.Runner, request: Diff, environ: Mapping[str, str]) -> str:
    """The diff between `request`'s two commits, each file's count of changed lines first.

    Returns:
        The diff, bounded, or a sentence saying there is none.

    Raises:
        Refused: The checkout is not this run's, a revision names no commit, or git failed.
    """
    git = _Git.of(runner, request, environ)
    base, head = git.commit(request.base), git.commit(request.head)
    # A submodule's change is its commit ids alone: a diff of its own would run git in its repository.
    options = ("--no-color", "--no-ext-diff", "--no-textconv", "--submodule=short", "--find-renames", "--no-relative")
    said = git.bounded("diff", *options, "--stat=200", "--patch", end=(base, head), paths=request.paths)
    return said or f"No changes between {request.base} and {request.head}{_touching(request.paths)}."


def log(runner: procs.Runner, request: Log, environ: Mapping[str, str]) -> str:
    """The commits of `request`'s range, newest first: each one's id, author, date, and message.

    Returns:
        The log, bounded, or a sentence saying it holds no commit.

    Raises:
        Refused: The checkout is not this run's, a revision names no commit, or git failed.
    """
    git = _Git.of(runner, request, environ)
    between = next((b for b in ("...", "..") if b in request.range), None)
    if between is None:
        commits = git.commit(request.range)
    else:
        left, _, right = request.range.partition(between)
        commits = f"{git.commit(left)}{between}{git.commit(right)}"
    options = ("--no-color", "--no-decorate", "--no-show-signature", "--no-mailmap", "--format=medium")
    limit = f"--max-count={request.limit}"
    said = git.bounded("log", *options, "--date=iso-strict", limit, end=(commits,), paths=request.paths)
    return said or f"No commits in {request.range}{_touching(request.paths)}."


def show(runner: procs.Runner, request: Show, environ: Mapping[str, str]) -> str:
    """A file's text at `request`'s commit, or a directory's entries, a directory's name ending in `/`.

    Returns:
        The text or the entries, bounded; or a sentence saying the file is too large, binary, or not UTF-8 text.

    Raises:
        Refused: The checkout is not this run's, the revision names no commit, the path is not there, or git failed.
    """
    git = _Git.of(runner, request, environ)
    commit = git.commit(request.rev)
    shown = request.path or "."
    spec = f"{commit}:{request.path}"
    kind = git.result("cat-file", "-t", "--end-of-options", spec)
    if not kind.ok:
        raise Refused("not_found", f"{shown} is not in {request.rev}")
    match kind.stdout.strip():
        case "tree":
            listed = git.ok(git.result("ls-tree", "--end-of-options", spec), SHOW)
            return _bounded("\n".join(_entry(line) for line in listed.splitlines()).encode()) or f"{shown} is empty."
        case "blob":
            size = int(git.ok(git.result("cat-file", "-s", "--end-of-options", spec), SHOW).strip() or 0)
            if size > MAX_FILE_BYTES:
                return f"{shown} at {request.rev} is {size} bytes, more than canopy shows ({MAX_FILE_BYTES}): use diff."
            try:
                text = git.ok(git.result("cat-file", "blob", "--end-of-options", spec), SHOW)
            except UnicodeDecodeError:
                return f"{shown} at {request.rev} is {size} bytes and not UTF-8 text: not shown."
            if "\0" in text:
                return f"{shown} at {request.rev} is a binary file of {size} bytes: not shown."
            return _bounded(text.encode())
        case other:
            raise Refused("not_a_file", f"{shown} at {request.rev} is a {_shown(other)}, not a file or a directory")


class _Git:
    """git in one checkout, as these tools run it."""

    def __init__(self, runner: procs.Runner, name: str, root: Path) -> None:
        self.runner = runner
        self.name = name
        self.root = root

    @classmethod
    def of(cls, runner: procs.Runner, request: _Read, environ: Mapping[str, str]) -> _Git:
        """Find the checkout `request` names, or the run's one, to run git in.

        Returns:
            Git in it.

        Raises:
            Refused: The run has no checkouts, several and the request names none, or none of the name it gives.
        """
        named = checkouts(environ)
        if request.checkout is None:
            if len(named) != 1:
                raise Refused("which_checkout", f"name a checkout: this run reads {', '.join(sorted(named))}")
            [(name, root)] = named.items()
            return cls(runner, name, root)
        root = named.get(request.checkout)
        if root is None:
            known = ", ".join(sorted(named))
            raise Refused("unknown_checkout", f"no checkout {_shown(request.checkout)}: this run reads {known}")
        return cls(runner, request.checkout, root)

    def result(self, *args: str, output: Path | None = None) -> procs.Result:
        """Run `git <args>` in the checkout, with every option above, `--output=<output>` after the subcommand if given.

        Returns:
            What it did.

        Raises:
            Refused: (`git_failed`) git could not start, as when the checkout is gone, or timed out.
        """
        command, rest = args[0], args[1:]
        written = (f"--output={output}",) if output is not None else ()
        argv = hostgit.argv(*_GLOBAL_FLAGS, command, *written, *rest)
        env = {**ENV, CEILING_ENV: str(self.root.parent)}
        try:
            done = self.runner.run(argv, cwd=self.root, env=env, timeout=TIMEOUT_SECONDS)
        except procs.ProcError as e:
            raise Refused("git_failed", f"git {command} in {self.name}: {e}") from None
        if done.timed_out:
            raise Refused("git_failed", f"git {command} took longer than {TIMEOUT_SECONDS} seconds")
        return done

    def ok(self, done: procs.Result, tool: str) -> str:
        """`done`'s output, if git succeeded.

        Returns:
            Its stdout.

        Raises:
            Refused: (`git_failed`) git exited nonzero; the refusal holds the first line it printed.
        """
        if done.ok:
            return done.stdout
        said = next((line for line in done.stderr.splitlines() if line.strip()), f"exit {done.returncode}")
        raise Refused("git_failed", f"{tool} in {self.name}: {visible(said[:300])}")

    def commit(self, revision: str) -> str:
        """Resolve `revision` to a commit's id.

        Returns:
            The id, in full.

        Raises:
            Refused: (`unknown_revision`) It names no commit here.
        """
        done = self.result("rev-parse", "--verify", "--quiet", "--end-of-options", f"{revision}^{{commit}}")
        found = done.stdout.strip()
        if not done.ok or not _COMMIT_RE.fullmatch(found):
            raise Refused("unknown_revision", f"{revision} names no commit in {self.name}")
        return found

    def bounded(self, command: str, *options: str, end: Sequence[str], paths: Sequence[str]) -> str:
        """Run `git <command> <options>` on the commits `end` names, for `paths`, into a file, and read it bounded.

        git writes to a file of canopy's, never a pipe, so what it prints is read only up to the bound, as bytes, and a
        file that is not UTF-8 text fails nothing.

        Returns:
            Its output, bounded; empty when it printed nothing.

        Raises:
            Refused: (`git_failed`) git failed.
        """
        with tempfile.TemporaryDirectory(prefix="canopy-git-") as directory:
            output = Path(directory) / "output"
            done = self.result(command, *options, "--end-of-options", *end, "--", *paths, output=output)
            self.ok(done, command)
            try:
                with output.open("rb") as f:
                    read = f.read(MAX_BYTES + 1)
            except FileNotFoundError:
                return ""
        return _bounded(read)


def _bounded(read: bytes) -> str:
    """What the agent is told of `read`, git's output: at most `MAX_BYTES` and `MAX_LINES`, each hidden character named.

    A line keeps at most `MAX_LINE_CHARS` characters, without its carriage return; tabs stay as they are.

    Returns:
        The lines, ending with `CUT_NOTE` when a bound cut any.
    """
    cut = len(read) > MAX_BYTES
    lines = read[:MAX_BYTES].decode("utf-8", errors="replace").split("\n")
    if lines[-1] == "" or cut:
        # The last line read is empty after a final newline, or may be cut short.
        lines.pop()
    if len(lines) > MAX_LINES:
        lines, cut = lines[:MAX_LINES], True
    shown = [_line(line) for line in lines]
    return "\n".join([*shown, CUT_NOTE] if cut else shown)


def _line(line: str) -> str:
    kept = line.removesuffix("\r")
    if len(kept) > MAX_LINE_CHARS:
        kept = f"{kept[:MAX_LINE_CHARS]} [line cut at {MAX_LINE_CHARS} characters]"
    return "\t".join(visible(part) for part in kept.split("\t"))


def _entry(line: str) -> str:
    """One of `git ls-tree`'s lines as `show` lists it: the entry's name, a directory's ending in `/`.

    Returns:
        The name.
    """
    meta, _, name = line.partition("\t")
    return f"{name}/" if meta.split(" ")[1:2] == ["tree"] else name


def _touching(paths: Sequence[str]) -> str:
    return f" in {', '.join(paths)}" if paths else ""


def _shown(value: str) -> str:
    """A value an agent gave, fit to echo in a refusal: quoted, its hidden characters escaped, and cut.

    Returns:
        Its `repr`, cut to `_SHOWN_CHARS` characters.
    """
    return repr(value if len(value) <= _SHOWN_CHARS else f"{value[:_SHOWN_CHARS]}...")
