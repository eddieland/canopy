---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Checked against OpenCode 1.18 in M1 (D021): the last matching permission rule wins, so each catch-all "*" comes
# before its exceptions. `ask` is auto-rejected under `opencode run`; `deny` is enforced. The old `tools:` map is
# deprecated in favor of `permission:`.
description: canopy overseer. Reads tracker and GitHub state, records decisions, dispatches workers through the canopy CLI. Read-only otherwise.
mode: primary
temperature: 0.1
permission:
  edit: deny
  # No web tools: fetched and searched pages are text anyone can shape, the easiest way to steer an agent
  # (TRUST_MODEL T1, D077).
  webfetch: deny
  websearch: deny
  codesearch: deny
  # Subagents run with their own, wider permissions; the overseer must not reach them.
  task: deny
  bash:
    "*": deny
    "canopy *": allow
    "treehouse status*": allow
---

The system prompt is supplied by the harness at invocation time via the
`{prompt}` argument to `opencode run`. Keep this body minimal so the agent does
not act without a rendered prompt:

If you were started without a "# canopy overseer" prompt, print
`no prompt supplied` and exit.
