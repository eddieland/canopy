"""The runtime's own config in the directories an agent starts in, where it could loosen canopy's agents (D044).

The runtime merges a repository's config with canopy's definitions, and a definition there of one of canopy's agents
could loosen its rules. So a run refuses to start where that config defines one of canopy's agents (`shadowing`), and a
private run also where it names a tool of the tracker's MCP server, since a rule there could reopen a write tool
(DESIGN §22). Which files the runtime reads, and how they name an agent or a tool, is the implementation's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import project_config

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def refusal(places: Iterable[Path], *, tracker_server: str | None = None) -> str | None:
    """Why an agent may not start where the runtime reads config from `places`, or None when it may.

    `tracker_server` is the tracker's MCP server, for a run that may call only its read tools: a private run, a plan,
    or a triage. Shadowing is checked first, in every place, then the tracker's tools.

    Returns:
        A message for the operator naming every file that refuses the run, or None.
    """
    places = list(places)
    shadowing = [found for place in places for found in project_config.shadowing(place)]
    if shadowing:
        return project_config.shadowing_message(shadowing)
    if tracker_server is None:
        return None
    naming = [found for place in places for found in project_config.naming_tools(place, tracker_server)]
    return project_config.naming_tools_message(tracker_server, naming) if naming else None


def shadowing(root: Path) -> list[Path]:
    """Return the files of the runtime's config in `root` that define, or may define, one of canopy's agents."""
    return project_config.shadowing(root)


def shadowing_message(found: Iterable[Path]) -> str:
    """Explain what `shadowing` found and what to do about it.

    Returns:
        A message for the operator naming every file in `found`.
    """
    return project_config.shadowing_message(found)
