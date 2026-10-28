"""How a command template starts one of the runtime's agents (DESIGN §12, §13).

canopy's templates are the operator's to change, so this holds only what canopy writes into one: the default for each
agent, and how a template points the runtime at canopy's definitions rather than the repository's (D040). Without
that, the runtime looks for canopy's agent in the repository and, not finding it, runs an agent that allows everything.
It also says whether a template chooses a model of its own, which config refuses, and runs a template on another of
canopy's agents, as a chore with a model of its own is run (DESIGN §13).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import one, pick, two

if TYPE_CHECKING:
    from collections.abc import Sequence

    from canopy.runtime.implementation import Version

# Both versions take a template alike but for its default, so what else is said of one is the first's.
_shared = one.invocation

#: The runtime, as messages to the operator name it.
NAME = _shared.NAME


def default_template(agent: str, *, version: Version, definitions_dir: str, title: str) -> str:
    """The default template that runs `agent` on the runtime `version` runs, from config's placeholders.

    The placeholders are those for the definitions and the title.

    Returns:
        A template that points the runtime at `definitions_dir`, and runs `agent` with the events canopy reads and
        `title` as the session's title. It places no prompt, so canopy writes the prompt on its stdin (D023).
    """
    return pick(version, one.invocation, two.invocation).default_template(
        agent,
        definitions_dir=definitions_dir,
        title=title,
    )


def with_config_dir(directory: str, command: str) -> str:
    """`command` with the runtime pointed at `directory`, a word already quoted for the shell, for its config.

    Returns:
        `command`, run with the runtime's config directory set.
    """
    return _shared.with_config_dir(directory, command)


def agent_of(command: str) -> str | None:
    """Return the agent `command` runs, or None when it names none a path component could hold."""
    return _shared.agent_of(command)


def with_agent(command: str, agent: str) -> str:
    """Return `command` running `agent` in place of the one it names, as a chore with a model of its own runs its copy.

    Returns:
        `command` with the agent replaced, or as it is when it names none.
    """
    return _shared.with_agent(command, agent)


def model_option(words: Sequence[str], *, run_args: bool = False) -> str | None:
    """Return the first of `words`, a command's, that passes the runtime a model or a variant, or None when none does.

    canopy writes each agent's model, and its variant, into its definition, and either passed on the command line would
    beat it unseen (DESIGN §13). With `run_args`, every word is read as an argument of the agent's run, as a suffix's
    are.
    """
    return _shared.model_option(words, run_args=run_args)
