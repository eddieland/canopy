"""How a command template starts one of OpenCode's agents (DESIGN §12, §13).

canopy's templates are the operator's to change, so this holds only what canopy writes into one: the defaults, which
run `opencode run` with JSON events (`canopy.runtime.events`) and a session title, and the variable that points
OpenCode at canopy's definitions rather than the repository's (D040). Without it, OpenCode looks for canopy's agent in
the repository and, not finding it, runs its default agent, which allows everything.
"""

from __future__ import annotations

import re

#: The runtime, as messages to the operator name it.
NAME = "OpenCode"
#: The variable OpenCode reads its config directory from.
CONFIG_DIR_ENV = "OPENCODE_CONFIG_DIR"
# The agent a command runs, as `opencode run` takes it, by a name that is safe as one path component.
_AGENT_RE = re.compile(r"--agent[ =]([a-z][a-z0-9-]*)(?:\s|$)")


def default_template(agent: str, *, definitions_dir: str, title: str, prompt: str) -> str:
    """The default template that runs `agent`, from config's placeholders for the definitions, title, and prompt.

    Returns:
        A template that points OpenCode at `definitions_dir`, and runs `agent` with JSON events, `title` as the
        session's title, and `prompt` as its message.
    """
    return with_config_dir(
        definitions_dir, f"opencode run --agent {agent} --format json --thinking --title={title} {prompt}"
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
    return found[1] if found else None
