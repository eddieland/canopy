"""Where the sandbox stands, for `canopy health`: each command's by the config in force, srt, and the templates.

Each command canopy starts an agent or setup with either starts in `canopy-sandbox`, by its own prefix or
`runtime.sandbox_repos` (DESIGN §24), or outside it. When any does, it says whether the srt the wrapper would run is the
one `canopy sandbox setup` installs, and whether the template of each role in use loads as a run would read it. It
reuses what setup checks, and installs, writes, and starts no sandbox: the sandbox is opt-in, so a config that wraps
nothing is no fault.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import canopy_sandbox

from canopy.core import config, sandboxing
from canopy.setup import sandbox

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from canopy.core.config import Config
    from canopy.infra import procs


@dataclass(frozen=True)
class Command:
    """One command canopy starts, and whether it starts in the sandbox."""

    #: What it starts, as `canopy config commands` names it: `worker`, `chore build-health`, or `setup`.
    what: str
    #: The config key whose template it is, which the operator prefixes.
    key: str
    #: The wrapper's role it starts in, which names its template, or None when it starts outside the sandbox.
    role: str | None
    #: The repositories whose runs alone it starts in the sandbox, by `runtime.sandbox_repos`; empty for every run.
    repos: Sequence[str] = ()


@dataclass(frozen=True)
class Standing:
    """Where the sandbox stands on this machine, by the config in force."""

    #: Each command canopy starts, in the order `canopy config commands` lists them.
    commands: Sequence[Command]
    #: The srt version canopy pins.
    pinned: str
    #: How the srt the wrapper would run differs from the pinned one setup installs; None when it does not, or when
    #: no command starts in the sandbox, which leaves srt unchecked.
    srt: str | None
    #: Each role a command starts in, with why its template would not load in a run, or None when it loads.
    templates: Mapping[str, str | None]

    @property
    def sandboxed(self) -> bool:
        """Whether any command starts in the sandbox."""
        return any(c.role is not None for c in self.commands)


def standing(cfg: Config, runner: procs.Runner) -> Standing:
    """Find where the sandbox stands for `cfg`: each command's state, then srt and the templates when any is in it.

    Returns:
        What was found. It changes nothing: srt is asked only its version.
    """
    runtime = cfg.runtime
    templates = [
        ("overseer", "runtime.overseer_cmd", runtime.overseer_cmd),
        ("worker", "runtime.worker_cmd", runtime.worker_template(runtime.worker_cmd)),
        ("private worker", "runtime.private_worker_cmd", runtime.worker_template(runtime.private_worker_cmd)),
        ("planner", "runtime.plan_cmd", runtime.worker_template(runtime.plan_cmd)),
        ("reviewer", "runtime.review_cmd", runtime.review_cmd),
        ("chore", "runtime.chore_cmd", runtime.chore_cmd),
        *(
            (f"chore {name}", f"chores.{name}.cmd", chore.cmd)
            for name, chore in sorted(cfg.chores.items())
            if chore.cmd is not None
        ),
    ]
    found = [_command(runtime, what, key, config.command_words(template)) for what, key, template in templates]
    if runtime.setup_cmd:
        found.append(_command(runtime, "setup", "runtime.setup_cmd", config.setup_words(runtime.setup_cmd)))
    roles = list(dict.fromkeys(c.role for c in found if c.role is not None))
    return Standing(
        commands=found,
        pinned=sandbox.pinned_version(),
        srt=sandbox.runtime_problem(runner) if roles else None,
        templates={role: _template_problem(role) for role in roles},
    )


def _command(runtime: config.Runtime, what: str, key: str, words: Sequence[str]) -> Command:
    """Return the command `what`, made from `key` as `words`: in the role its prefix names, or `sandbox_repos` gives.

    Returns:
        The command, its role None when neither puts it in the sandbox.
    """
    if words and Path(words[0]).name == config.SANDBOX_WRAPPER:
        # The wrapper refuses a role it does not know, so the word is kept as it is, to say so.
        return Command(what, key, words[1] if len(words) > 1 else "")
    if runtime.sandbox_repos and (role := sandboxing.COMMAND_ROLES.get(what)) is not None:
        return Command(what, key, role, runtime.sandbox_repos)
    return Command(what, key, None)


def _template_problem(role: str) -> str | None:
    """Say why a run as `role` would not start for its template, if it would not.

    Returns:
        The wrapper's reason, or None when the template loads.
    """
    if role not in canopy_sandbox.ROLES:
        return f"canopy-sandbox has no role {role!r}: it takes {', '.join(canopy_sandbox.ROLES)}"
    try:
        canopy_sandbox.validate_template(role)
    except canopy_sandbox.SandboxError as e:
        return str(e)
    return None
