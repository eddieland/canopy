---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, and `deny` is enforced under `opencode run`. Scalars are used where a
# whole tool is denied, since a repository's config cannot loosen a scalar canopy sets (D044).
# The agent of the example chores that look at canopy itself, canopy-health and canopy-efficiency.
# `canopy chore install` copies it into the workspace beside the chore's prompt, and the chore's `cmd` loads that copy,
# which stays as installed until the chore is installed again. It is `canopy-chore` with the reports of canopy's its
# prompts read allowed as tools; like it, it has no shell. A chore reads and reports (DESIGN §19, TRUST_MODEL T6): its
# only output is its result line. Everything but the reports it allows is `canopy-chore`'s; keep the two in step.
description: canopy chore that reads canopy's own health, spend, and runs. Reports findings, changes nothing.
mode: primary
permission:
  edit: deny
  # It reads its history and canopy's reports through canopy's tools, below, not a shell.
  bash: deny
  # No web tools: fetched and searched pages are text anyone can shape, the easiest way to steer an agent
  # (TRUST_MODEL T1, D077).
  webfetch: deny
  websearch: deny
  codesearch: deny
  external_directory: deny
  # Subagents run with their own, wider permissions; a chore must not reach them.
  task: deny
  # The operator's own `canopy` skill (`canopy skill --install`) is for their sessions, not canopy's agents.
  skill:
    "canopy": deny
    # The artifact store's skill is for the agents that publish to it (DESIGN §38).
    "canopy-artifacts": deny
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
  # canopy's read-only git tools are the reviewer's and the planner's alone (DESIGN §27): after every pattern, so none
  # above reopens one.
  "canopy_git_*": deny
  # Its tools of canopy's, each allowed by exact name: last, so no pattern above closes one. Its own chore's earlier
  # runs (DESIGN §19, History), which refuses any other chore's, and the reports its prompts name (DESIGN §27), each
  # of which writes nothing: `show-run` and `show-chore` and no ticket's page, which holds its conversation; the
  # reports' server's other tools are denied.
  "canopy_reports_*": deny
  "canopy_chore_history": allow
  "canopy_reports_health": allow
  "canopy_reports_spend": allow
  "canopy_reports_decisions": allow
  "canopy_reports_show-run": allow
  "canopy_reports_show-chore": allow
  "canopy_reports_config-show": allow
  "canopy_reports_agents": allow
---

The system prompt is supplied by the harness at invocation time via the
`{prompt}` argument to `opencode run`. Keep this body minimal so the agent does
not act without a rendered prompt:

If you were started without a prompt ending in a "## Run" section from canopy,
print `no prompt supplied` and exit.
