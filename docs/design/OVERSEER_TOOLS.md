# The overseer's tools

Part of the canopy design, normative like all of it: the MCP tools canopy serves the overseer, in place of the CLI it
runs through bash. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Garbage collection](GARBAGE_COLLECTION.md). Next: [Agent memory](MEMORY.md).

## 27. The overseer's tools (M48)

Designed, not built (ROADMAP M48). Until its second stage lands, the overseer runs the `canopy` CLI through bash, and
§6, §13, §22, and TRUST_MODEL T1 describe canopy as it is. This section says what changes.

The overseer acts through MCP tools canopy serves, not by running `canopy` commands in a shell. The CLI's overseer
verbs stay while the tools settle, and go once nothing needs them (stage 3).

### Why

- A call is typed. Each tool's input schema says what it takes, and a refusal comes back as a tool error naming the
  field, which the model reads and corrects, where a click usage error is text it has to parse.
- The overseer's only write path stops being a shell. Its guards are code either way (D020), but today which command
  runs is decided by quoting, and a comment's body reaches `canopy mirror` through a heredoc whose delimiter must be
  random per tick so no comment can end it (D081). A tool call's arguments are JSON fields, with nothing to quote,
  expand, or end early. M37 retires mirroring anyway; this removes the heredoc sooner, and the shell with it.
- Each verb is its own tool name, so spend by tool (§11) splits the overseer's calls by verb rather than counting them
  all as `bash`.

How much the first two buy is measured before anything is built (stage 0): how often the overseer's bash calls fail
today on usage or quoting.

Workers are out of scope. They run no `canopy` command, and their definitions deny `canopy *`; what they report is read
from their final line after they exit (§8), so nothing a worker writes reaches the journal while it runs. A tool a
worker could call mid-run would end that. A tool that only checks a draft result against the contract and writes
nothing would not, and is a possible later step, not part of M48.

### The server

`canopy _mcp`, hidden like `_run`, speaks MCP over stdio. The runtime starts it as a local server, a child of the
overseer's process, and it lives as long as that run. It opens no socket, so it is not a listener (TRUST_MODEL T8) and
not a daemon (§3): nothing outside the overseer's process tree can reach it.

It implements `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`, and nothing else:
no resources, prompts, sampling, or HTTP transport. Rejected: the `mcp` SDK, a runtime dependency with its own async
stack and HTTP transports, for five methods canopy can speak itself (stdlib first). It answers `initialize` with the
protocol version the client asked for when it knows that version, and otherwise with its newest. It knows
`2025-11-25` and `2025-06-18`, both of which OpenCode's client accepts (below).

Each call opens the Context as a CLI command does, runs the verb, and closes it, so a call sees and writes exactly
what the same CLI call would. Calls are handled one at a time, in the order they arrive.

- The tick is `CANOPY_TICK_ID`, inherited from the overseer. Every call checks that it names a running tick, as the
  CLI's verbs do today (D020).
- With `CANOPY_RUN_ID` set, a worker's or a chore's environment, it lists no tools and refuses every call, as the
  operator's commands refuse inside a run (§22).
- A guard's refusal or an invalid input is a tool error with the text the CLI prints for it today, which the model
  reads and goes on, as after a `deny`. A protocol error is only for a malformed request or an unknown tool. An
  exception in a verb is a tool error naming it, logged with the tick id, and the server keeps serving.
- It logs as the CLI's verbs do, plus one line per call naming the tool and its outcome. It never logs an argument's
  text: a mirrored comment's body is the tracker's, not the log's.
- It writes nothing to stderr, and discards its own stderr before it serves, so a warning or a traceback cannot reach
  it either: OpenCode pipes a local server's stderr and never reads it (below), so enough output there blocks the
  server mid-call.
- It exits when its stdin closes, which is how OpenCode stops it.
- A run a tool starts (`_run`, `_chore`, `_review`) is never the server's descendant. OpenCode kills every descendant
  of a local server when the overseer's run ends (below), so a worker spawned as the server's child would die with the
  tick that dispatched it. A spawn from the server goes through an intermediate process that starts the run and exits
  at once, so the run is reparented before the overseer ends, as a `canopy dispatch` run is today.

### The tools

OpenCode names an MCP tool `<server>_<tool>`, each part with every character outside `[A-Za-z0-9_-]` replaced by `_`,
so the server is `canopy` and the overseer sees `canopy_dispatch` and the rest. No tool name holds an underscore: a
tool `ticket_set` would be `canopy_ticket_set`, which a server named `canopy_ticket` with a tool `set` also produces,
and the later one replaces the earlier. With one underscore in each full name, only a server named `canopy` can
produce it, and that one the shadowing check refuses (below).

| Tool | Today | Input |
| --- | --- | --- |
| `dispatch` | `canopy dispatch` | its arguments and options as fields, `repos` a list |
| `decide` | `canopy decide` | `key` (omitted only for a tick-wide `skip`, whose `rationale` gives its reason), `action`, `rationale` |
| `queried` | `canopy queried` | `keys`, a list, empty for none |
| `attention` | `canopy attention` | its arguments and options as fields |
| `ticket-set` | `canopy ticket set` | its arguments and options as fields |
| `mirror` | `canopy mirror` | `ref`, `comment`, `author`, `at`, and `body`, a field: no heredoc, no delimiter |
| `review-run`, `review-wait`, `review-end` | `canopy review run`, `wait`, `end` | their options as fields |
| `chore-run`, `chore-wait` | `canopy chore run`, `wait` | their arguments and options as fields |

No tool reads the pool: the state block's leased slots already say what `treehouse status` would, and the definition's
`treehouse status*` allow goes with bash in stage 2.

Each input refuses an unknown field, and its schema is the tool's input schema. The bounds §6 lists move from the
CLI's parameter types into those inputs, and the commands validate through the same inputs, so a tool and its command
cannot drift apart. A rule across fields, such as `decide` without a `key` for any action but `skip`, is refused by
the tool as by the command. A tool's result is the text its command prints today; stage 3 may make it structured.

### Where the code goes

In `loop/`, which already owns the overseer's side of the tick and drives the features the verbs call: each verb as a
function over its input, which the click commands wrap, and the stdio protocol beside it. No new package or layer.

### How the overseer gets them

The runtime needs one config entry, a local server named `canopy` whose command is canopy's own interpreter running
`-m canopy _mcp`, as dispatch starts `_run` (§8). It needs no `canopy` on `PATH`.

- The entry is in the overseer process's environment, as OpenCode's inline config, `OPENCODE_CONFIG_CONTENT`, not in
  the shared definitions snapshot every run loads (§13). It merges after the workspace's own config, so canopy's
  `command` replaces any the workspace sets. It sets the command, the workspace root as cwd, and enabled, and no
  environment of its own.
- The server inherits that environment, and a spawn passes its whole environment on (D015), so every worker, chore,
  and review a tool starts would inherit the entry and start a `canopy` server of its own. The harness removes the
  variable from every run it starts. The `CANOPY_RUN_ID` refusal and the denies below are
  defense in depth, not the protection.
- The overseer's definition allows each tool by its exact name, never `canopy_*`: a server another config names
  `canopy_x` would have tools that wildcard matches. Its `bash` is denied. Every other definition denies `canopy_*`,
  where a wildcard is the safe direction. Allowing by name is needed in any case: a tool no rule matches is `ask`,
  which `opencode run` rejects (D021).
- The shadowing check (§13) also refuses a workspace whose OpenCode config names an MCP server `canopy`, as it refuses
  one that defines a canopy agent (TRUST_MODEL T7). Merging replaces only the keys canopy's entry sets, so without the
  check a workspace's environment for that server would survive into canopy's entry and could set `PYTHONPATH` for
  canopy's own interpreter. The rest of T7's residual stands: the workspace can still add servers under other names,
  and plugins, which already run code in the agent process.
- The harness also removes OpenCode's experimental code-mode flags from the overseer's environment: code mode does
  not offer MCP tools as tools.
- Before the overseer runs, §6 step 5's check of `canopy` becomes a check of the server: start it, send
  `initialize`, and on failure close the tick `canopy_unavailable`, as today. It does not prove OpenCode loaded the
  entry; a run that never had the tools records nothing, and the duties check (§6) fails it `overseer_failed`. No
  migration.

### What OpenCode does

From OpenCode's source at 1.19.3 (2026-10-16), and the MCP SDK it pins, `@modelcontextprotocol/sdk` 1.29.0 with
OpenCode's patch. The design above rests on each of these; a later OpenCode is read again before stage 2.

- **Config order.** `packages/opencode/src/config/config.ts` merges, each over the one before: a remote well-known
  config, the global files under `~/.config/opencode`, `OPENCODE_CONFIG`, the project's `opencode.json` and
  `opencode.jsonc` files, each `.opencode` directory and `OPENCODE_CONFIG_DIR`, then `OPENCODE_CONFIG_CONTENT`, then
  an account organization's config, the managed config directory, macOS managed preferences, and
  `OPENCODE_PERMISSION`. Inline config therefore comes after the workspace's config and before only what the operator
  or their organization manages.
- **Merging.** remeda's `mergeDeep`: a plain object is merged key by key, and anything else, an array included, is
  replaced. So canopy's `command` replaces a workspace's, and a key canopy's entry leaves out keeps the workspace's
  value.
- **A local server's environment.** `packages/opencode/src/mcp/index.ts` starts it with OpenCode's whole environment,
  then the entry's `environment` over it, in the entry's `cwd` resolved against the run's directory, or that directory
  itself. So the server inherits `OPENCODE_CONFIG_CONTENT`, and so would every process it starts.
- **stderr.** The transport is made with `stderr: "pipe"`, and nothing reads the pipe.
- **A server that fails to start.** Its status becomes `failed`, OpenCode logs `server unavailable`, and the run goes on
  without its tools. The connection's timeout is the entry's `timeout`, 30 seconds by default.
- **Protocol.** The client sends `initialize` with `2025-11-25` and refuses a server that answers with a version
  outside `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`, and `2024-10-07`, then sends
  `notifications/initialized`. It lists tools only when the server's capabilities name `tools`. A call's timeout is
  the entry's `timeout`, else `experimental.mcp_timeout`, else the SDK's 60 seconds.
- **Tool names and permission.** `packages/opencode/src/mcp/catalog.ts` names a tool `sanitize(server) + "_" +
  sanitize(tool)`, `sanitize` replacing each character outside `[A-Za-z0-9_-]` with `_`. Each call asks the permission
  named for the tool with pattern `*`; a permission no rule matches is `ask`.
- **A tool error.** A result with `isError` becomes an error whose message is the result's text, which the model
  reads as the tool's failure.
- **Stopping.** When the run ends, OpenCode finds every descendant of each local server's pid by `pgrep -P`,
  recursively, and sends each SIGTERM, whatever its session or process group. It then closes the server's stdin,
  waits two seconds, sends SIGTERM, waits two more, and sends SIGKILL.
- **Code mode.** With `OPENCODE_EXPERIMENTAL_CODE_MODE` set, or `OPENCODE_EXPERIMENTAL` and that one not set false,
  `packages/opencode/src/session/tools.ts` returns before it adds MCP tools, which code mode offers in its own way.

### What changes elsewhere, in stage 2

The overseer's prompt names tools, not commands; its definition as above; the state
block drops the heredoc delimiter; §6's overseer step, preflight, and dry-run wording; §13's `canopy-overseer`; §22's
mirroring; TRUST_MODEL T1 (the overseer acts only through canopy's tools, whose guards are code; the heredoc paragraph
goes) and T7 (the server's name); D020 edited to name the tools, D081 superseded, and a new entry: canopy serves MCP
itself, over stdio only, to the overseer only.

M37 retires mirroring once the tracker connector writes comments, and with it the `mirror` tool. M39's overseer has
canopy's tools and nothing else.

### Open

- Structured results: JSON a tool returns instead of the CLI's text. Recommended in stage 3, when no command prints
  the same thing.
- A validate-only `check_result` for workers (above). Not before a measurement shows workers losing runs to results
  that do not parse.
