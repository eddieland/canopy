"""Which runs canopy puts in the sandbox itself: those in the repositories `runtime.sandbox_repos` names (DESIGN §24).

A run in one of them starts in `canopy-sandbox`, the wrapper canopy installs beside itself, with the role that picks
its policy template, as the prefix in DESIGN §24 would start it. A joint run whose repositories disagree is refused at
dispatch (`mixed`); one that disagrees by the time it runs, after the config changed, is sandboxed.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final, Literal

from canopy.core import config

#: The wrapper, by its absolute path beside the interpreter canopy runs on, where the install puts it: never looked up
#: on PATH, where a relative entry would find what a branch committed, and never `python -m`, which would put the
#: run's directory first on the import path.
WRAPPER: Final = Path(sys.executable).parent / config.SANDBOX_WRAPPER

#: The wrapper's roles canopy starts a run in: a worker run's, `setup_cmd`'s, and a review's.
Role = Literal["worker", "setup", "review"]


def wrap(
    runtime: config.Runtime,
    repos: Iterable[str | None],
    role: Role,
    argv: Sequence[str],
    definitions_dir: Path | None = None,
) -> list[str]:
    """Return `argv` behind the wrapper, as `role`, when a repository in `repos` is sandboxed; else `argv` as it is.

    `definitions_dir` is canopy's agent definitions, which the wrapper lets the run read (D040); setup runs no agent and
    takes none. A repository that is None, a review's in a workspace of one, is never sandboxed.

    Returns:
        The words to run.
    """
    if not sandboxed(runtime, repos):
        return list(argv)
    read = ["--read", str(definitions_dir)] if definitions_dir is not None else []
    return [str(WRAPPER), role, *read, "--", *argv]


def sandboxed(runtime: config.Runtime, repos: Iterable[str | None]) -> bool:
    """Return whether any of `repos` is one `runtime.sandbox_repos` names."""
    return any(repo in runtime.sandbox_repos for repo in repos)


def mixed(runtime: config.Runtime, repos: Sequence[str]) -> str | None:
    """Return why a joint run over `repos` cannot start, when some are sandboxed and some not; else None.

    One run is one command, so it runs in one sandbox or none.

    Returns:
        The refusal's reason, or None when every repository agrees.
    """
    inside = [repo for repo in repos if repo in runtime.sandbox_repos]
    outside = [repo for repo in repos if repo not in runtime.sandbox_repos]
    if not inside or not outside:
        return None
    return (
        f"{', '.join(inside)} {'runs' if len(inside) == 1 else 'run'} sandboxed and {', '.join(outside)} "
        f"{'does' if len(outside) == 1 else 'do'} not (runtime.sandbox_repos), and one run is one sandbox or none: "
        "dispatch them as separate runs, or the operator sandboxes all of them or none"
    )
