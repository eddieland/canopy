"""How a command template starts one of OpenCode's agents (DESIGN §12, §13).

canopy's templates are the operator's to change, so this holds only what canopy writes into one: the defaults, which
run `opencode run` with JSON events (`canopy.runtime.opencode.events`) and a session title, and the variable that points
OpenCode at canopy's definitions rather than the repository's (D040). Without it, OpenCode looks for canopy's agent in
the repository and, not finding it, runs its default agent, which allows everything. It also knows the option that
would choose a run's model on the command line, beating the model canopy writes into the agent's definition (DESIGN
§13), so config can refuse a template that passes one.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The runtime, as messages to the operator name it.
NAME = "OpenCode"
#: The variable OpenCode reads its config directory from.
CONFIG_DIR_ENV = "OPENCODE_CONFIG_DIR"
#: The option of `opencode run` that chooses a model, and its short form.
MODEL_OPTION = "--model"
SHORT_MODEL_OPTION = "-m"
#: The option of `opencode run` that chooses the model's variant, which has no short form.
VARIANT_OPTION = "--variant"
# The agent a command runs, as `opencode run` takes it, by a name that is safe as one path component.
_AGENT_RE = re.compile(r"(--agent[ =])([a-z][a-z0-9-]*)(?=\s|$)")


def default_template(agent: str, *, definitions_dir: str, title: str) -> str:
    """The default template that runs `agent`, from config's placeholders for the definitions and title.

    It places no prompt: canopy writes it on stdin, which `opencode run` appends to its message, so no argument limit
    applies and OpenCode does not quote it as it quotes a message argument that holds a space.

    Returns:
        A template that points OpenCode at `definitions_dir`, and runs `agent` with JSON events and `title` as the
        session's title.
    """
    return with_config_dir(
        definitions_dir,
        f"opencode run --agent {agent} --format json --thinking --title={title}",
    )


def with_config_dir(directory: str, command: str) -> str:
    """`command` with OpenCode pointed at `directory`, a word already quoted for the shell, for its config.

    Returns:
        `command`, run by `env` with the config directory set.
    """
    return f"env {CONFIG_DIR_ENV}={directory} {command}"


def agent_of(command: str) -> str | None:
    """Return the agent `command` names with `--agent`, or None when it names none a path component could hold."""
    found = _AGENT_RE.search(command)
    return found[2] if found else None


def with_agent(command: str, agent: str) -> str:
    """Return `command` running `agent` in place of the one it names with `--agent`, or as it is when it names none."""
    return _AGENT_RE.sub(lambda found: f"{found[1]}{agent}", command, count=1)


def model_option(words: Sequence[str], *, run_args: bool = False) -> str | None:
    """Return the first of `words`, a command's, that passes `opencode run` a model or variant, or None when none does.

    `--model` and `--variant` count wherever they are, since a wrapper may hand them on; `-m`, which a wrapper may take
    for itself, only among `opencode run`'s own arguments: after `opencode run` in `words`, or anywhere with
    `run_args`, for words that follow a run's command, such as a suffix's.
    """
    after_run = run_args
    for i, word in enumerate(words):
        # `-m` takes its value as the next word, after `=`, or attached (`-macme/x`), as yargs parses it.
        if word.split("=", 1)[0] in (MODEL_OPTION, VARIANT_OPTION) or (
            after_run and word.startswith(SHORT_MODEL_OPTION)
        ):
            return word
        if word == "run" and i > 0 and PurePosixPath(words[i - 1]).name == "opencode":
            after_run = True
    return None
