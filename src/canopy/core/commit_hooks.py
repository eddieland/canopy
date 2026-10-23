"""canopy's git hooks, which put its trailers on every commit a worker makes (TRUST_MODEL T5).

The trailers are formed by the harness and added by git, not by the agent: a worker run's environment points git's
`core.hooksPath` at the hooks in canopy's snapshot (DESIGN §13), through `GIT_CONFIG_COUNT` and its keys, and names
the trailers in `CANOPY_COMMIT_TRAILERS`. `prepare-commit-msg` adds each trailer the message lacks; git runs it for a
commit, an amend, a merge, a rebase, a cherry-pick, and a revert, `--no-verify` or not, and only plumbing such as
`commit-tree` makes a commit without it. Every hook, that one included, then runs the repository's own hook of its
name, the one git would have run without canopy's entry, so the operator's hooks run as before (docs/HOOKS.md).

canopy's entry is the last of the `GIT_CONFIG_*` ones, after any the operator's environment holds, so a hook finds
the repository's own hooks by asking git with one entry fewer. The variables reach every git the worker's tools run,
in any repository: what they add there is a trailer, and what they run, that repository's own hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import prompts

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from canopy.core.config import Config

#: The directory in canopy's snapshot that holds the hooks.
HOOKS_DIR = "git-hooks"
#: The trailers the hooks add, one to a line.
TRAILERS_ENV = "CANOPY_COMMIT_TRAILERS"
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
# canopy's git hook (TRUST_MODEL T5): adds canopy's trailers to the message, as prepare-commit-msg, then runs the
# repository's own hook of this name.
name=${0##*/}
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
# The hooks directory git would use without canopy's entry, the last of GIT_CONFIG_COUNT's.
hooks=$(GIT_CONFIG_COUNT=$((${GIT_CONFIG_COUNT:-1} - 1)) git rev-parse --git-path hooks) || exit
if [ -x "$hooks/$name" ]; then
    exec "$hooks/$name" "$@"
fi
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


def trailers(config: Config, model: str | None = None, planner_model: str | None = None) -> list[str]:
    """Return the trailers canopy puts on a worker's commits: none while `trust.commit_trailer` is off.

    `model` is the worker's chosen model, which its trailer may name (`prompts.commit_trailer`), and `planner_model`
    that of the planner whose approved plan it follows, which a second trailer names (`prompts.planner_trailer`).

    Returns:
        The trailers, each `Co-authored-by: <name> <<email>>`.
    """
    if not config.trust.commit_trailer:
        return []
    planner = prompts.planner_trailer(config, planner_model)
    return [prompts.commit_trailer(config, model), *([planner] if planner is not None else [])]


def env(snapshot: Path, added: Sequence[str], inherited: Mapping[str, str]) -> dict[str, str]:
    """Return what a worker's environment needs for git to add `added` to its commits, through the hooks in `snapshot`.

    `inherited` is the environment the worker would otherwise get, whose `GIT_CONFIG_*` entries come first.

    Returns:
        The variables to merge over `inherited`, or none when there is nothing to add.
    """
    if not added:
        return {}
    count = inherited.get("GIT_CONFIG_COUNT", "")
    # git refuses a count that is not a number, whatever canopy adds, so one that is not is replaced, not kept.
    index = int(count) if count.isdigit() else 0
    return {
        "GIT_CONFIG_COUNT": str(index + 1),
        f"GIT_CONFIG_KEY_{index}": "core.hooksPath",
        f"GIT_CONFIG_VALUE_{index}": str(snapshot.absolute() / HOOKS_DIR),
        TRAILERS_ENV: "\n".join(added),
    }
