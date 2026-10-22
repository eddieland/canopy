"""The commands canopy starts its agents with, rendered from the operator's templates as a run would render them.

`canopy config commands` prints them, so the operator can see a template's words, quoting, prefix, and suffix land where
they meant before a run starts one. A template may carry a token or name a host, so only the operator reads them: the
command refuses inside one of canopy's own ticks or runs, where an agent would report what it read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import config
from canopy.core.vocab import RunKind

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from canopy.core.config import Config
    from canopy.core.settings import Layer

#: What stands for the prompt in a rendered command: canopy writes a new one for each run.
PROMPT = "<prompt>"
#: The ticket an example title names.
EXAMPLE_KEY = "PROJ-1"
#: The PR an example reviewer's title names.
EXAMPLE_PR = "https://github.com/owner/repo/pull/1"


@dataclass(frozen=True)
class Key:
    """One config key a command is made from."""

    #: Its name, `section.key`, or `chores.<name>.cmd` for one chore's own.
    key: str
    #: The file that set it, or None when it is the default.
    set_in: Layer | None


@dataclass(frozen=True)
class Command:
    """One command canopy starts, as a run of it would start it."""

    #: What it starts: an agent's role, `chore <name>` for a chore with its own command, or `setup`.
    role: str
    #: The keys it is made from, in the order their words appear.
    keys: Sequence[Key]
    #: Its words, as canopy runs them with no shell, `PROMPT` in the prompt's place.
    argv: Sequence[str]
    #: `PROMPT` when canopy writes the prompt on its stdin; None when a word of `argv` carries it, or it takes none.
    stdin: str | None = None


def commands(cfg: Config, layer_of: Mapping[str, Layer], definitions_dir: Path) -> list[Command]:
    """Return each command canopy starts, rendered from `cfg` with `definitions_dir` and an example title.

    `layer_of` names the file that set each key some file sets, by `section.key`, as `config.origins` finds them.

    Returns:
        The overseer's, each worker run's, the reviewer's, and the chores' commands, then `runtime.setup_cmd` when set.
    """
    runtime = cfg.runtime

    def keys(*names: str) -> list[Key]:
        return [Key(name, layer_of.get(name)) for name in names]

    def wrapped(name: str) -> list[Key]:
        prefix = ["runtime.worker_cmd_prefix"] if runtime.worker_cmd_prefix else []
        suffix = ["runtime.worker_cmd_suffix"] if runtime.worker_cmd_suffix else []
        return keys(*prefix, name, *suffix)

    def render(role: str, made_of: Sequence[Key], template: str, title: str) -> Command:
        rendered = config.render_command(template, PROMPT, definitions_dir, title)
        return Command(role, made_of, rendered.argv, rendered.stdin)

    found = [
        render("overseer", keys("runtime.overseer_cmd"), runtime.overseer_cmd, "tick 1 · by hand · nothing open"),
        render(
            "worker",
            wrapped("runtime.worker_cmd"),
            runtime.worker_template(runtime.worker_cmd),
            _title(RunKind.IMPLEMENT),
        ),
        render(
            "private worker",
            wrapped("runtime.private_worker_cmd"),
            runtime.worker_template(runtime.private_worker_cmd),
            _title(RunKind.IMPLEMENT),
        ),
        render("planner", wrapped("runtime.plan_cmd"), runtime.worker_template(runtime.plan_cmd), _title(RunKind.PLAN)),
        render("reviewer", keys("runtime.review_cmd"), runtime.review_cmd, f"review {EXAMPLE_PR}"),
        render("chore", keys("runtime.chore_cmd"), runtime.chore_cmd, "chore:<name>"),
    ]
    # A chore's table is one key, from the last file that has the whole `chores` section.
    chores_from = layer_of.get("chores")
    found.extend(
        render(f"chore {name}", [Key(f"chores.{name}.cmd", chores_from)], chore.cmd, f"chore:{name}")
        for name, chore in sorted(cfg.chores.items())
        if chore.cmd is not None
    )
    if runtime.setup_cmd:
        found.append(Command("setup", keys("runtime.setup_cmd"), config.setup_words(runtime.setup_cmd)))
    return found


def _title(kind: RunKind) -> str:
    return f"{EXAMPLE_KEY} {kind}: Example ticket"
