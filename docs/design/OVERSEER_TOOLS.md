# The overseer's tools

Part of the canopy design, normative like all of it: the MCP tools canopy serves the overseer, in place of the CLI it
runs through bash. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Garbage collection](GARBAGE_COLLECTION.md). Next: [Agent memory](MEMORY.md).

## 27. The overseer's tools

The overseer acts through MCP tools canopy serves, not by running `canopy` in a shell: it has no shell but the
commands the operator names in `runtime.allow_bash` (§13), never canopy's own. Its verbs are tools alone: the CLI has
no command for them.

### Why

- A call is typed. A refusal comes back as a tool error naming the field, which the model reads and corrects, where a
  click usage error is text it has to parse.
- The overseer's only write path is not a shell. Its guards are code either way (D020), but in a shell which command
  runs is decided by quoting. A tool call's arguments are JSON fields, with nothing to quote, expand, or end early.
- Each verb is its own tool name, so spend by tool (§11) splits the overseer's calls by verb.

Workers are out of scope: what they report is read from their final line after they exit (§8). A worker's, planner's,
or reviewer's one tool of canopy's own, `status` (§41), writes nothing: the harness records its update from the call in
the events the agent prints, so nothing a worker writes reaches the journal but what canopy observes it print.

### The server

`canopy _mcp`, hidden like `_run`, speaks MCP over stdio, started by the runtime as a child of the overseer's process
and living as long as that run. It opens no socket, so it is not a listener (TRUST_MODEL T8) and not a daemon (§3):
nothing outside the overseer's process tree can reach it. It serves tools and nothing else. Rejected: the `mcp` SDK, a
runtime dependency with its own async stack and HTTP transports, for the few methods canopy can speak itself.

- Each call is one verb, one call at a time, and checks that `CANOPY_TICK_ID` names a running tick (D020). With
  `CANOPY_RUN_ID` set, the server lists no tools and refuses every call, as the operator's commands refuse inside a run
  (§22).
- A guard's refusal or an invalid input is a tool error whose text names the field or the guard, which the model
  reads and goes on. It never logs an argument's free text, which may echo a tracker's or a reviewer's.
- It writes nothing to stderr, which OpenCode never reads, so output there cannot block it mid-call.
- A run a tool asks for is recorded, and the tick starts it once the overseer's run has ended (§40), so none is the
  server's descendant, which OpenCode kills when that run ends.

A chore trials it first (ROADMAP M48, stage 1b). `canopy _mcp --chore`, a server named `canopy_chore` in a chore run's
inline config, serves that run one tool, `history`, which the chore sees as `canopy_chore_history`: its own chore's
history (§19), the request and text `canopy chore history` has, refused for any other chore. Beside it, `canopy _mcp
--reports`, named `canopy_reports`, serves canopy's read-only reports, `health`, `spend`, `memory-lessons`,
`memory-proposals`, `memory-list`, `config-show`, `agents`, `decisions`, `show-run`, and `show-chore`, each the request
and text its command prints, with `--json` where it has one; there is no page of a ticket, which holds its conversation.
It is named for what it serves, not for whom: a chore's run is the one given it today, and its tools refuse in any
other. Neither lists anything where `CANOPY_RUN_ID` names no chore's run, or serves the overseer's tools. `canopy-chore`
denies bash and `canopy_*`, then allows `history` by exact name; an agent of the operator's allows each report it reads
by name after the same deny; every other definition denies both. Each run canopy starts drops the variables that
name a server, so none passes below the run it was given to.

The reviewer, which has no shell, and the planner, whose shell runs only what `runtime.allow_bash` names, never git,
read git so too. `canopy _mcp --git NAME=PATH`, named `canopy_git` in a review's or a plan's inline config, serves
`merge-base`, `diff`, `log`, `show`, `blame`, `grep`, and `files` over the checkouts the harness names on its command
line for that run, never the agent. An argument is a revision, a path inside the repository, or text to search for
joined to its option or after `-e`, never an option itself; git reads commits only, inherits no `GIT_*` variable, and
runs no hook, filesystem monitor, external diff, textconv, pager, signature check, submodule, or transport; output is
bounded. `log`, `grep`, `files`, and `blame` answer with records, each field apart, as structured content and as JSON
in its text, so no message, path, or line in a PR can pass for another record; the rest answer with git's text. Their
definitions deny bash, the planner's but for what `runtime.allow_bash` names (§13), deny `canopy_*`, and then allow
each by exact name; every other definition denies them. Workers keep their shell, for git's writes.

### The tools

One tool per overseer verb, its words joined by hyphens: `dispatch`, `decide`, `attention`,
`ticket-set`, `review-run`, `review-wait`, `review-end`, `review-revise`, `chore-run`, and `chore-wait`. The overseer
sees them as `canopy_dispatch` and so on.
No tool name holds an underscore: OpenCode joins server and tool with one, so `canopy_ticket_set` could also come from
a server named `canopy_ticket`, and the later would replace the earlier. No tool reads the pool or the observations:
the state block already holds them, and a claim on them, such as a dispatch's label or a cursor, is a field its tool
checks (§7).

Each input refuses an unknown field and is the tool's schema, and holds the bounds §6 lists. A tool's result is text
the model reads, and what it did as structured content, such as the id of a run it started, held to the output schema
it is listed with. A refusal carries the text alone.

### How the overseer gets them

- The runtime is given one entry, a local server named `canopy` running canopy's own interpreter, in the overseer
  process's inline config only, not in the shared definitions every run loads (§13). It merges after the workspace's
  config, so canopy's command replaces any the workspace sets.
- A spawn passes its environment on (D015), so the harness removes the entry from every run it starts; the refusal
  under `CANOPY_RUN_ID` and the denies below are defense in depth.
- The overseer's definition denies `canopy_*`, then allows each tool by exact name: an allow by pattern would also
  match another server whose name starts `canopy_`, a chore's or the git tools' among them. Its bash rules deny every
  command but those `runtime.allow_bash` names. Every other definition denies `canopy_*`, and a chore's then allows
  its own tools by name, the reviewer's and the planner's their git tools, and theirs and the workers' `status` (§41),
  last, since the last matching rule wins (D021).
- The shadowing check (§13) refuses a workspace config that names an MCP server `canopy` (TRUST_MODEL T7): merging keeps
  keys canopy's entry leaves out, so the workspace could set the environment of canopy's own interpreter. It can still
  add servers under other names, and plugins.
- The entry runs canopy's interpreter with the workspace root off its import path, so no file the workspace holds can
  stand in for canopy's modules (TRUST_MODEL T7).
- Each request the runtime makes of the server, a tool call included, may take as long as the overseer's run may: a
  dispatch can wait on the dispatch lock and a pool's lease, and the server answers one call at a time, so a call the
  runtime gave up on would still hold up the calls after it.
- Code mode offers no MCP tool by name: the harness turns OpenCode 1's off in the overseer's environment, and the
  server's entry takes it out of OpenCode 2's (`codemode: false`), which offers tools only through `execute`, which
  every agent is denied (D077).
- §6 step 5 checks that the server, started as the runtime starts it, answers `initialize`; on failure the tick closes
  `canopy_unavailable`. A run that never had the tools records nothing, and the duties check (§6) fails it.

### What OpenCode does

Read from OpenCode 1.19.3's source (2026-10-16), and from its build again (2026-10-20). The design above rests on
these:

- Inline config merges after the workspace's and before only what the operator or their organization manages, and a
  merge replaces anything but a plain object, keeping keys canopy's entry leaves out.
- A local server inherits OpenCode's whole environment, inline config included; its stderr is piped and never read.
- A tool is `<server>_<tool>`, every character outside `[A-Za-z0-9_-]` made `_`.
- The model reads a tool result's text alone: OpenCode 1 never reads its structured content, and OpenCode 2 hands it
  only to code mode.
- When the run ends, OpenCode signals every descendant of each local server, whatever its session or process group.
- A local server's `timeout` bounds each request to it, connecting and calling a tool alike; without one, a tool call
  waits a minute. OpenCode 2's (2.1.4) is `timeout.execution` for a tool call, twelve hours without it.
- Code mode, on with `OPENCODE_EXPERIMENTAL_CODE_MODE`, or with `OPENCODE_EXPERIMENTAL` when that is unset, offers no
  MCP tool; the first set to false turns it off whatever the second says. OpenCode 2 (2.1.4, 2026-10-23) has no such
  variable: a server's own `codemode: false` takes it out of code mode. It sends a session's first model call no MCP
  tool until the server's tools are registered, which canopy's plugin waits for (§33).

D124 holds that canopy serves MCP itself, over stdio only.

### Open

- Structured results: JSON as a tool's text, in place of the prose it returns, which is all OpenCode 1's model reads.
- A validate-only `check_result` tool for workers, once workers are measured losing runs to results that do not parse.
