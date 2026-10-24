"""OpenCode 1, the runtime canopy runs by default (DESIGN §13): an implementation of `canopy.runtime`'s surface.

Everything canopy knows of OpenCode is here: the command line and variables a template uses (`invocation`), the JSON
events it prints (`events`, `transcript`, `watch`), the format of canopy's agent definitions (`definitions`), and the
files of its own config that could loosen them (`project_config`). Only `canopy.runtime.implementation` imports it, and
it imports from the rest of `canopy.runtime` only what any runtime reports (`report`, `entries`, `agents`). OpenCode
2's, `canopy.runtime.opencode2`, is a sibling package with the same modules, which `runtime.version` chooses instead,
and reuses its definitions' format.
"""

from canopy.runtime.opencode import (
    definitions,
    events,
    invocation,
    models,
    offerings,
    project_config,
    servers,
    session_models,
    transcript,
    watch,
)

__all__ = [
    "definitions",
    "events",
    "invocation",
    "models",
    "offerings",
    "project_config",
    "servers",
    "session_models",
    "transcript",
    "watch",
]
