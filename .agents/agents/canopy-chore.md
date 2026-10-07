---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, and `deny` is enforced under `opencode run`. Scalars are used where a
# whole tool is denied, since a repository's config cannot loosen a scalar canopy sets (D044).
# A chore reads and reports (DESIGN §19, TRUST_MODEL T6): its only output is its result line. A chore that runs the
# operator's own tools gets its own copy of this definition in the operator's runtime config, with bash allowed for
# exactly those tools, never in a repository's `.opencode/`.
description: canopy chore. Recurring read-only check the operator defines; reports findings, changes nothing.
mode: primary
temperature: 0.1
permission:
  edit: deny
  bash: deny
  external_directory: deny
  # Subagents run with their own, wider permissions; a chore must not reach them.
  task: deny
  # MCP tools are permissioned by name, `<server>_<tool>`, and names differ by server, so these patterns are defense
  # in depth: no tool that writes to the tracker, GitHub, or files.
  "*create*": deny
  "*comment*": deny
  "*label*": deny
  "*assign*": deny
  "*edit*": deny
  "*update*": deny
  "*write*": deny
  "*transition*": deny
  "*close*": deny
  "*delete*": deny
  "*merge*": deny
  "*approve*": deny
  "*submit*": deny
  "*rerun*": deny
  "*cancel*": deny
  "*dispatch*": deny
  "*push*": deny
  "*branch*": deny
  "*fork*": deny
---
The system prompt is supplied by the harness at invocation time via the
`{prompt}` argument to `opencode run`. Keep this body minimal so the agent does
not act without a rendered prompt:

If you were started without a prompt ending in a "## Run" section from canopy,
print `no prompt supplied` and exit.
