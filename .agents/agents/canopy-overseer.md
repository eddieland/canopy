---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Checked against OpenCode 1.18 in M1 (D021): the last matching permission rule wins, so each catch-all "*" comes
# before its exceptions. `ask` is auto-rejected under `opencode run`; `deny` is enforced. The old `tools:` map is
# deprecated in favor of `permission:`.
# The body is rendered: canopy puts the overseer's prompt at its marked line (DESIGN §6, §13).
# Its temperature is rendered at the marked line from `runtime.overseer_temperature`, unless that is -1: some models,
# such as OpenAI's reasoning models, refuse a request that sets one.
description: canopy overseer. Reads the state block, records decisions, dispatches workers through canopy's tools. Read-only otherwise.
mode: primary
# canopy: model
# canopy: temperature
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
  # OpenCode 2's code mode runs the model's JavaScript, which can make HTTP requests of its own, so it is a web
  # tool too (D077). An MCP server reached only through it is then out of reach: give it `codemode: false`.
  execute: deny
  # Subagents run with their own, wider permissions; the overseer must not reach them.
  task: deny
  # No shell of its own: the overseer acts through canopy's tools alone (DESIGN §27), and reads the pool from its state
  # block. Only the commands the operator names in `runtime.allow_bash` follow the deny.
  bash:
    "*": deny
    # The commands `runtime.allow_bash` names for the overseer, such as a tracker's CLI, are rendered at the marked
    # line, last, so that each is allowed (DESIGN §13). canopy refuses a shell, an interpreter, or its own tools there.
    # canopy: bash allows
  # Nothing to plan across calls: a tick's work is its decisions, each recorded as it is made.
  todowrite: deny
  # The operator's own `canopy` skill (`canopy skill --install`) is for their sessions, not canopy's agents. canopy
  # renders `"*": deny` at the marked line, last, so the tool is denied whole: the overseer reads no tracker, so it has
  # no skill to load (DESIGN §39).
  skill:
    "canopy": deny
    # The artifact store's skill is for the agents that publish to it (DESIGN §38).
    "canopy-artifacts": deny
    # canopy: skill rule
  # The overseer reaches no MCP server but canopy's (DESIGN §39, TRUST_MODEL T6), whatever servers the operator's
  # runtime config grants: the `tracker` source config requires and the `vcs` source read the tracker and GitHub for
  # it. Read from OpenCode 1.19.3's source: an MCP tool's name, and the permission it asks for, is `<server>_<tool>`,
  # joined by one `_` (`McpCatalog.toolName`, src/mcp/catalog.ts; src/session/tools.ts), and a tool whose last matching
  # rule denies `*` is not sent (`Permission.disabled`, src/permission/index.ts). No built-in tool's permission the
  # overseer uses holds a `_`: `disabled` checks `apply_patch` as `edit` and the MCP resource tools as `read`. So `*_*`
  # denies every server's tools, and catches besides only `external_directory`, denied above, `doom_loop`, which
  # `opencode run` rejects as an `ask`, and the experimental `plan_exit`, which the overseer has no use for. canopy's
  # own tools are allowed after it, by name.
  "*_*": deny
  # The MCP resource tools read any server's resources and ask `read` for `mcp:<server>:<uri>`
  # (src/session/tools.ts): denied, leaving `read` of a file as it was. canopy's server has no resources.
  read:
    "mcp:*": deny
  # The artifact store's MCP server, `artifacts.mcp_server`, is for the agents `artifacts.publish_roles` names
  # (DESIGN §38): canopy renders it denied whole at the marked line.
  # canopy: artifact tools
  # canopy's own tools, from the server the harness names in this run's inline config alone (DESIGN §27): every tool of
  # a server whose name starts `canopy_` is denied, the reviewer's and planner's git tools, a chore's history, and the
  # reports among them, then each of the overseer's is allowed by its exact name, last so no pattern above takes one
  # back. An allow by pattern would also match another server's tools.
  "canopy_*": deny
  "canopy_dispatch": allow
  "canopy_decide": allow
  "canopy_attention": allow
  "canopy_ticket-set": allow
  "canopy_review-run": allow
  "canopy_review-wait": allow
  "canopy_review-end": allow
  "canopy_review-revise": allow
  "canopy_chore-run": allow
  "canopy_chore-wait": allow
---

<!-- canopy: overseer prompt -->
canopy renders the overseer's prompt in place of the marker line above and all that follows it, when it snapshots
its definitions (DESIGN §13), so the prompt is the agent's system prompt and each tick's message is its state block.

You were started from a definition canopy did not render. Print `no prompt supplied` and exit.
