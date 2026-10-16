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

`canopy _mcp`, hidden like `_run`, speaks MCP over stdio: newline-delimited JSON-RPC 2.0 on its stdin and stdout. The
runtime starts it as a local server, a child of the overseer's process, and it lives as long as that run. It opens no
socket, so it is not a listener (TRUST_MODEL T8) and not a daemon (§3): nothing outside the overseer's process tree
can reach it.

It implements `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`, and nothing else: no
resources, prompts, sampling, or HTTP transport. That is a few hundred lines over `json` and pydantic. Rejected: the
`mcp` SDK, a runtime dependency with its own async stack and HTTP transports, for five methods canopy can speak itself
(stdlib first). It answers `initialize` with the protocol version the client asked for when the server knows it, and
otherwise with its newest; which versions OpenCode's client asks for is read from its source in stage 0.

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

No tool reads the pool: the state block's `repositories[].leased_slots` already says what `treehouse status` would,
and the prompt tells the overseer not to run `treehouse`. The definition's `treehouse status*` allow is a leftover,
and goes with bash in stage 2.

Each input is a pydantic model with `extra="forbid"`, and its JSON schema is the tool's `inputSchema`. The bounds §6
lists (keys and attention reasons validated, phases from §7's table, cursor ids, text cut at 2000 characters) move
from click parameter types into those models, below `cli/`, and the click commands validate through the same models,
so a tool and its command cannot drift apart. A rule across fields, which a JSON schema cannot state, is a model
validator, so the tool refuses it as the command does: `decide` without a `key` for any action but `skip`, and each
such check the commands make by hand today. A tool's result is the text its command prints today; stage 3 may make
it structured, once no command shares it.

### Where the code goes

In `loop/`, which already owns the overseer's side of the tick (`state.py`, `duties.py`, `attention.py`) and already
drives the features the verbs call:

- `loop/tools.py`: each overseer verb as a function over its request model, holding the body that is in its `cmd_*`
  function today. Most are validation and one journal write, so little moves.
- `loop/mcp.py`: the stdio protocol and the tool table.

The click commands in `cli/` become wrappers that build the request, call the verb, and print its text, and `cli/`
gains the hidden `_mcp`. No new package, layer, or §5 line beyond the two modules.

### How the overseer gets them

The runtime needs one config entry, a local server named `canopy` whose command is canopy's own interpreter running
`-m canopy _mcp`, as dispatch starts `_run` (§8). It needs no `canopy` on `PATH`.

- The entry is in the overseer process's environment, as OpenCode's inline config, set by the harness as it sets
  `CANOPY_TICK_ID`, not in the shared definitions snapshot every run loads (§13). Stage 0 reads from OpenCode's source
  how inline config merges with the operator's and the workspace's, whether it reaches OpenCode's children, and what
  a run does when a local server fails to start; if it does not behave as assumed, this part is redesigned first.
- The server inherits that environment, and `procs.spawn` passes the spawner's whole environment on (D015), so every
  worker, chore, and review a tool starts would inherit the entry and start a `canopy` server of its own. The harness
  removes the variable from every run it starts: `procs`' `env` can only add or override today, so the seam gains a
  way to remove one, tested in stage 1. The `CANOPY_RUN_ID` refusal and the denies below are then defense in depth,
  not the protection.
- The overseer's definition allows each tool by its exact name, `canopy_dispatch: allow` and so on, never
  `canopy_*`: a server another config names `canopy_x` would have tools that wildcard matches. Its `bash` is denied.
  Every other definition denies `canopy_*`, where a wildcard is the safe direction.
- `definitions.shadowing` also refuses a workspace whose OpenCode config names an MCP server `canopy`, as it refuses
  one that defines a canopy agent (TRUST_MODEL T7). The rest of T7's residual stands: the workspace can still add
  servers of its own, under other names.
- Before the overseer runs, the check §6 step 5 makes of `canopy` becomes a check of the server: start `-m canopy
  _mcp`, send `initialize`, and on failure close the tick `canopy_unavailable`, as today. It does not prove OpenCode
  loaded the entry; a run that never had the tools records nothing, and the duties check (§6) fails it
  `overseer_failed`. No migration.

### What changes elsewhere, in stage 2

With the operator's approval note: the overseer's prompt names tools, not commands; its definition as above; the state
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
