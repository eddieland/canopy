---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, so each catch-all "*" comes before its exceptions. `ask` is
# auto-rejected under `opencode run`; `deny` is enforced. Bash compound commands are checked command by command.
# These permissions are defense in depth, not the boundary (TRUST_MODEL T4). Branch protection governs where pushes can
# land (TRUST_MODEL T1), and `canopy _run` verifies what was pushed.
description: canopy worker. Works one ticket in a leased worktree; pushes a branch, opens a PR, comments.
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
  # MCP tools are permissioned by name, `<server>_<tool>`, and names differ by server, so these patterns are defense
  # in depth, whatever write tools the operator's runtime config grants (D084). The worker comments on its ticket,
  # edits the ticket's labels, and opens and updates its PRs. Denied: merging, review submissions, closing,
  # transitions, creating tickets, writing files or branches through the API instead of git, deleting, forking, and
  # starting other agents or workflow runs. GitHub's `issue_write` creates and closes issues as well as labelling them,
  # and its PR update tool can close the PR; neither has a narrower name to deny, so the prompt keeps them to labels
  # and the PR's title and body. tests/canopy/test_definitions.py checks these rules against real tool names.
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
---

The system prompt is supplied by the harness at invocation time via the
`{prompt}` argument to `opencode run`. Keep this body minimal so the agent does
not act without a rendered prompt:

If you were started without a "# canopy worker" prompt, print
`no prompt supplied` and exit.
