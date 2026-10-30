# M57. A clock for running agents

DESIGN §33, TRUST_MODEL T3 and T4, issue #775. Every agent run canopy starts with a timeout gets `CANOPY_DEADLINE`,
from the clock `procs` kills it by, and canopy's one OpenCode plugin, `plugins/canopy.js`, shipped in the snapshot,
adds a `[canopy]` line with the minutes left to each tool's output in the last fifth of the timeout (at most its last
10 minutes), first in an MCP tool's `content`; the snapshot is unwritable once written, and every prompt says what a
`[canopy]` line asks. The kill stays the only guard.

Status: done 2026-10-30.
Learned: closed on the operator's own use, before Stage 0's measure pass, the 5-minute live check, and the week's count
of timed-out runs that pushed after a warning, which are SCENARIOS S61. Stage 0's source read (OpenCode 1.19.3) changed
the plan: the line goes first in an MCP result, which OpenCode truncates keeping the head; the snapshot is made
unwritable, since any plugin makes OpenCode install `@opencode-ai/plugin` in each config directory it can write; and
the plugin catches everything, since a hook that throws fails the call. A worker that winds down reports `failed`, its
summary naming what remains, with no status of its own.
Next: the same channel could carry a notice (M35) or a request to wind down to runs already going (M65); each needs a
file the harness writes and a sandboxed run reads, so each waits for real use to ask.
