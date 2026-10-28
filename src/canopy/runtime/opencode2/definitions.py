"""canopy's agent definitions as OpenCode 2 reads them (DESIGN §13): OpenCode 1's format, and a config of its own.

OpenCode 2 reads an agent file in OpenCode 1's format through its compatibility layer, the `permission` frontmatter
included: it renames the actions `bash` to `shell`, `task` to `subagent`, and `write` and `patch` to `edit`, keeps the
rules' order, and evaluates them as 1 did, the last matching rule deciding, and a tool whose last matching rule denies
it with the pattern `*` not sent at all. So canopy's definitions, and how config is rendered into them, are OpenCode 1's
(`canopy.runtime.opencode.definitions`), shared rather than copied, and only what OpenCode 2 adds is here. The plugin
is shared too: its default export holds an entry point for each major version (DESIGN §33).

It adds one file, and links others. OpenCode 2's commands share a background service unless told otherwise, and the
service keeps the config and environment of whichever command started it. A config directory with a `service.json`
that disables it gives every command that reads the directory a private server instead, so no command run with
canopy's definitions starts a service that outlives it, or attaches to one the operator started with their own config.

A config directory named in `OPENCODE_CONFIG_DIR` takes the place of the operator's own, `~/.config/opencode` (or
under `XDG_CONFIG_HOME`), where OpenCode 1 read both: their MCP servers, providers, and rules would be lost to every
run. So the snapshot links each JSON config file of theirs at its own name (`links`), which 2 reads through the link,
and passes over while the link leads nowhere; what their directory holds besides, such as plugins of their own, is not
read.

Two of 2's rules differ from 1's, and canopy's files keep within both: a definition that does not decode is dropped
without an error, and a run that names it then fails, `Agent not found`; and a skill's id is its directory's name,
which 2 does not validate, so canopy keeps to 1's rule for the names it counts a skill under.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from canopy.runtime.opencode.definitions import (
    AGENTS_SUBDIR,
    BASH_ALLOW_RE,
    MODEL_RE,
    RUNTIME_COMMANDS,
    SKILLS_SUBDIR,
    TOOL_PART_RE,
    VARIANT_RE,
    agent_names,
    render,
)
from canopy.runtime.opencode.definitions import bundled as _bundled

__all__ = [
    "AGENTS_SUBDIR",
    "BASH_ALLOW_RE",
    "MAX_SKILL_NAME",
    "MODEL_RE",
    "RUNTIME_COMMANDS",
    "SERVICE_FILE",
    "SKILLS_SUBDIR",
    "SKILL_NAME_RE",
    "TOOL_PART_RE",
    "USER_CONFIG_FILES",
    "VARIANT_RE",
    "agent_names",
    "bundled",
    "links",
    "render",
]

#: The file of a config directory that says whether OpenCode's commands share a background service.
SERVICE_FILE = "service.json"
#: The names canopy counts a skill under: OpenCode 1's rule, lowercase letters and digits in words joined by single
#: hyphens, at most 64. OpenCode 2 takes any directory's name as a skill's id.
SKILL_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_SKILL_NAME = 64


#: The JSON config files OpenCode 2 reads from its own config directory.
USER_CONFIG_FILES = ("config.json", "opencode.json", "opencode.jsonc")


def links() -> dict[str, Path]:
    """Return the files the snapshot links to rather than holds: the operator's own config, each at its own name.

    Returns:
        Each JSON config file of OpenCode's own config directory, whether or not it exists, by its name.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    user_dir = (Path(xdg) if xdg else Path.home() / ".config") / "opencode"
    return {name: user_dir / name for name in USER_CONFIG_FILES}


def bundled() -> dict[str, bytes]:
    """Return the bundled agents, skills, and plugins as a config directory holds them, and the file for the service.

    Returns:
        Each file by its path relative to the directory, unrendered, with `SERVICE_FILE` disabling the service.
    """
    return {**_bundled(), SERVICE_FILE: (json.dumps({"disabled": True}) + "\n").encode()}
