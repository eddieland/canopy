---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, and `deny` is enforced under `opencode run`. Scalars are used where a
# whole tool is denied, since a repository's config cannot loosen a scalar canopy sets (D044).
# The agent of the example chore `briefing`, which tells the operator what waits on them and what changed.
# `canopy chore install` copies it into the workspace beside the chore's prompt, and the chore's `cmd` loads that copy,
# which stays as installed until the chore is installed again. It is `canopy-chore` with the one report of canopy's its
# prompt reads allowed as a tool; like it, it has no shell. A chore reads and reports (DESIGN §19, TRUST_MODEL T6): its
# only output is its result line. Everything but the report it allows is `canopy-chore`'s; keep the two in step.
description: canopy chore that briefs the operator on what waits on them. Reports a summary, changes nothing.
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
  # OpenCode 2's code mode runs the model's JavaScript, which can make HTTP requests of its own, so it is a web
  # tool too (D077). An MCP server reached only through it is then out of reach: give it `codemode: false`.
  execute: deny
  # Reads outside its directory are denied, except in the skill directories of the operator's home, where OpenCode 1
  # finds them: loading a skill reads its SKILL.md whatever this says, and these let the agent read the files beside it,
  # its references and scripts. It writes nothing, so reading is all it can do there. OpenCode expands `~/`, and `*`
  # crosses `/` (read from OpenCode 1.19.3). A table, unlike a scalar, is one a repository's config past the check D044
  # makes could add a rule to (TRUST_MODEL T7).
  external_directory:
    "*": deny
    "~/.claude/skills/*": allow
    "~/.agents/skills/*": allow
    "~/.config/opencode/skills/*": allow
    "~/.config/opencode/skill/*": allow
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
  # canopy's own tools, the overseer's, the reviewer's and planner's git tools, and the reports this agent does not
  # read, are not its (DESIGN §27): denied by pattern, before its exceptions below.
  "canopy_*": deny
  # Its tools of canopy's, each allowed by exact name: last, so no pattern above closes one. Its own chore's earlier
  # runs (DESIGN §19, History), which refuses any other chore's, and the report its prompt names (DESIGN §27), which
  # writes nothing.
  "canopy_chore_history": allow
  # And the `result` tool of the same server, which validates a result and writes nothing (DESIGN §13).
  "canopy_chore_result": allow
  "canopy_reports_waiting": allow
---

The system prompt is supplied by the harness at invocation time via the
`{prompt}` argument to `opencode run`. Keep this body minimal so the agent does
not act without a rendered prompt:

If you were started without a prompt ending in a "## Run" section from canopy,
print `no prompt supplied` and exit.
