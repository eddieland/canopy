"""OpenCode 2, a runtime canopy runs when config asks for it (DESIGN §13): an implementation of the surface.

Everything canopy knows of OpenCode 2 is here: the command line and variables a template uses (`invocation`), the JSON
events it prints (`events`, `transcript`, `watch`), the format of canopy's agent definitions (`definitions`), what it
offers each agent (`offerings`), the files of its own config that could loosen them (`project_config`), how a run is
given one of canopy's MCP servers (`servers`), which models served a session (`session_models`), and which it lists to
run an agent on (`models`). It is the sibling of `canopy.runtime.opencode`, OpenCode 1's, with the same modules, run
when `runtime.version` is 2 (D009). It imports from the rest of `canopy.runtime` only what any runtime reports
(`report`, `entries`, `agents`).

Checked against OpenCode 2.1.2, its source and its binary (2026-10-22), and against 2.1.4's binary (2026-10-23), the
release it needs: 2.1.2 runs a primary agent on the default model whatever its definition names.
"""

from canopy.runtime.opencode2 import (
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
