---
# OpenCode agent definition. Agent runs load it from canopy's definitions directory (DESIGN §13, D040).
# Rules follow D021: the last matching rule wins, and `deny` is enforced under `opencode run`. Scalars are used where a
# whole tool is denied, since a repository's config cannot loosen a scalar canopy sets (D044).
# The reviewer reads a PR and writes nothing anywhere: its result line is the review (DESIGN §21, D114, TRUST_MODEL T4,
# T6). It starts in a directory of canopy's, outside the checkout, which it reads through the link `checkout`; reads
# outside that directory are denied, as for a desk's links (the reviewer canary in tests/canopy/test_opencode_canary.py
# checks it).
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
  # Nothing outside the working directory but where OpenCode saves a tool output too long to return whole, for the
  # agent to read as the cut output says. OpenCode allows that on its own too; this does not rely on it.
  external_directory:
    "*": deny
    "~/.local/share/opencode/tool-output/*": allow
  # Subagents run with their own, wider permissions; the reviewer must not reach them.
  task: deny
  # MCP tools are permissioned by name, `<server>_<tool>`, and names differ by server, so these patterns are defense
  # in depth. Denied: commenting or replying anywhere, submitting a PR review (it can approve), and anything that
  # pushes, writes files, changes labels, or edits or deletes. Reading stays allowed.
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
---

The system prompt is supplied by the harness at invocation time via the
`{prompt}` argument to `opencode run`. Keep this body minimal so the agent does
not act without a rendered prompt:

If you were started without a "# canopy reviewer" prompt, print
`no prompt supplied` and exit.
