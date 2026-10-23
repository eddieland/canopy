# The overseer's tools

Part of the canopy design, normative like all of it: the MCP tools canopy serves the overseer, in place of the CLI it
runs through bash. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Garbage collection](GARBAGE_COLLECTION.md). Next: [Agent memory](MEMORY.md).

## 27. The overseer's tools

The server and its tools are built; nothing gives them to the overseer yet (ROADMAP M48). Until its second stage
lands, the overseer runs the `canopy` CLI through bash, and §6, §13, §22, and TRUST_MODEL T1 describe canopy as it is.
This section says what changes: the overseer acts through MCP tools canopy serves, not by running `canopy` in a shell.
The CLI's overseer verbs stay until nothing needs them.

### Why

- A call is typed. A refusal comes back as a tool error naming the field, which the model reads and corrects, where a
  click usage error is text it has to parse.
- The overseer's only write path stops being a shell. Its guards are code either way (D020), but today which command
  runs is decided by quoting, and a comment's body reaches `canopy mirror` through a heredoc whose delimiter must be
  random per tick (D081). A tool call's arguments are JSON fields, with nothing to quote, expand, or end early.
- Each verb is its own tool name, so spend by tool (§11) splits the overseer's calls by verb.

How much the first two buy is measured before anything is built. Workers are out of scope: what they report is read
from their final line after they exit (§8), so nothing a worker writes reaches the journal while it runs, and a tool a
worker could call mid-run would end that.

### The server

`canopy _mcp`, hidden like `_run`, speaks MCP over stdio, started by the runtime as a child of the overseer's process
and living as long as that run. It opens no socket, so it is not a listener (TRUST_MODEL T8) and not a daemon (§3):
nothing outside the overseer's process tree can reach it. It serves tools and nothing else. Rejected: the `mcp` SDK, a
runtime dependency with its own async stack and HTTP transports, for the few methods canopy can speak itself.

- Each call sees and writes exactly what the same CLI call would, one call at a time, and checks that
  `CANOPY_TICK_ID` names a running tick (D020). With `CANOPY_RUN_ID` set, the server lists no tools and refuses every
  call, as the operator's commands refuse inside a run (§22).
- A guard's refusal or an invalid input is a tool error with the text the CLI prints, which the model reads and goes
  on. It never logs an argument's text: a mirrored comment's body is the tracker's, not the log's.
- It writes nothing to stderr, which OpenCode never reads, so output there cannot block it mid-call.
- A run a tool starts is never the server's descendant, since OpenCode kills those when the overseer's run ends; it is
  reparented, as a `canopy dispatch` run is today.

A chore trials it first (ROADMAP M48, stage 1b). `canopy _mcp --chore`, a server named `canopy_chore` in a chore run's
inline config, serves that run one tool, `history`, which the chore sees as `canopy_chore_history`: its own chore's
history (§19), the request and text `canopy chore history` has, refused for any other chore. Beside it, `canopy _mcp
--reports`, named `canopy_reports`, serves canopy's read-only reports, `health`, `spend`, `memory-lessons`,
`memory-proposals`, and `memory-list`, each the request and JSON its command prints with `--json`. It is named for what
it serves, not for whom: a chore's run is the one given it today, and its tools refuse in any other. Neither lists
anything where `CANOPY_RUN_ID` names no chore's run, or serves the overseer's tools. `canopy-chore` allows `history` by
exact name, denies the reports and bash; an agent of the operator's allows each report it reads by name; every other
definition denies both. Each run canopy starts drops the variables that name a server, so none passes below the run it
was given to.

The reviewer, which has no shell, and the planner, whose shell runs only what `runtime.allow_bash` names, never git,
read git so too. `canopy _mcp --git NAME=PATH`, named `canopy_git` in a review's or a plan's inline config, serves
`merge-base`, `diff`, `log`, `show`, and `blame` over the checkouts the harness names on its command line for that run,
never the agent. An argument is a revision, a path inside the repository, or text to search for joined to its option,
never an option itself; git reads commits only, inherits no `GIT_*` variable, and runs no hook, filesystem monitor,
external diff, textconv, pager, signature check, or transport; output is bounded. Their definitions deny bash, the
planner's but for what `runtime.allow_bash` names (§13), and allow each by exact name; every other definition denies
`canopy_git_*`. Workers keep their shell, for git's writes.

### The tools

One tool per overseer verb, named for its command with hyphens for spaces: `dispatch`, `decide`, `queried`,
`attention`, `ticket-set`, `mirror` (its body a field: no heredoc, no delimiter), `review-run`, `review-wait`,
`review-end`, `chore-run`, and `chore-wait`. The overseer sees them as `canopy_dispatch` and so on. No tool name holds an
underscore: OpenCode joins server and tool with one, so `canopy_ticket_set` could also come from a server named
`canopy_ticket`, and the later would replace the earlier. No tool reads the pool: the state block already does.

Each input refuses an unknown field and is the tool's schema. The bounds §6 lists move into those inputs, and the
commands validate through the same inputs, so a tool and its command cannot drift apart. A tool's result is the text its
command prints.

### How the overseer gets them

- The runtime is given one entry, a local server named `canopy` running canopy's own interpreter, in the overseer
  process's inline config only, not in the shared definitions every run loads (§13). It merges after the workspace's
  config, so canopy's command replaces any the workspace sets.
- A spawn passes its environment on (D015), so the harness removes the entry from every run it starts; the refusal
  under `CANOPY_RUN_ID` and the denies below are defense in depth.
- The overseer's definition allows each tool by exact name, never `canopy_*`, which would match another server named
  `canopy_x`, and denies `bash`. Every other definition denies `canopy_*`. A tool no rule matches is `ask`, which
  `opencode run` rejects (D021).
- The shadowing check (§13) refuses a workspace config that names an MCP server `canopy` (TRUST_MODEL T7): merging keeps
  keys canopy's entry leaves out, so the workspace could set the environment of canopy's own interpreter. It can still
  add servers under other names, and plugins.
- The harness removes OpenCode's code-mode flags from the overseer's environment: code mode offers no MCP tools.
- §6 step 5's check of `canopy` becomes a check that the server answers `initialize`; on failure the tick closes
  `canopy_unavailable`. A run that never had the tools records nothing, and the duties check (§6) fails it.

### What OpenCode does

Read from OpenCode 1.19.3's source (2026-10-16), and read again before stage 2. The design above rests on these:

- Inline config merges after the workspace's and before only what the operator or their organization manages, and a
  merge replaces anything but a plain object, keeping keys canopy's entry leaves out.
- A local server inherits OpenCode's whole environment, inline config included; its stderr is piped and never read.
- A tool is `<server>_<tool>`, every character outside `[A-Za-z0-9_-]` made `_`.
- When the run ends, OpenCode signals every descendant of each local server, whatever its session or process group.

### What changes elsewhere, in stage 2

The overseer's prompt and definition, §6, §13, §22, TRUST_MODEL T1 and T7, and D020 and D081. D124 already holds that
canopy serves MCP itself, over stdio only. §35 retires mirroring, and with it the `mirror` tool.

### Open

- Structured results: JSON a tool returns instead of the CLI's text, once no command prints the same thing.
- A validate-only `check_result` tool for workers, once workers are measured losing runs to results that do not parse.
- How long OpenCode waits on one `tools/call` to a local server, and on `tools/list` as it connects, to be read from
  its source before stage 2: `dispatch` can wait on the dispatch lock and a pool's lease, and the server answers one
  call at a time, so calls the overseer makes in parallel queue behind it.
