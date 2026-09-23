---
# OpenCode agent definition. Installed to .opencode/agent/canopy-overseer.md by `canopy init`.
# Verify field names against current OpenCode docs in M1; permission semantics
# under `opencode run` are an open question (DESIGN §16, ROADMAP M1 canary).
description: canopy overseer. Reads tracker and GitHub state, records decisions, dispatches workers through the canopy CLI. Read-only otherwise.
mode: primary
temperature: 0.1
tools:
  write: false
  edit: false
  patch: false
permission:
  edit: deny
  write: deny
  bash:
    "canopy *": allow
    "treehouse status*": allow
    "*": deny
---
The system prompt is supplied by the harness at invocation time via the
`{prompt}` argument to `opencode run`. Keep this body minimal so the agent does
not act without a rendered prompt:

If you were started without a "# canopy overseer" prompt, print
`no prompt supplied` and exit.
