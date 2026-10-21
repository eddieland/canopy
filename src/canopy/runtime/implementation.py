"""The runtime canopy runs, bound in one place (D009): the implementation behind each of the surface's modules.

Nothing but this module imports an implementation, so a new runtime, or a new major version of this one, is a package
beside the current one with the same modules, bound here instead, and the definitions and default templates it reads.
There is one binding, chosen here and not in config: canopy runs one runtime at a time, with no adapter interface
between them (AGENTS.md, Do not build).
"""

from canopy.runtime.opencode import (
    definitions,
    events,
    invocation,
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
    "offerings",
    "project_config",
    "servers",
    "session_models",
    "transcript",
    "watch",
]
