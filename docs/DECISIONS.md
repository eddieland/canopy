# Decisions

Append-only. One entry per choice that someone might later want to revisit.
Format: context, decision, consequences, and what would make us revisit.

## D001. Do not build on Azimuth

Context: Azimuth encoded the workflow in code, was hard to grow, and never
shipped as something a second person could run. treehouse solves worktree
problems Azimuth had.
Decision: new repository, no shared code.
Revisit: never; salvage ideas, not code.

## D002. treehouse is the worktree pool

Context: pooled, reusable worktrees with durable leases, dirty and in-use
detection, safe prune, no daemon, JSON output.
Decision: hard dependency. canopy wraps `status --json`, `get --lease --json`,
`return --force --if-lease-id --if-lease-holder`. Lease holder is
`canopy:<TICKET>`.
Consequences: worktrees are ephemeral; the pushed branch is the checkpoint.
Revisit: if treehouse's lease semantics change incompatibly.

## D003. Connectivity through the agent runtime's MCP, not harness code

Context: Jira and GitHub are reachable as remote MCP servers with OAuth
handled by the runtime.
Decision: the harness imports no tracker or VCS client and never sees a token.
Tracker specifics are prompt and config.
Consequences: the harness cannot poll Jira or GitHub itself; the overseer
does, each tick, guided by cursors in the journal. A second tracker is a
prompt edit.
Revisit: if the overseer's token cost for reading state dominates, or if
MCP client auth from a script becomes trivial. Then move polling into Python.

## D004. SQLite journal plus flock, not a stateless overseer

Context: a stateless design hid state in ticket comments and label timestamps,
which is slower, noisier for teammates, and unqueryable.
Decision: SQLite in WAL mode with numbered migrations; `flock` around the
tick. The journal owns loop facts only; world facts are always re-read.
Consequences: cursors, attempt counts, cooldowns, crash detection, and an
audit log are all queries.
Revisit: multi-machine operation (not planned).

## D005. Aggressive release of worktrees

Decision: hold a slot only while a worker process is running. Waiting on CI,
review, or a human holds nothing. Worker pushes before release, always.
Consequences: reacquisition lands on any slot, so build caches must be
slot-independent; repository concern, documented.
Revisit: if reacquisition cost is measured to exceed the capacity gained.

## D006. OpenCode as the agent runtime, not Pi

Context: Pi is a minimal, extensible agent with a TypeScript extension API,
print/JSON/RPC/SDK modes, and deliberately no built-in MCP, no permission
prompts, and no sub-agents; those are meant to be added by extensions or run
in a container. OpenCode has built-in MCP (including remote OAuth servers),
agent definitions with per-tool permissions, non-interactive `opencode run
--agent`, TypeScript plugins, and a server/SDK.
Decision: OpenCode.
Reasons:
1. D003 depends on the runtime doing MCP and OAuth. OpenCode does this out of
   the box; Pi would need an extension for it, which puts connectivity code
   back in our hands.
2. The pluggability canopy needs is one thing: run a named agent
   non-interactively in a cwd and read stdout. `opencode run --agent` is
   sufficient. Pi's richer extension API is for changing the agent from the
   inside; canopy orchestrates from the outside and does not need it.
3. The team already uses OpenCode skills and MCP servers. Pi is another
   runtime to install (Node 22+).
4. Per-agent tool permissions give a second layer of guardrails for the
   overseer (read-only) and worker (worktree-scoped) without writing code.
Consequences: `overseer_cmd` and `worker_cmd` are OpenCode invocations by
default. Because they are command templates, a Pi worker is a config change.
Caveat to verify in M1: that agent permission denies hold under `opencode run`
(a past report suggested denies were ignored via the SDK). Config permissions
remain defense in depth, not the boundary.
Revisit: if we want the loop inside the agent process (extension hooks on
turn end, structured-output termination). That is firstmate's shape, and it
was rejected in favor of outside orchestration.

## D007. Python with uv, not Go

Context: Go would match treehouse's single-binary distribution. Python with
`uv tool install` gives an isolated install, faster iteration, stdlib
`sqlite3` and `tomllib`, and matches team tooling.
Decision: Python 3.12+, uv, ruff, ty, pytest. Stdlib first.
Revisit: if installation friction on coworker machines shows up in M5.

## D008. Policy in prompts, guards in code

Decision: what to do about a ticket lives in `prompts/overseer.md`. What the
loop may never do lives in `dispatch.py` guards and agent permissions.
Consequences: a new capability is a tool plus a paragraph. Guards are
non-negotiable from the prompt side. `decisions` table is the prompt eval
corpus.
Revisit: if prompt behavior proves too unstable, move specific phase rules
into code one at a time, recording each move here.

## D009. Runtime abstraction is a command template

Decision: no adapter interface. `runtime.overseer_cmd` and
`runtime.worker_cmd` are shell templates with `{prompt}`.
Revisit: when a second runtime needs different result parsing or invocation
shape. Then, and only then, introduce the smallest interface that covers both.

## D010. Operator identity for the MVP

Decision: all actions run as the operator. Agent work is distinguishable by
branch prefix, PR label, and commit trailer. No bot account.
Consequences: zero org approval needed; audit relies on the local journal plus
the markers above.
Revisit: when audit or compliance requires a distinct identity.

## D011. `ty` for type checking

Context: `ty` and `pyrefly` were both candidates; `ty` pairs with `uv` and
`ruff` from the same vendor.
Decision: `ty`.
Revisit: if `ty` blocks on a needed feature; swapping checkers is a Makefile
change.

## D012. Milestone status lives in ROADMAP.md

Context: there was nowhere to record that a milestone was finished, or what
building it taught us, so the next agent started without that context.
Decision: each milestone in `ROADMAP.md` ends with a `Status:` line. When the
milestone is done it gets a date, a `Learned` note, and a `Next` note. No
separate status file.
Consequences: the file agents already read in order also carries the
outcomes. `ROADMAP.md` stays editable, unlike this file.
Revisit: if status notes grow long enough to crowd out the plan.

## D013. Tracker-agnostic: MCP plus a contract, with optional provider skills

Context: D003 put tracker access behind the runtime's MCP servers, but config
(`jql`), prompts ("Tracker MCP (Atlassian)"), and docs still assumed Jira. The
goal is that any tracker with an MCP server works: Jira, GitHub Issues,
Linear, others.
Decision: the harness stays tracker-blind. Config names a free-form
`tracker.provider` and a `tracker.query` in the tracker's own syntax (or plain
language). DESIGN §17 states a provider-neutral contract of capabilities the
loop needs. Per-provider knowledge goes in optional skills
(`tracker-<provider>`), shipped for `jira` and `github`, loaded by the agents
when present. No adapter interface, consistent with AGENTS.md.
Consequences: a new tracker is config plus, if agents misread it, a skill. The
label, not the query, authorizes work, so a vague query cannot widen scope.
Keys are validated by a regex guard in the CLI, since they end up in branch
names, paths, and shell arguments. Skill loading depends on the runtime.
Revisit: if the `decisions` table shows agents ignoring skills, have the
harness inline the skill body into the rendered prompt instead. If a tracker
needs code to be usable, record why here before writing it.
