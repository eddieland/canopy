---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, so each catch-all "*" comes before its exceptions. `ask` is
# auto-rejected under `opencode run`; `deny` is enforced. Bash compound commands are checked command by command.
# These permissions are defense in depth, not the boundary (TRUST_MODEL T4). Branch protection governs where pushes can
# land (TRUST_MODEL T1), and `canopy _run` verifies what was pushed.
# canopy-worker for a private ticket (DESIGN §22): the same rules, and none of the tracker's tools but the reads and the
# ones that create a ticket, for its follow-ups (§18). canopy renders this file into its definitions directory with the
# tracker's MCP server and tools from the operator's config (`tracker.mcp_server`, `tracker.read_tools`) and the
# provider's create tools, at the marked line below. As shipped it names none.
description: canopy private worker. Works one private ticket; pushes a branch, opens a PR, never writes to the ticket.
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
    # The artifact store's skill is for the agents that publish to it (DESIGN §38).
    "canopy-artifacts": deny
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
    "gh pr comment*": deny
    "gh issue comment*": deny
    # The loop's own tools belong to the harness and the overseer, but for the search the memory digests name, which
    # reads only what this run's prompt could be served (DESIGN §28) and writes nothing.
    "canopy *": deny
    "canopy memory search *": allow
    "treehouse *": deny
    "sudo *": deny
    # The tracker CLIs canopy knows: a private ticket's conversation never reaches the tracker (TRUST_MODEL T6).
    "gh": deny
    "gh *": deny
    "acli": deny
    "acli *": deny
    "jira": deny
    "jira *": deny
    # Reading a PR and its CI writes nothing, and these read no ticket: a resumed worker reads the review comments it
    # was pointed at, and the failing checks and their logs, as `canopy-worker` can. `gh pr edit` writes only to a PR,
    # as the GitHub server's PR update tool allowed below does, and resolves no issue, so it cannot reach the ticket.
    # Compound commands are checked command by command, so none of these lets another `gh` command through.
    "gh pr view": allow
    "gh pr view *": allow
    "gh pr checks": allow
    "gh pr checks *": allow
    "gh pr diff": allow
    "gh pr diff *": allow
    "gh pr edit": allow
    "gh pr edit *": allow
    "gh run view": allow
    "gh run view *": allow
  # MCP tools are permissioned by name, `<server>_<tool>`, as for canopy-worker (D084): the private worker opens and
  # updates its PRs and replies on them, and nothing else. Its PR update tool can close the PR; the prompt keeps it to
  # the PR's own text. tests/canopy/core/test_definitions.py checks these rules against real tool names.
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
  "*issue_read*": deny
  "*list_issues*": deny
  "*search_issues*": deny
  "*issue_write*": deny
  "*list_issue_types*": deny
  "*list_issue_fields*": deny
  "*get_label*": deny
  # Every tool of the tracker's MCP server is denied by a wildcard, then only its read tools, the tool that creates a
  # ticket, and, where it is GitHub's, the tools that open, update, and reply on a PR, are allowed by name, whole: the
  # last matching rule wins (D021), so a write tool missing from these lists fails closed. GitHub's `issue_write` also
  # edits and closes issues; the prompt keeps it to filing follow-ups.
  # canopy: tracker tools
  "atlassian_*": deny
  "atlassian_atlassianUserInfo": allow
  "atlassian_getAccessibleAtlassianResources": allow
  "atlassian_getJiraIssue": allow
  "atlassian_getJiraIssueTypeMetaWithFields": allow
  "atlassian_listJiraIssueChangelogs": allow
  "atlassian_listJiraIssueComments": allow
  "atlassian_listJiraIssueLinkTypes": allow
  "atlassian_listJiraIssueRemoteIssueLinks": allow
  "atlassian_listJiraProjectIssueTypesMetadata": allow
  "atlassian_listJiraProjects": allow
  "atlassian_lookupJiraAccountId": allow
  "atlassian_searchJiraIssuesUsingJql": allow
  "atlassian_createJiraIssue": allow
  # With `trust.review_replies = "approve"`, canopy renders the denial of the GitHub server's comment tools here, last,
  # so that it beats the tracker's allow of GitHub's reply tool.
  # canopy: reply tools
  "*reply_to_pull_request_comment*": deny
  "*add_comment_to_pending_review*": deny
  "*add_issue_comment*": deny
  # The artifact store's MCP server, `artifacts.mcp_server`: this agent never publishes, whatever config says
  # (DESIGN §38), and canopy renders the server denied whole at the marked line.
  # canopy: artifact tools
  # canopy's read-only git tools are the reviewer's and the planner's alone (DESIGN §27): after every pattern, so none
  # above reopens one.
  "canopy_git_*": deny
  # A chore's own tool, which reads its history (DESIGN §19), is the chore's alone: last, so no rule above reopens it.
  "canopy_chore_history": deny
---

Your task is the prompt canopy starts this run with. If it is not a "# canopy private worker" prompt,
print `no prompt supplied` and exit.
