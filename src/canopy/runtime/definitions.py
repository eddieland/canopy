"""canopy's agent definitions in the runtime's format (DESIGN §13): the bundled files, rendered with config's rules.

canopy ships its agents and skills as the runtime reads them from a config directory, and writes into them what each
agent may do (`canopy.runtime.agents.Rules`). `canopy.core.definitions` snapshots the result for runs to load (D040).
The format, and the names the runtime gives tools and skills, are the implementation's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import definitions

if TYPE_CHECKING:
    from collections.abc import Mapping

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


def agent_names() -> list[str]:
    """Return the names of the agents canopy ships, as the runtime names them, in order."""
    return definitions.agent_names()


def bundled() -> dict[str, bytes]:
    """Return the bundled agents and skills as a config directory holds them, by relative path, unrendered."""
    return definitions.bundled()


def render(files: Mapping[str, bytes], rules: Rules) -> dict[str, bytes]:
    """Return `files`, a config directory's by relative path, with `rules` written into canopy's agents.

    Returns:
        A copy of `files` with each of canopy's definitions it holds rendered.

    Raises:
        DefinitionsError: A definition cannot be rendered.
    """
    return definitions.render(files, rules)
