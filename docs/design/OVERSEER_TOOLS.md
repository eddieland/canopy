# The overseer's tools

Part of the canopy design, normative like all of it: the MCP tools canopy serves the overseer, in place of the CLI it
runs through bash. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Garbage collection](GARBAGE_COLLECTION.md).

## 27. The overseer's tools (M48)

Designed, not built (ROADMAP M48). Until its second stage lands, the overseer runs the `canopy` CLI through bash, and
§6, §13, §22, and TRUST_MODEL T1 describe canopy as it is. This section says what changes.

Asked for by the operator (2026-10-16): the overseer acts through MCP tools canopy serves, not by running `canopy`
commands in a shell. The CLI's overseer verbs stay while the tools settle, and go once nothing needs them (stage 3).

### Why

- The overseer's only write path is a shell. Its guards are code (D020), but which command runs is decided by quoting:
  `canopy *` matches whatever follows, a comment's body reaches `canopy mirror` through a heredoc whose delimiter must
  be random per tick so no comment can end it (D081), and an `ask`, such as a `cd` out of the workspace, ends the run
  and loses every decision not yet recorded (§13, D021). A tool call has no shell under it: its arguments are JSON
  fields, so there is nothing to quote, expand, or end early.
- A call is typed. Each tool's input schema says what it takes, and a refusal comes back as a tool error naming the
  field, which the model reads and corrects, where a click usage error is text it has to parse.
- Each verb is its own tool name, so spend by tool (§11) splits the overseer's calls by verb rather than counting them
  all as `bash`.
- MCP config is what any runtime the operator might swap in reads. Bash permission patterns are OpenCode's own syntax.

Workers are out of scope. They run no `canopy` command, and their definitions deny `canopy *`; what they report is read
from their final line after they exit (§8), so nothing a worker writes reaches the journal while it runs. A tool a
worker could call mid-run would end that. A tool that only checks a draft result against the contract and writes
nothing would not, and is a possible later step, not part of M48.

### The server

`canopy _mcp`, hidden like `_run`, speaks MCP over stdio: newline-delimited JSON-RPC 2.0 on its stdin and stdout. The
runtime starts it as a local server, a child of the overseer's process, and it lives as long as that run. It opens no
socket, so it is not a listener (TRUST_MODEL T8) and not a daemon (§3): nothing outside the overseer's process tree
can reach it.

It implements `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`, and nothing else: no
resources, prompts, sampling, or HTTP transport. That is a few hundred lines over `json` and pydantic. Rejected: the
`mcp` SDK, a runtime dependency with its own async stack and HTTP transports, for five methods canopy can speak itself
(stdlib first). It answers `initialize` with the protocol version the client asked for when the server knows it, and
otherwise with its newest; which versions OpenCode's client asks for is read from its source in stage 1, as §24 read
how it starts local servers.

Each `tools/call` opens the Context as a CLI command does, runs the verb, and closes it, so a call sees and writes
exactly what the same CLI call would. Calls are handled one at a time, in the order they arrive.

- The tick is `CANOPY_TICK_ID` from the server's environment, which it inherits from the overseer's. Every call checks
  that it names a running tick, as the CLI's verbs do today (D020).
- With `CANOPY_RUN_ID` set, a worker's or a chore's environment, it lists no tools and refuses every call, as the
  operator's commands refuse inside a run (§22).
- A guard's refusal or an invalid input is a tool result with `isError: true` and the text the CLI prints for it
  today. The model reads it and goes on, as it does after a `deny`. A JSON-RPC error is only for a malformed request
  or an unknown tool. An exception in a verb is a tool error naming its class, logged with the tick id, and the server
  keeps serving.
- It logs as the CLI's verbs do, JSON lines to `canopy.log` with the tick id, plus one line per call naming the tool
  and its outcome. It never logs an argument's text: a mirrored comment's body is the tracker's, not the log's.

### The tools

OpenCode names an MCP tool `<server>_<tool>`, so the server is `canopy` and the overseer sees `canopy_dispatch` and
the rest.

| Tool | Today | Input |
| --- | --- | --- |
| `dispatch` | `canopy dispatch` | its arguments and options as fields, `repos` a list |
| `decide` | `canopy decide` | `key` (optional only for a tick-wide `skip`), `action`, `rationale` |
| `queried` | `canopy queried` | `keys`, a list, empty for none |
| `attention` | `canopy attention` | its arguments and options as fields |
| `ticket_set` | `canopy ticket set` | its arguments and options as fields |
| `mirror` | `canopy mirror` | `ref`, `comment`, `author`, `at`, and `body`, a field: no heredoc, no delimiter |
| `review_run`, `review_wait`, `review_end` | `canopy review run`, `wait`, `end` | their options as fields |
| `chore_run`, `chore_wait` | `canopy chore run`, `wait` | their arguments and options as fields |
| `pool_status` | `treehouse status` | none; what the overseer reads of the pool today, through canopy's pool seam |

Each input is a pydantic model with `extra="forbid"`, and its JSON schema is the tool's `inputSchema`. The bounds §6
lists (keys and attention reasons validated, phases from §7's table, cursor ids, text cut at 2000 characters) move
from click parameter types into those models, below `cli/`, and the click commands validate through the same models,
so a tool and its command cannot drift apart. A tool's result is the text its command prints today; stage 3 may make
it structured, once no command shares it.

`pool_status` goes through the pool seam, `core/pools.py`, not `treehouse` itself, so canopy's own pools (M45) serve
it too, and the overseer's definition can then deny bash entirely.

### Where the code goes

A new package, `overseer/`, beside `loop/` and above the features, since its verbs drive `runs`, `reviews`, and
`chores`:

- `overseer/verbs.py`: each overseer verb as a function over its request model, holding the body that is in its
  `cmd_*` function today.
- `overseer/server.py`: the stdio protocol and the tool table.

The click commands in `cli/` become wrappers that build the request, call the verb, and print its text, and `cli/`
gains the hidden `_mcp`. The package gets a line in §5 and a layer in `tests/canopy/test_layers.py` when it is built.

### How the overseer gets them

The runtime needs one config entry, a local server named `canopy` whose command is canopy's own interpreter running
`-m canopy _mcp`, as dispatch starts `_run` (§8). It needs no `canopy` on `PATH`, so the launcher check in §6 step 5,
which exists for the overseer's bash calls, goes with them in stage 2.

- The entry reaches the overseer's run only. Recommended: OpenCode's inline config in the overseer process's
  environment, set by the harness as it sets `CANOPY_TICK_ID`, not the shared definitions snapshot every run loads
  (§13). Stage 1 reads from OpenCode's source how inline config merges with the operator's and the workspace's, and
  what a run does when a local server fails to start.
- The overseer's definition allows each tool by its exact name, `canopy_dispatch: allow` and so on, never
  `canopy_*`: a server another config names `canopy_x` would have tools that wildcard matches. Its `bash` is denied.
  Every other definition denies `canopy_*`, where a wildcard is the safe direction.
- `definitions.shadowing` also refuses a workspace whose OpenCode config names an MCP server `canopy`, as it refuses
  one that defines a canopy agent (TRUST_MODEL T7). The rest of T7's residual stands: the workspace can still add
  servers of its own, under other names.
- A run that never started the server would have no way to record anything, and its duties (§6) would fail with every
  ticket listed. So the server records on the tick when it answers `initialize`, and a tick whose overseer ended
  without that closes `overseer_failed` with the summary `no canopy tools`.

### What changes elsewhere, in stage 2

With the operator's approval note: the overseer's prompt names tools, not commands; its definition as above; the state
block drops the heredoc delimiter; §6's overseer step, launcher check, and dry-run wording; §13's `canopy-overseer`;
§22's mirroring; TRUST_MODEL T1 (the overseer acts only through canopy's tools, whose guards are code; the heredoc
paragraph goes) and T7 (the server's name); D020 edited to name the tools, D081 superseded, and a new entry: canopy
serves MCP itself, over stdio only, to the overseer only.

M37 retires mirroring once the tracker connector writes comments, and with it the `mirror` tool. M39's overseer has
canopy's tools and nothing else.

### Open

- Structured results: JSON a tool returns instead of the CLI's text. Recommended in stage 3, when no command prints
  the same thing.
- A validate-only `check_result` for workers (above). Not before a measurement shows workers losing runs to results
  that do not parse.
