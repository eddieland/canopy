---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, and `deny` is enforced under `opencode run`. Scalars are used where a
# whole tool is denied, since a repository's config cannot loosen a scalar canopy sets (D044).
# A chore reads and reports (DESIGN §19, TRUST_MODEL T6): its only output is its result line. A chore that runs the
# operator's own tools gets its own copy of this definition in the operator's runtime config, with bash allowed for
# exactly those tools, never in a repository's `.opencode/`.
description: canopy chore. Recurring read-only check the operator defines; reports findings, changes nothing.
mode: primary
permission:
  edit: deny
  # The one command it may run reads its own chore's earlier runs back (DESIGN §19, History); `canopy chore history`
  # refuses any other chore's. Everything else in bash is denied.
  bash:
    "*": deny
    "canopy chore history *": allow
  # No web tools: fetched and searched pages are text anyone can shape, the easiest way to steer an agent
  # (TRUST_MODEL T1, D077).
  webfetch: deny
  websearch: deny
  codesearch: deny
  external_directory: deny
  # Subagents run with their own, wider permissions; a chore must not reach them.
  task: deny
  # A chore reads the tracker and writes nothing to it (TRUST_MODEL T6). At the marked line canopy renders, off a GitHub
  # tracker, the tracker's server denied by a wildcard and each of its read tools allowed by name: OpenCode sends no
  # other tool of it, and a write no pattern names fails closed (D021). GitHub's issue reads stay, as the chore's prompt
  # is the operator's. On a GitHub tracker, whose server the PRs share, and with no read tools known, the line stays as
  # it is. The patterns below come after, so no allow reopens a write they close.
  # canopy: tracker reads
  # MCP tools are permissioned by name, `<server>_<tool>`, and names differ by server, so these patterns are defense
  # in depth: no tool that writes to the tracker, GitHub, or files, or asks Copilot to review or work.
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
  "*copilot*": deny
---

Your task is the prompt canopy starts this run with. If it does not end in a "## Run" section from canopy,
print `no prompt supplied` and exit.
