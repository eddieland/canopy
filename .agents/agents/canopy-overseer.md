---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Checked against OpenCode 1.18 in M1 (D021): the last matching permission rule wins, so each catch-all "*" comes
# before its exceptions. `ask` is auto-rejected under `opencode run`; `deny` is enforced. The old `tools:` map is
# deprecated in favor of `permission:`.
# The body is rendered: canopy puts the overseer's prompt at its marked line (DESIGN §6, §13).
description: canopy overseer. Reads tracker and GitHub state, records decisions, dispatches workers through the canopy CLI. Read-only otherwise.
mode: primary
temperature: 0.1
permission:
  edit: deny
  # A path outside the workspace would otherwise `ask`, which ends the run and loses every decision not yet recorded.
  # `deny` refuses the one call and the overseer goes on.
  external_directory: deny
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

<!-- canopy: overseer prompt -->
canopy renders the overseer's prompt in place of the marker line above and all that follows it, when it snapshots
its definitions (DESIGN §13), so the prompt is the agent's system prompt and each tick's message is its state block.

You were started from a definition canopy did not render. Print `no prompt supplied` and exit.
