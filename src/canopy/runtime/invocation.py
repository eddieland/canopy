"""How a command template starts one of the runtime's agents (DESIGN §12, §13).

canopy's templates are the operator's to change, so this holds only what canopy writes into one: the default for each
agent, and how a template points the runtime at canopy's definitions rather than the repository's (D040). Without
that, the runtime looks for canopy's agent in the repository and, not finding it, runs an agent that allows everything.
"""

from __future__ import annotations

from canopy.runtime.implementation import invocation

#: The runtime, as messages to the operator name it.
NAME = invocation.NAME


def default_template(agent: str, *, definitions_dir: str, title: str) -> str:
    """The default template that runs `agent`, from config's placeholders for the definitions and title.

    Returns:
        A template that points the runtime at `definitions_dir`, and runs `agent` with the events canopy reads and
        `title` as the session's title. It places no prompt, so canopy writes the prompt on its stdin (D023).
    """
    return invocation.default_template(agent, definitions_dir=definitions_dir, title=title)


def with_config_dir(directory: str, command: str) -> str:
    """`command` with the runtime pointed at `directory`, a word already quoted for the shell, for its config.

    Returns:
        `command`, run with the runtime's config directory set.
    """
    return invocation.with_config_dir(directory, command)


def agent_of(command: str) -> str | None:
    """Return the agent `command` runs, or None when it names none a path component could hold."""
    return invocation.agent_of(command)
