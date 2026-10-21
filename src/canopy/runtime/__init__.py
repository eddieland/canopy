"""The agent runtime (DESIGN §13): everything canopy knows of how an agent runs, and nothing about tickets.

The package is in three parts, so that a new runtime, or a new major version of this one, such as OpenCode 2, is a
change here and to the command templates (D009):

- The surface, which the rest of canopy calls: `stdout` (what a finished agent printed), `watch` (a running one's
  lines), `transcript` (a session's log, for a page), `definitions` (canopy's agents in the runtime's format),
  `project_config` (the runtime's config where an agent starts), `offerings` (what it offers each agent once the
  operator's config is merged in), `invocation` (a command template's defaults), and `servers` (how a run is given
  one of canopy's own MCP servers).
- What any runtime reports, which the surface returns and an implementation builds: `report` (text, session, cost, and
  tools), `entries` (a transcript's entries and bounds), and `agents` (canopy's agents and what config decides of them).
  These name no runtime, and bound what agent output may hold whatever printed it.
- The implementation, one package with a module behind each of the surface's, bound in `implementation`. Only that
  module imports it, and only the implementation names the runtime.

There is still no adapter interface: one runtime at a time, chosen by the binding, not by config.
"""
