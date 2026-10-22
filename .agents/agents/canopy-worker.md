---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, so each catch-all "*" comes before its exceptions. `ask` is
# auto-rejected under `opencode run`; `deny` is enforced. Bash compound commands are checked command by command.
# These permissions are defense in depth, not the boundary (TRUST_MODEL T4). Branch protection governs where pushes can
# land (TRUST_MODEL T1), and `canopy _run` verifies what was pushed.
description: canopy worker. Works one ticket in a leased worktree; pushes a branch, opens a PR, comments.
mode: primary
permission:
  # Edits inside the worktree, which is the working directory `canopy _run` starts the worker in. Files outside it
  # are refused. A joint run's working directory is its desk, whose links lead to the worktrees it leased (DESIGN
  # §18); the desk canary in tests/canopy/test_opencode_canary.py checks edits follow them and go nowhere else.
  edit: allow
  external_directory: deny
  # Subagents run with their own, wider permissions; the worker must not reach them.
  task: deny
  # The operator's own `canopy` skill (`canopy skill --install`) is for their sessions, not canopy's agents.
  skill:
    "canopy": deny
    # The artifact store's skill is for the agents that publish to it (DESIGN §38): with the worker among
    # `artifacts.publish_roles`, canopy renders its allow at the marked line.
    "canopy-artifacts": deny
    # canopy: artifact skill
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
    # With `trust.review_replies = "approve"`, canopy renders the denial of `gh`'s commands that comment at the marked
    # line: the worker drafts its comments, and the operator sends them (DESIGN §29).
    # canopy: reply rules
    # The loop's own tools belong to the harness and the overseer, but for the search the memory digests name, which
    # reads only what this run's prompt could be served (DESIGN §28) and writes nothing.
    "canopy *": deny
    "canopy memory search *": allow
    "treehouse *": deny
    "sudo *": deny
    # The commands `runtime.allow_bash` names for the worker are rendered at the marked line, last, so that each beats
    # a deny above (DESIGN §13). canopy refuses git, gh, a shell, a wrapper such as sudo, or its own tools there.
    # canopy: bash allows
  # MCP tools are permissioned by name, `<server>_<tool>`, and names differ by server, so these patterns are defense
  # in depth, whatever write tools the operator's runtime config grants (D084). The worker comments on its ticket,
  # edits the ticket's labels, opens and updates its PRs, and creates follow-up tickets linked to its ticket (DESIGN
  # §18, TRUST_MODEL T6). Denied: merging, review submissions, closing, transitions, sub-issues, writing files or
  # branches through the API instead of git, deleting, forking, and starting other agents or workflow runs. GitHub's
  # `issue_write` creates and closes issues as well as labelling them, and its PR update tool can close the PR; neither
  # has a narrower name to deny, so the prompt keeps them to creating follow-ups, labels, and the PR's title and body.
  # tests/canopy/core/test_definitions.py checks these rules against real tool names.
  "*merge*": deny
  "*review_write*": deny
  "*pending_review*": deny
  "*create_pull_request_review*": deny
  "*submit*": deny
  "*approve*": deny
  "*close*": deny
  "*transition*": deny
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
  # GitHub's tools that no canopy prompt asks for, denied by name: OpenCode sends no tool a rule denies whole, so each
  # request is smaller. Its teams, users, and UI data; releases and tags; repository search; and collaborators.
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
  # GitHub's issue tools, which only the `tracker-github` skill names: off a GitHub tracker, canopy renders their
  # denial at the marked line, so OpenCode sends none of them. Its issue comment tools stay, for a PR's conversation.
  # canopy: github issue tools
  # With `trust.review_replies = "approve"`, canopy renders the denial of the GitHub server's comment tools here.
  # canopy: reply tools
  # The artifact store's MCP server, `artifacts.mcp_server` (DESIGN §38): canopy renders it denied whole at the
  # marked line, then, with the worker among `artifacts.publish_roles`, the tools it publishes with allowed by
  # name, after every pattern above.
  # canopy: artifact tools
  # canopy's read-only git tools are the reviewer's and the planner's alone (DESIGN §27): after every pattern, so none
  # above reopens one.
  "canopy_git_*": deny
  # A chore's own tool, which reads its history (DESIGN §19), is the chore's alone: last, so no rule above reopens it.
  "canopy_chore_history": deny
---

Your task is the prompt canopy starts this run with. If it is not a "# canopy worker" prompt, print
`no prompt supplied` and exit.
