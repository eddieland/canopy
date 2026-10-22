"""`runtime.allow_bash`: the commands the operator lets one of canopy's agents run beyond its own bash rules.

An allow in the operator's own runtime config cannot beat canopy's deny: the runtime merges canopy's definitions after
it (D044), and applies the last rule that matches (D021). One in `runtime.allow_bash` is rendered into the agent's
definition, last of its bash rules, so it wins (DESIGN §13). The key is private (TRUST_MODEL T7): only the operator
widens an agent's shell. Whatever they write, canopy refuses what would undo its trust model (TRUST_MODEL T1): an agent
with no shell, a pattern that is not one plain command line, and a command that runs other commands, fetches pages,
writes through git or a forge, or is one of the loop's own tools.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from canopy.runtime import agents
from canopy.runtime.definitions import BASH_ALLOW_RE, RUNTIME_COMMANDS

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: The agents whose shell the key may widen, by the name it keys them by: the overseer and the planner, whose bash rules
#: deny every command but those they name, such as a tracker CLI's reads while its MCP server is down, and the workers,
#: whose rules deny only what they name, so an allow undoes one of those denies that no check below refuses, such as
#: the private worker's of a tracker's CLI (TRUST_MODEL T6).
ROLES: Mapping[str, str] = {
    "overseer": agents.OVERSEER,
    "worker": agents.WORKER,
    "worker-private": agents.PRIVATE_WORKER,
    "planner": agents.PLANNER,
}
#: canopy's other agents, by the name the key would give them, and why none of them takes an allow.
REFUSED_ROLES: Mapping[str, str] = {
    "reviewer": "the reviewer has no shell: it reads code the loop did not write (TRUST_MODEL T4)",
    "chore": "canopy-chore has no shell; a chore that runs commands names an agent of yours in its cmd (DESIGN §19)",
}
#: The most patterns one agent takes, and the longest pattern.
MAX_PATTERNS = 20
MAX_PATTERN = 200

#: Commands that run a command, script, or expression they are given, so allowing one, whatever its arguments, would
#: allow any: shells and the builtins that run text, wrappers, interpreters, the runners of a language's packages and
#: builds, editors, remote and container shells, and commands with an option that runs a program.
RUNS_COMMANDS = frozenset(
    {
        # Shells, and the builtins that run text or a file.
        *("sh", "bash", "rbash", "zsh", "fish", "dash", "ksh", "mksh", "csh", "tcsh", "ash", "yash", "busybox"),
        *("pwsh", "powershell", "nu", "xonsh", "elvish", "osh", "ysh"),
        *("eval", "exec", "source", "command", "builtin", "trap", "coproc", "fc", "enable", "alias", "export"),
        *("declare", "typeset", "set"),
        # Wrappers that run the command after them.
        *("env", "sudo", "doas", "su", "runuser", "pkexec", "xargs", "nohup", "timeout", "nice", "ionice", "stdbuf"),
        *("time", "watch", "setsid", "script", "chroot", "unshare", "nsenter", "flock", "parallel", "strace", "ltrace"),
        *("gdb", "taskset", "systemd-run", "at", "batch", "crontab", "screen", "tmux", "expect", "entr", "open"),
        *("xdg-open", "osascript", "chrt", "prlimit", "setpriv", "sg", "unbuffer", "firejail", "bwrap"),
        *("caffeinate", "srt"),
        # Interpreters, and the runners of a language's packages, tasks, and builds. `python3.12` and the like are
        # refused by family, below.
        *("deno", "bun", "npx", "npm", "pnpm", "pnpx", "yarn", "corepack", "uv", "uvx", "pipx", "poetry", "pdm"),
        *("hatch", "tox", "nox", "conda", "mamba", "irb", "luajit", "java", "jshell", "scala", "kotlin", "groovy"),
        *("r", "rscript", "julia", "awk", "gawk", "mawk", "nawk", "sed", "make", "cmake", "ninja", "bazel", "cargo"),
        *("go", "gradle", "mvn", "just", "task", "rake", "bunx", "ts-node", "tsx", "ipython", "bpython", "jupyter"),
        *("elixir", "iex", "erl", "escript", "swift", "dotnet", "ghci", "runghc", "sbcl", "guile", "racket", "clojure"),
        # Editors, which run a command from their arguments.
        *("vi", "vim", "nvim", "ex", "ed", "emacs"),
        # Remote and container shells.
        *("ssh", "scp", "sftp", "rsync", "docker", "podman", "nerdctl", "kubectl"),
        # Commands with an option that runs a program: `find -exec`, `fd -x`, `rg --pre`, `tar -I`, `zip -TT`,
        # `sort --compress-program`, `split --filter`, `man -P`, and m4's `syscmd`.
        *("find", "fd", "rg", "tar", "zip", "sort", "split", "man", "m4"),
        # Pagers, editors, and shells that run a command from their input: `less`'s `!`, `nano`'s speller, `dc`'s
        # `!`, sqlite3's `.shell`, psql's `\!`, and mysql's `system`.
        *("less", "more", "most", "pg", "nano", "dc", "sqlite3", "psql", "mysql", "mariadb", "duckdb"),
    },
)
#: Commands that fetch a page, which anyone can shape: no agent has web tools (D077).
WEB_COMMANDS = frozenset(
    {
        *("curl", "wget", "http", "https", "xh", "aria2c", "lynx", "w3m", "links", "nc", "ncat", "netcat", "socat"),
        *("telnet", "ftp"),
    },
)
#: git and the forges' CLIs: they push, merge, and close, which canopy keeps from every agent but its workers, and git
#: runs hooks and configured commands.
VCS_COMMANDS = frozenset({"gh", "glab", "hub"})

# The families of interpreters, refused with any version (`python3`, `python3.12`, `pip3`), and of canopy's own
# programs, git's, and treehouse's, refused with any suffix (`canopy-post-github`, `git-receive-pack`).
_INTERPRETERS_RE = re.compile(r"(?:python|pypy|pip|perl|ruby|php|lua|node|nodejs|tclsh|wish)[0-9.]*")
_LOOP_RE = re.compile(r"(?:canopy|treehouse)(?:-.*)?")
_GIT_RE = re.compile(r"git(?:-.*)?")


def by_agent(allow_bash: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, ...]]:
    """Return `runtime.allow_bash`'s patterns by the name of the agent each role is.

    Returns:
        Each agent with at least one pattern, by its name, and its patterns in the order config gives them.
    """
    return {ROLES[role]: tuple(patterns) for role, patterns in allow_bash.items() if patterns}


def check_role(role: str) -> str:
    """Return `role` if `runtime.allow_bash` may name it.

    Raises:
        ValueError: it is another of canopy's agents, with why, or no agent of canopy's.
    """
    if role in ROLES:
        return role
    why = REFUSED_ROLES.get(role)
    if why is not None:
        raise ValueError(f"{role!r} takes no bash allows: {why}")
    raise ValueError(f"{role!r} is not an agent bash allows may name; name {', '.join(ROLES)}")


def check_pattern(pattern: str) -> str:
    """Return `pattern` if canopy renders it as an allow: one plain command line, of a command that may be allowed.

    Raises:
        ValueError: it is too long, is not one plain command line with a literal command first, or allows a command
            that runs others, fetches pages, writes through git or a forge, or is one of the loop's own.
    """
    if len(pattern) > MAX_PATTERN or not BASH_ALLOW_RE.fullmatch(pattern):
        raise ValueError(
            f"{pattern!r} must be one command line of at most {MAX_PATTERN} characters: a command's name, with no "
            "wildcard or path in it, then arguments of letters, digits, single spaces between words, the wildcards "
            "`*` and `?`, and `._,:=@%+/-`; no quote, `$`, `;`, `&`, `|`, `<`, `>`, backslash, or brace",
        )
    why = _refused(pattern.split(" ", 1)[0].lower())
    if why is not None:
        raise ValueError(f"{pattern!r} allows {why}")
    return pattern


def check_patterns(patterns: tuple[str, ...]) -> tuple[str, ...]:
    """Return one agent's patterns if there are few enough and none repeats.

    Raises:
        ValueError: there are more than `MAX_PATTERNS`, or one is named twice.
    """
    if len(patterns) > MAX_PATTERNS:
        raise ValueError(f"at most {MAX_PATTERNS} patterns an agent")
    twice = sorted({p for p in patterns if patterns.count(p) > 1})
    if twice:
        raise ValueError(f"names {', '.join(repr(p) for p in twice)} more than once")
    return patterns


def _refused(command: str) -> str | None:
    """Return why `command`, lowercased, may not be allowed, or None when it may.

    Lowercased, since a file system that ignores case runs `Bash` as `bash`.
    """
    if _LOOP_RE.fullmatch(command) or command in RUNTIME_COMMANDS:
        return f"{command!r}, one of the loop's own tools, whose reach canopy's rules decide"
    if command in RUNS_COMMANDS or _INTERPRETERS_RE.fullmatch(command):
        return f"{command!r}, which runs a command it is given, and would allow any"
    if command in WEB_COMMANDS:
        return f"{command!r}, which fetches pages anyone can shape: no agent has web tools (D077)"
    if command in VCS_COMMANDS or _GIT_RE.fullmatch(command):
        return f"{command!r}, which can push, merge, or close, or run hooks: canopy's rules decide who may"
    return None
