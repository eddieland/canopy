---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, and `deny` is enforced under `opencode run`. Scalars are used where a
# whole tool is denied, since a repository's config cannot loosen a scalar canopy sets (D044).
# The planner writes one file, its plan, and nothing else anywhere (DESIGN §25, TRUST_MODEL T1, T6). It reads the
# worktrees linked from its desk with OpenCode's read, list, glob, and grep tools, and the ticket with the tracker's
# read tools only. canopy renders this file into its definitions directory with the tracker's MCP server and tools from
# the operator's config (`tracker.mcp_server`, `tracker.read_tools`), at the marked line below, as for
# canopy-worker-private. As shipped it names none, and dispatch refuses a plan then (`no_read_tools`).
description: canopy planner. Writes a plan for one ticket before it is implemented; reads, and writes only its plan.
mode: primary
permission:
  bash: deny
  # No web tools: fetched and searched pages are text anyone can shape, the easiest way to steer an agent
  # (TRUST_MODEL T1, D077).
  webfetch: deny
  websearch: deny
  codesearch: deny
  external_directory: deny
  # Subagents run with their own, wider permissions; the planner must not reach them.
  task: deny
  # The operator's own `canopy` skill (`canopy skill --install`) is for their sessions, not canopy's agents.
  skill:
    "canopy": deny
  # MCP tools are permissioned by name, `<server>_<tool>`, and names differ by server, so these patterns are defense
  # in depth for servers other than the tracker's: commenting or replying anywhere, reviewing, and anything that
  # creates, pushes, writes files, changes labels, or edits or deletes. Reading stays allowed.
  "*add_*": deny
  "*addComment*": deny
  "*comment*": deny
  "*reply*": deny
  "*write*": deny
  "*pending_review*": deny
  "*submit*": deny
  "*approve*": deny
  "*create*": deny
  "*label*": deny
  "*assign*": deny
  "*edit*": deny
  "*update*": deny
  "*delete*": deny
  "*merge*": deny
  "*close*": deny
  "*transition*": deny
  "*push*": deny
  "*branch*": deny
  "*file*": deny
  "*fork*": deny
  "*copilot*": deny
  "*run_workflow*": deny
  "*run_trigger*": deny
  "*rerun*": deny
  "*cancel*": deny
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
  # And GitHub's reads of commits and code: the planner reads the code in its desk and its history with canopy's git
  # tools below, as it does on a GitHub tracker, whose rules allow it none of these.
  "*list_commits*": deny
  "*get_commit*": deny
  "*search_commits*": deny
  "*search_code*": deny
  # GitHub's issue tools, which only the `tracker-github` skill names: off a GitHub tracker, canopy renders their
  # denial at the marked line, so OpenCode sends none of them. Its issue comment tools stay, for a PR's conversation.
  # canopy: github issue tools
  # Every edit is denied but of `.canopy-new-plan.md` (`plans.WRITTEN`), which canopy reads from the desk's root when
  # the planner exits. Here, after the patterns above: OpenCode matches each key as a wildcard on the permission's name
  # too, so `*edit*` denies the edit tool, and a rule after this block would undo it. OpenCode matches an edit's path
  # relative to the project, `/` for a desk outside a checkout, and `*` crosses `/`; so the planner may also make a
  # file of that name in a worktree, which is reset with its slot and never read. `external_directory: deny` keeps every
  # edit inside the desk and its links. The planner canary in tests/canopy/test_opencode_canary.py checks it.
  edit:
    "*": deny
    ".canopy-new-plan.md": allow
    "*/.canopy-new-plan.md": allow
  # Every tool of the tracker's MCP server is denied by a wildcard, then only its read tools are allowed by name: the
  # last matching rule wins (D021), so a write tool missing from both lists fails closed.
  # canopy: tracker tools
  # canopy's read-only git tools, over this run's own checkouts alone (DESIGN §27), allowed by exact name: after every
  # pattern, so none above, such as `*merge*`, closes one.
  "canopy_git_merge-base": allow
  "canopy_git_diff": allow
  "canopy_git_log": allow
  "canopy_git_show": allow
  "canopy_git_blame": allow
  # A chore's own tool, which reads its history (DESIGN §19), is the chore's alone: last, so no rule above reopens it.
  "canopy_chore_history": deny
---

Your task is the prompt canopy starts this run with. If it is not a "# canopy worker: plan" prompt, print
`no prompt supplied` and exit.
