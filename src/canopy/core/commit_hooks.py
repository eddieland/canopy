"""canopy's git hooks, which put its marks on every commit a worker makes: its trailers and prefix (TRUST_MODEL T5).

The marks are formed by the harness and added by git, not by the agent: a worker run's environment points git's
`core.hooksPath` at the hooks in canopy's snapshot (DESIGN §13), through `GIT_CONFIG_COUNT` and its keys, and names
the marks in `CANOPY_COMMIT_TRAILERS` and `CANOPY_COMMIT_PREFIX`. `prepare-commit-msg` puts the prefix before a subject
that lacks it, but a `fixup!`, `squash!`, or `amend!` one, which `--autosquash` matches by its subject, and adds each
trailer the message lacks; git runs it for a commit, an amend, a merge, a rebase, a cherry-pick, and a revert,
`--no-verify` or not, and only plumbing such as `commit-tree` makes a commit without it. Every hook, that one
included, then runs the repository's own hook of its name, the one git would have run without canopy's entry, so the
operator's hooks run as before (docs/HOOKS.md).

canopy's entry is the last of the `GIT_CONFIG_*` ones, after any the operator's environment holds, so a hook finds
the repository's own hooks by asking git with one entry fewer, or more where a tool added its own after canopy's.
`GIT_CONFIG_COUNT` needs git 2.31; an older git ignores it and adds no marks, so each tick checks the git on `PATH`
(`git_too_old`), and the run's note names the commits. The variables reach every git the worker's tools run, in any
repository: what they add there is canopy's marks, and what they run, that repository's own hooks.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import hostgit, prompts
from canopy.infra import procs

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from canopy.core.config import Config

#: The directory in canopy's snapshot that holds the hooks.
HOOKS_DIR = "git-hooks"
#: The trailers the hooks add, one to a line.
TRAILERS_ENV = "CANOPY_COMMIT_TRAILERS"
#: The text the hooks put before a commit's subject.
PREFIX_ENV = "CANOPY_COMMIT_PREFIX"
#: The oldest git that reads `GIT_CONFIG_COUNT`, through which a worker's git finds the hooks.
MIN_GIT = (2, 31)
#: How `git --version` names its version, as Linux, macOS, and Windows builds print it.
_GIT_VERSION_RE = re.compile(r"git version (\d+)\.(\d+)")
_GIT_VERSION_TIMEOUT_SECONDS = 30
#: The client-side hooks git runs from its hooks directory, each of which canopy's must hand on to the repository's.
NAMES = (
    "applypatch-msg",
    "commit-msg",
    "post-applypatch",
    "post-checkout",
    "post-commit",
    "post-index-change",
    "post-merge",
    "post-rewrite",
    "pre-applypatch",
    "pre-auto-gc",
    "pre-commit",
    "pre-merge-commit",
    "pre-push",
    "pre-rebase",
    "prepare-commit-msg",
    "reference-transaction",
    "sendemail-validate",
)
#: Each hook, under each name: POSIX sh, so a hook costs a shell and one git, not a Python start.
SCRIPT = r"""#!/bin/sh
# canopy's git hook (TRUST_MODEL T5): puts canopy's prefix and trailers on the message, as prepare-commit-msg, then
# runs the repository's own hook of this name.
name=${0##*/}
if [ "$name" = prepare-commit-msg ] && [ -n "${CANOPY_COMMIT_PREFIX-}" ] && [ -s "$1" ]; then
    # Not an empty subject or a comment, which git drops, nor one --autosquash matches the commit it is for by.
    case $(head -n 1 "$1") in
        "$CANOPY_COMMIT_PREFIX"* | "" | "#"* | fixup!* | squash!* | amend!*) ;;
        *) { printf '%s' "$CANOPY_COMMIT_PREFIX" && cat "$1"; } >"$1.canopy" && mv "$1.canopy" "$1" || exit ;;
    esac
fi
if [ "$name" = prepare-commit-msg ] && [ -n "${CANOPY_COMMIT_TRAILERS-}" ]; then
    # A message whose last line has no newline, as a merge's has, would take the trailers into its last paragraph.
    if [ -s "$1" ] && [ -n "$(tail -c 1 "$1")" ]; then
        echo >>"$1" || exit
    fi
    printf '%s\n' "$CANOPY_COMMIT_TRAILERS" | while IFS= read -r trailer; do
        if [ -n "$trailer" ]; then
            git interpret-trailers --in-place --if-exists addIfDifferent --trailer "$trailer" "$1" || exit
        fi
    done || exit
fi
# The hooks directory git would use without canopy's entry: dropping GIT_CONFIG_COUNT's entries from the last, the
# first that is not this one's. A tool may have added its own after canopy's, and handing on to this hook again would
# never end.
here=$(cd -P "${0%/*}" && pwd) || exit
n=${GIT_CONFIG_COUNT:-0}
while [ "$n" -gt 0 ]; do
    n=$((n - 1))
    hooks=$(GIT_CONFIG_COUNT=$n git rev-parse --git-path hooks) || exit
    if [ "$(cd -P "$hooks" 2>/dev/null && pwd)" != "$here" ]; then
        if [ -x "$hooks/$name" ]; then
            exec "$hooks/$name" "$@"
        fi
        exit 0
    fi
done
"""


def files() -> dict[str, bytes]:
    """Return the hooks as the snapshot holds them, by relative path.

    Returns:
        The script under each of git's hook names, in `HOOKS_DIR`.
    """
    data = SCRIPT.encode()
    return {f"{HOOKS_DIR}/{name}": data for name in NAMES}


def is_hook(rel: str) -> bool:
    """Return whether `rel`, a path in the snapshot, is one of the hooks, which must be executable."""
    return rel.startswith(f"{HOOKS_DIR}/")


@dataclass(frozen=True)
class Marks:
    """What canopy's hooks put on each commit a run makes, as its prompt names them."""

    #: The trailers, each `Co-authored-by: <name> <<email>>`; none while `trust.commit_trailer` is off.
    trailers: Sequence[str] = ()
    #: What starts each subject, but a fixup's (`prompts.commit_prefix`); "" for none.
    prefix: str = ""


#: No marks: what a run that makes no commit gets.
NONE = Marks()


def marks(
    config: Config,
    *,
    key: str | None,
    model: str | None = None,
    planner_model: str | None = None,
) -> Marks:
    """Return what canopy puts on the commits of a run for ticket `key`, None for a task's.

    `model` is the worker's chosen model, which its trailer may name (`prompts.commit_trailer`), and `planner_model`
    that of the planner whose approved plan it follows, which a second trailer names (`prompts.planner_trailer`).

    Returns:
        The trailers and the prefix.
    """
    prefix = prompts.commit_prefix(config, key)
    if not config.trust.commit_trailer:
        return Marks(prefix=prefix)
    planner = prompts.planner_trailer(config, planner_model)
    return Marks((prompts.commit_trailer(config, model), *([planner] if planner is not None else [])), prefix)


def env(snapshot: Path, added: Marks, inherited: Mapping[str, str]) -> dict[str, str]:
    """Return what a worker's environment needs for git to put `added` on its commits, through the hooks in `snapshot`.

    `inherited` is the environment the worker would otherwise get, whose `GIT_CONFIG_*` entries come first.

    Returns:
        The variables to merge over `inherited`, or none when there is nothing to add.
    """
    if not added.trailers and not added.prefix:
        return {}
    count = inherited.get("GIT_CONFIG_COUNT", "")
    # git refuses a count that is not a number, whatever canopy adds, so one that is not is replaced, not kept.
    index = int(count) if count.isdigit() else 0
    return {
        "GIT_CONFIG_COUNT": str(index + 1),
        f"GIT_CONFIG_KEY_{index}": "core.hooksPath",
        f"GIT_CONFIG_VALUE_{index}": str(snapshot.absolute() / HOOKS_DIR),
        **({TRAILERS_ENV: "\n".join(added.trailers)} if added.trailers else {}),
        **({PREFIX_ENV: added.prefix} if added.prefix else {}),
    }


def git_too_old(config: Config, runner: procs.Runner) -> str | None:
    """Return why canopy's marks cannot reach a worker's commits, when the git on `PATH` is older than `MIN_GIT`.

    Only while there are marks to add: canopy's trailer, or a prefix. A git that does not say its version, or cannot be
    run, is no finding here: a run's own git steps fail on it, and say so.

    Returns:
        The attention item's detail, or None.
    """
    if not config.trust.commit_trailer and not config.trust.commit_prefix:
        return None
    try:
        result = runner.run(["git", "--version"], env=hostgit.ENV, timeout=_GIT_VERSION_TIMEOUT_SECONDS)
    except procs.ProcError:
        return None
    found = _GIT_VERSION_RE.search(result.stdout) if result.ok else None
    if found is None or (int(found[1]), int(found[2])) >= MIN_GIT:
        return None
    least = ".".join(map(str, MIN_GIT))
    return (
        f"git {found[1]}.{found[2]} on PATH is older than {least}, which canopy's commit hooks need: workers' commits "
        f"get no trailer or prefix, and each run's note names them; install git {least} or later"
    )
