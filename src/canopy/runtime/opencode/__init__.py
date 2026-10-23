"""OpenCode 1, a runtime canopy ran (DESIGN §13): an implementation of `canopy.runtime`'s surface, no longer bound.

Everything canopy knows of OpenCode is here: the command line and variables a template uses (`invocation`), the JSON
events it prints (`events`, `transcript`, `watch`), the format of canopy's agent definitions (`definitions`), and the
files of its own config that could loosen them (`project_config`). Only `canopy.runtime.implementation` imports it, and
it imports from the rest of `canopy.runtime` only what any runtime reports (`report`, `entries`, `agents`). OpenCode
2's, `canopy.runtime.opencode2`, is a sibling package with the same modules, bound in its place, and reuses its
definitions' format.
"""
