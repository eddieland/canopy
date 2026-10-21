---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, and `deny` is enforced under `opencode run`. Scalars are used where a
# whole tool is denied, since a repository's config cannot loosen a scalar canopy sets (D044).
# The reviewer reads a PR and writes nothing anywhere: its result line is the review (DESIGN §21, D114, TRUST_MODEL T4,
# T6). It starts in a directory of canopy's, outside the checkout, which it reads through the link `checkout`; reads
# outside that directory are denied, as for a desk's links (the reviewer canary in tests/canopy/test_opencode_canary.py
# checks it). It reads the checkout's history through canopy's git tools, allowed last.
# Its temperature is rendered at the marked line from `runtime.review_temperature`, unless that is -1: the reviewer is
# meant to run on another model than the worker's (DESIGN §21), and some, such as OpenAI's reasoning models, refuse a
# request that sets one.
description: canopy reviewer. Adversarial review of one PR at one commit; read-only; posts nothing, never approves.
mode: primary
# canopy: temperature
permission:
  edit: deny
  bash: deny
  # No web tools: fetched and searched pages are text anyone can shape, the easiest way to steer an agent
  # (TRUST_MODEL T1, D077).
  webfetch: deny
  websearch: deny
  codesearch: deny
  external_directory: deny
  # Subagents run with their own, wider permissions; the reviewer must not reach them.
  task: deny
  # The operator's own `canopy` skill (`canopy skill --install`) is for their sessions, not canopy's agents.
  skill:
    "canopy": deny
  # The reviewer reads the ticket and writes nothing to it (TRUST_MODEL T6). At the marked line canopy renders, off a
  # GitHub tracker, GitHub's issue reads denied, then the tracker's server denied by a wildcard and each of its read
  # tools allowed by name, so a write tool no pattern names fails closed (D021). On a GitHub tracker, whose server the
  # PR's reads go through, and with no read tools known, the line stays as it is. The patterns below come after, so no
  # allow reopens a write they close.
  # canopy: tracker reads
  # MCP tools are permissioned by name, `<server>_<tool>`, and names differ by server, so these patterns are defense
  # in depth. Denied: commenting or replying anywhere, submitting a PR review (it can approve), asking Copilot for one,
  # and anything that pushes, writes files, changes labels, or edits or deletes. Reading stays allowed.
  "*add_*": deny
  "*addComment*": deny
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
  # And GitHub's reads that only a write needs, for an issue the reviewer never files or labels: its types and fields,
  # and a label's definition.
  "*list_issue_types*": deny
  "*list_issue_fields*": deny
  "*get_label*": deny
  # A chore's own tool, which reads its history (DESIGN §19), is the chore's alone: last, so no rule above reopens it.
  "canopy_chore_history": deny
  # canopy's tools that read the checkout's history and write nothing (DESIGN §27), each allowed by exact name, never
  # by a pattern another server's tool could match: last, so no pattern above, such as `*merge*`, closes one.
  "canopy_git_merge-base": allow
  "canopy_git_diff": allow
  "canopy_git_log": allow
  "canopy_git_show": allow
---

Your task is the prompt canopy starts this run with. If it is not a "# canopy reviewer" prompt, print
`no prompt supplied` and exit.
