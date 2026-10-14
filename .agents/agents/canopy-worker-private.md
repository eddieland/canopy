---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, so each catch-all "*" comes before its exceptions. `ask` is
# auto-rejected under `opencode run`; `deny` is enforced. Bash compound commands are checked command by command.
# These permissions are defense in depth, not the boundary (TRUST_MODEL T4). Branch protection governs where pushes can
# land (TRUST_MODEL T1), and `canopy _run` verifies what was pushed.
# canopy-worker for a private ticket (DESIGN §22): the same rules, and none of the tracker's tools but the reads.
# canopy renders this file into its definitions directory with the tracker's MCP server and tools from the operator's
# config (`tracker.mcp_server`, `tracker.read_tools`), at the marked line below. As shipped it names none.
description: canopy private worker. Works one private ticket; pushes a branch, opens a PR, never writes to the ticket.
mode: primary
temperature: 0.2
permission:
  # Edits inside the worktree, which is the working directory `canopy _run` starts the worker in. Files outside it
  # are refused. A joint run's working directory is its desk, whose links lead to the worktrees it leased (DESIGN
  # §18); the desk canary in tests/canopy/test_opencode_canary.py checks edits follow them and go nowhere else.
  edit: allow
  external_directory: deny
  # Subagents run with their own, wider permissions; the worker must not reach them.
  task: deny
  # No web tools: fetched and searched pages are text anyone can shape, the easiest way to steer an agent
  # (TRUST_MODEL T1, D077). Bash can still reach the network, for package installs and builds; this removes the tools
  # a model reaches for on its own, not the capability.
  webfetch: deny
  websearch: deny
  codesearch: deny
  bash:
    "*": allow
    # Pushes are plain ones: no force, no deletes, no mirrors or bulk ref updates. Patterns anchor on a space before
    # a short flag so that branch names such as agent/PROJ-1-fix-typo still match nothing. With `trust.rebase` set,
    # canopy renders the one forced push the prompts name, `--force-with-lease` to a branch, at the marked line.
    "git push *--force*": deny
    # canopy: rebase rules
    "git push -f*": deny
    "git push * -f*": deny
    "git push *--delete*": deny
    "git push -d*": deny
    "git push * -d*": deny
    "git push *--mirror*": deny
    "git push *--all*": deny
    "git push *--tags*": deny
    "git push *--prune*": deny
    "git push * :*": deny
    "git push * +*": deny
    # Never merge, approve, or close; never move the ticket (TRUST_MODEL §6).
    "gh pr merge*": deny
    "gh pr review*": deny
    "gh pr close*": deny
    "gh issue close*": deny
    "gh api*": deny
    # The loop's own tools belong to the harness and the overseer.
    "canopy *": deny
    "treehouse *": deny
    "sudo *": deny
    # The tracker CLIs canopy knows: a private ticket's conversation never reaches the tracker (TRUST_MODEL T6).
    "gh": deny
    "gh *": deny
    "acli": deny
    "acli *": deny
    "jira": deny
    "jira *": deny
  # MCP tools are permissioned by name, `<server>_<tool>`, as for canopy-worker (D084): the private worker opens and
  # updates its PRs and replies on them, and nothing else. Its PR update tool can close the PR; the prompt keeps it to
  # the PR's own text. tests/canopy/test_definitions.py checks these rules against real tool names.
  "*merge*": deny
  "*review_write*": deny
  "*pending_review*": deny
  "*create_pull_request_review*": deny
  "*submit*": deny
  "*approve*": deny
  "*close*": deny
  "*transition*": deny
  "*create_issue*": deny
  "*createJiraIssue*": deny
  "*sub_issue*": deny
  "*create_branch*": deny
  "*create_or_update_file*": deny
  "*push_files*": deny
  "*delete*": deny
  "*fork*": deny
  "*create_repository*": deny
  "*copilot*": deny
  "*run_workflow*": deny
  "*run_trigger*": deny
  "*rerun*": deny
  "*cancel*": deny
  "*createConfluence*": deny
  "*updateConfluence*": deny
  # Every tool of the tracker's MCP server is denied by a wildcard, then only its read tools are allowed by name: the
  # last matching rule wins (D021), so a write tool missing from both lists fails closed.
  # canopy: tracker tools
---

The system prompt is supplied by the harness at invocation time via the
`{prompt}` argument to `opencode run`. Keep this body minimal so the agent does
not act without a rendered prompt:

If you were started without a "# canopy private worker" prompt, print
`no prompt supplied` and exit.
