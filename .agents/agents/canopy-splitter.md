---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, and `deny` is enforced under `opencode run`. Scalars are used where a
# whole tool is denied, since a repository's config cannot loosen a scalar canopy sets (D044).
# The splitter creates tickets and nothing else (DESIGN §18, TRUST_MODEL T1, T6). It reads the workspace's clones with
# OpenCode's read, list, glob, and grep tools, and reaches the tracker through its MCP server.
description: canopy splitter. Splits a ticket into one ticket per repository; adds no labels, pushes nothing.
mode: primary
temperature: 0.1
permission:
  edit: deny
  bash: deny
  webfetch: deny
  external_directory: deny
  # Subagents run with their own, wider permissions; the splitter must not reach them.
  task: deny
  # MCP tools are permissioned by name, `<server>_<tool>`, and names differ by server, so these patterns are defense
  # in depth: a child is a candidate only if its label was added after the split run ended, which the overseer checks
  # (DESIGN §18). No label or assignee tools; nothing that edits, moves, or closes an existing ticket; no PR, branch,
  # or file writes.
  "*label*": deny
  "*assign*": deny
  "*edit*": deny
  "*update*": deny
  "*transition*": deny
  "*close*": deny
  "*delete*": deny
  "*pull_request*": deny
  "*review*": deny
  "*merge*": deny
  "*branch*": deny
  "*push*": deny
  "*file*": deny
  "*fork*": deny
---
The system prompt is supplied by the harness at invocation time via the
`{prompt}` argument to `opencode run`. Keep this body minimal so the agent does
not act without a rendered prompt:

If you were started without a "# canopy worker: split" prompt, print
`no prompt supplied` and exit.
