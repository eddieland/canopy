---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, and `deny` is enforced under `opencode run`. Scalars are used where a
# whole tool is denied, since a repository's config cannot loosen a scalar canopy sets (D044).
# The planner writes nothing anywhere: its final message is the plan (DESIGN §25, TRUST_MODEL T1, T6). It reads the
# worktrees linked from its desk with OpenCode's read, list, glob, and grep tools, and the ticket with the tracker's
# read tools only. canopy renders this file into its definitions directory with the tracker's MCP server and tools from
# the operator's config (`tracker.mcp_server`, `tracker.read_tools`), at the marked line below, as for
# canopy-worker-private. As shipped it names none, and dispatch refuses a plan then (`no_read_tools`).
description: canopy planner. Writes a plan for one ticket before it is implemented; reads only, writes nothing.
mode: primary
temperature: 0.1
permission:
  edit: deny
  bash: deny
  # No web tools: fetched and searched pages are text anyone can shape, the easiest way to steer an agent
  # (TRUST_MODEL T1, D077).
  webfetch: deny
  websearch: deny
  codesearch: deny
  external_directory: deny
  # Subagents run with their own, wider permissions; the planner must not reach them.
  task: deny
  # MCP tools are permissioned by name, `<server>_<tool>`, and names differ by server, so these patterns are defense
  # in depth for servers other than the tracker's: commenting or replying anywhere, reviewing, and anything that
  # creates, pushes, writes files, changes labels, or edits or deletes. Reading stays allowed.
  "*add_*": deny
  "*addComment*": deny
  "*comment*": deny
  "*reply*": deny
  "*write*": deny
  "*pending_review*": deny
  "*submit*": deny
  "*approve*": deny
  "*create*": deny
  "*label*": deny
  "*assign*": deny
  "*edit*": deny
  "*update*": deny
  "*delete*": deny
  "*merge*": deny
  "*close*": deny
  "*transition*": deny
  "*push*": deny
  "*branch*": deny
  "*file*": deny
  "*fork*": deny
  "*copilot*": deny
  "*run_workflow*": deny
  "*run_trigger*": deny
  "*rerun*": deny
  "*cancel*": deny
  # Every tool of the tracker's MCP server is denied by a wildcard, then only its read tools are allowed by name: the
  # last matching rule wins (D021), so a write tool missing from both lists fails closed.
  # canopy: tracker tools
---

The system prompt is supplied by the harness at invocation time via the
`{prompt}` argument to `opencode run`. Keep this body minimal so the agent does
not act without a rendered prompt:

If you were started without a "# canopy worker: plan" prompt, print
`no prompt supplied` and exit.
