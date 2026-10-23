"""How a command template starts one of OpenCode 2's agents (DESIGN §12, §13).

canopy's templates are the operator's to change, so this holds only what canopy writes into one: the defaults, which
run `opencode run` with JSON events (`canopy.runtime.opencode2.events`) and a session title, and the variable that
points OpenCode at canopy's definitions rather than the repository's (D040). Without it, OpenCode looks for canopy's
agent in the repository and, not finding it, runs its default agent, which allows everything. It also knows the
option that would choose a run's model on the command line, beating the model canopy writes into the agent's
definition (DESIGN §13), so config can refuse a template that passes one.

OpenCode 2's commands talk to a server. Unless told otherwise they share a background service, started once and kept
running, whose environment and config are those of whichever command started it, and whose tools run in its process,
outside whatever wraps the command. So every default runs with `--standalone`: a private server, started as a child of
the command, with the command's environment and inside its sandbox, and gone when the command ends.
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
#: The flag that gives a command a private server of its own rather than the shared background service.
STANDALONE = "--standalone"
#: The options of `opencode run` that choose a model, its short form, and the model's variant, taken to be 1's: a
#: template refused for one 2 does not take loses nothing, while one it does take would beat the model in the agent's
#: definition (DESIGN §13).
MODEL_OPTION = "--model"
SHORT_MODEL_OPTION = "-m"
VARIANT_OPTION = "--variant"
# The agent a command runs, as `opencode run` takes it, by a name that is safe as one path component.
_AGENT_RE = re.compile(r"(--agent[ =])([a-z][a-z0-9-]*)(?=\s|$)")


def default_template(agent: str, *, definitions_dir: str, title: str, prompt: str) -> str:
    """The default template that runs `agent`, from config's placeholders for the definitions, title, and prompt.

    Returns:
        A template that points OpenCode at `definitions_dir`, and runs `agent` on a private server with JSON events,
        `title` as the session's title, and `prompt` as its message.
    """
    return with_config_dir(
        definitions_dir,
        f"opencode run {STANDALONE} --agent {agent} --format json --thinking --title={title} {prompt}",
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
