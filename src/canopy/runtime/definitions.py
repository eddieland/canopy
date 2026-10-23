"""canopy's agent definitions in the runtime's format (DESIGN §13): the bundled files, rendered with config's rules.

canopy ships its agents, skills, and plugins as the runtime reads them from a config directory, and writes into its
agents what each agent may do (`canopy.runtime.agents.Rules`). `canopy.core.definitions` snapshots the result for runs
to load (D040). The format, and the names the runtime gives tools and skills, are the implementation's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import definitions

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from canopy.runtime.agents import Rules

#: The directory of a config directory the runtime reads agent definitions from, and the one it reads skills from.
AGENTS_SUBDIR = definitions.AGENTS_SUBDIR
SKILLS_SUBDIR = definitions.SKILLS_SUBDIR

#: A part of a tool's name as the runtime gives it: an MCP server's name or one of its tools'. They are rendered into
#: definitions, so nothing else may reach them.
TOOL_PART_RE = definitions.TOOL_PART_RE
#: The runtime's rule for a skill's name, and the longest one it takes.
SKILL_NAME_RE = definitions.SKILL_NAME_RE
MAX_SKILL_NAME = definitions.MAX_SKILL_NAME
#: A bash rule canopy renders from config, `runtime.allow_bash`: a command's name, a literal word, then arguments of
#: plain characters and the runtime's wildcards. Its first word is the command it allows.
BASH_ALLOW_RE = definitions.BASH_ALLOW_RE
#: The runtime's own commands, which run an agent with rules of their own.
RUNTIME_COMMANDS = definitions.RUNTIME_COMMANDS
#: A model as the runtime names one, which canopy renders into an agent's definition (DESIGN §13).
MODEL_RE = definitions.MODEL_RE
#: A variant of a model as the runtime names one, which canopy renders beside the model (DESIGN §13).
VARIANT_RE = definitions.VARIANT_RE


def agent_names() -> list[str]:
    """Return the names of the agents canopy ships, as the runtime names them, in order."""
    return definitions.agent_names()


def bundled() -> dict[str, bytes]:
    """Return the bundled agents, skills, and plugins as a config directory holds them, by relative path, unrendered."""
    return definitions.bundled()


def links() -> dict[str, Path]:
    """Return the files the snapshot links to rather than holds, by the relative path of each link.

    A runtime that reads canopy's definitions directory in place of the operator's own config reads that config
    through these, so the operator's servers and providers reach every run.

    Returns:
        Each link's target by its path in the snapshot; empty when the runtime reads its own config beside it.
    """
    return definitions.links()


def render(files: Mapping[str, bytes], rules: Rules) -> dict[str, bytes]:
    """Return `files`, a config directory's by relative path, with `rules` written into canopy's agents.

    Returns:
        A copy of `files` with each of canopy's definitions it holds rendered.

    Raises:
        DefinitionsError: A definition cannot be rendered.
    """
    return definitions.render(files, rules)
