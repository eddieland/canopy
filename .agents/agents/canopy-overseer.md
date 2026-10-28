---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Checked against OpenCode 1.18 in M1 (D021): the last matching permission rule wins, so each catch-all "*" comes
# before its exceptions. `ask` is auto-rejected under `opencode run`; `deny` is enforced. The old `tools:` map is
# deprecated in favor of `permission:`.
# The body is rendered: canopy puts the overseer's prompt at its marked line (DESIGN §6, §13).
# Its temperature is rendered at the marked line from `runtime.overseer_temperature`, unless that is -1: some models,
# such as OpenAI's reasoning models, refuse a request that sets one.
description: canopy overseer. Reads tracker and GitHub state, records decisions, dispatches workers through canopy's tools. Read-only otherwise.
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
  # The operator's own `canopy` skill (`canopy skill --install`) is for their sessions, not canopy's agents. With the
  # tracker's skill in its body, canopy renders `"*": deny` at the marked line, last, so the tool is denied whole: the
  # overseer has nothing to load. Otherwise the prompt has it load the skill by name, if there is one.
  skill:
    "canopy": deny
    # The artifact store's skill is for the agents that publish to it (DESIGN §38).
    "canopy-artifacts": deny
    # canopy: skill rule
  # The overseer only reads the tracker (TRUST_MODEL T6). At the marked line canopy renders the tracker's server denied
  # by a wildcard, then each of its read tools allowed by name: for GitHub, whose server it shares, the reads kept
  # below. Off a GitHub tracker, GitHub's issue reads are denied first, and an allow after them reopens a read of the
  # tracker's they match. The denials below come after, so no allow reopens a write they close. With no read tools
  # known, the line stays as it is. Where a `tracker` source runs, beside the `vcs` source, the overseer reads neither
  # (DESIGN §39): canopy renders there the GitHub reads kept below denied by pattern, and the tracker's server whole
  # where it knows it.
  # canopy: tracker reads
  # GitHub's MCP tools are permissioned by name, `<server>_<tool>`, and the server's name is the operator's, so each
  # tool is denied by its own: OpenCode sends no tool a rule denies whole, which cuts each tick's request. Kept are the
  # reads the prompt makes, PRs (with their checks, reviews, comments, and merge state) and branches; issues, when they
  # are the tickets; and the signed-in user, too small to matter. Every write is denied (TRUST_MODEL T6).
  "*merge_pull_request*": deny
  "*create_pull_request*": deny
  "*update_pull_request*": deny
  "*pull_request_review_write*": deny
  "*add_comment_to_pending_review*": deny
  "*add_reply_to_pull_request_comment*": deny
  "*add_issue_comment*": deny
  "*update_issue_comment*": deny
  "*issue_write*": deny
  "*create_branch*": deny
  "*create_or_update_file*": deny
  "*push_files*": deny
  "*delete_file*": deny
  "*create_repository*": deny
  "*fork_repository*": deny
  "*copilot*": deny
  # Reads the prompt has no use for: commits, code and files, what creating an issue takes, and the tools below that
  # no canopy prompt asks for.
  "*get_commit*": deny
  "*list_commits*": deny
  "*search_commits*": deny
  "*search_code*": deny
  "*get_file_contents*": deny
  "*get_label*": deny
  "*list_issue_types*": deny
  "*list_issue_fields*": deny
  "*get_teams*": deny
  "*get_team_members*": deny
  "*search_users*": deny
  "*ui_get*": deny
  "*list_releases*": deny
  "*get_latest_release*": deny
  "*get_release_by_tag*": deny
  "*list_tags*": deny
  "*get_tag*": deny
  "*search_repositories*": deny
  "*list_repository_collaborators*": deny
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
  "canopy_queried": allow
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
