"""OpenCode 2, a runtime canopy can run (DESIGN §13): an implementation of `canopy.runtime`'s surface.

Everything canopy knows of OpenCode 2 is here: the command line and variables a template uses (`invocation`), the JSON
events it prints (`events`, `transcript`, `watch`), the format of canopy's agent definitions (`definitions`), what it
offers each agent (`offerings`), the files of its own config that could loosen them (`project_config`), how a run is
given one of canopy's MCP servers (`servers`), and which models served a session (`session_models`). It is the sibling
of `canopy.runtime.opencode`, OpenCode 1's, with the same modules, so either is bound in `canopy.runtime.implementation`
(D009). It imports from the rest of `canopy.runtime` only what any runtime reports (`report`, `entries`, `agents`).

Checked against OpenCode 2.1.2, its source and its binary (2026-10-22).
"""
