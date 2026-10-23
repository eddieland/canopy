# A clock for running agents

Part of the canopy design, normative like all of it: how a running agent learns how long it has before canopy's timeout
ends it. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Feedback
plans](FEEDBACK_PLANS.md). Next: [Published reviews](PUBLISHED_REVIEWS.md).

## 33. A clock for running agents

Built, and checked against the fakes; its live check is ROADMAP M57's.

Every agent run ends at its timeout, its process group killed (§15), and what a worker has not pushed goes with its
slot. An agent is told its time limit once, in its prompt, and has no clock after that. This section gives it one: near
the end, a line from canopy on each tool call tells it the minutes left, so a worker pushes what it has and an overseer
records what it owes before the kill. The kill stays the only guard (TRUST_MODEL T3): the clock is advice, and nothing
an agent does with it extends a run.

### The deadline

Every agent run canopy starts with a timeout (the overseer, every kind of worker run, triages, reviews, and chores)
gets `CANOPY_DEADLINE`, the moment its timeout fires, in Unix seconds, as does any other process canopy starts with a
timeout. It is taken when canopy starts the clock it kills by, so the two agree. A process canopy starts without a
timeout gets none, not even one its parent had. The variable reaches a sandboxed agent unchanged (§24).

### The plugin

canopy ships one OpenCode plugin, `canopy.js`, in the snapshot, beside its definitions (§13, D040), so every run that
loads canopy's definitions loads it, and the snapshot's digest splits runs into before and after it. It is plain
JavaScript with no imports, so it loads with no network, inside the sandbox too. It holds each job canopy asks of the
agent process, the clock its first: each job reads only what the harness hands it for that job, and its hooks run in a
try of their own, so one that throws fails neither the call nor the jobs after it. A later job joins this file rather
than shipping a plugin of its own. Both of OpenCode's major versions load the one file: its default export carries an
entry point for each, and each version reads only its own, so binding OpenCode 2 (D009) keeps the clock.

After each tool call that succeeds (`tool.execute.after`, MCP tools' included), once the run is in the last fifth of
the time it had when the plugin loaded, and never more than its last 10 minutes, the plugin adds one line to the call's
result: the minutes left, and, the first time in a session, to finish what keeps the work (commit and push, or record
its decisions) and print the result line. The line goes after a built-in tool's output, and first in an MCP tool's
content, which OpenCode truncates after the hook keeping its head; so the tracker's, GitHub's, and the overseer's own
tools (§27) carry it too. OpenCode 2 truncates every tool's result after the hook, so there it goes first in all of
them. Counting from its own load, at the session's start, keeps it to one variable.

What lets it run inside every agent process (TRUST_MODEL T4):

- It reads `CANOPY_DEADLINE` and the clock, nothing else. Without the variable it adds nothing.
- It writes nothing, refuses no call, grants no tool, and keeps nothing but whether it has warned in this session.
- It catches every error, since a hook that throws fails a call that has already run.

An agent thinking without calling a tool hears nothing until its next call; its prompt's time limit covers that.

### MCP tools on the first call

Under OpenCode 2 the plugin has one job more, of 2's alone. 2 registers an MCP server's tools only once the server has
connected, as the session starts, and sends each model call the tools registered when it is made: without a wait, a
session's first call gets none of them, and the overseer, which acts only through canopy's tools (§27), has nothing to
call. So the plugin holds a session's first prompt while a server is still connecting, at most 30 seconds, then while
a connected server has no tool registered, at most 2 seconds more, since one may have none; then the prompt goes on as
it would have. It reads the servers' names and states and the tools' names, changes none of them, and catches every
error, as the clock does.

These rest on OpenCode's source at 1.19.3, read 2026-10-19 and read again on an upgrade: OpenCode loads plugins from
every config directory, the snapshot's last, so a repository's own plugins already run in the agent's process (T7);
a hook that throws fails the call; and an MCP result is truncated after the hook. OpenCode 2's, at 2.1.2, read
2026-10-22: it loads a plugin file only by a default export with an id and a `setup` that registers hooks, and
logs any other and runs without it; and the same three hold, for every tool's result.

### The snapshot, unwritable

With any plugin configured, OpenCode waits, before the session, on an npm install of its plugin package into each
config directory it loads and can write, so the first run on a new snapshot would wait on the registry
(MEASUREMENTS 2026-10-19, F50). canopy takes the snapshot's write permission away once it is written, the operator's
included, so OpenCode installs nothing there, and gives it back only to remove the snapshot (§26). A sandboxed run
could not write it already (§24); an unsandboxed one could.

A repository's `.opencode/` that the run can write is still installed into and waited for, inside the sandbox too: with
canopy's plugin, every run in such a repository pays that wait, not only one whose repository ships a plugin.

### Forged lines

A file, a PR, or a tool's result the agent reads can print a line that looks like canopy's. One can only tell the agent
to wrap up early, or that it has longer than it has, which leaves it where it is without the clock; so a forged line
fails safe, as the comment marks do (§8, D069). The prompts say a line from canopy asks for nothing but wrapping up,
so one that asks for more is data (T1).

### Prompts

Each prompt's time limit, and the overseer's body and a chore's run section (§19), which have none, say that the agent
will hear the minutes left on its tool calls near the end, and what such a line asks. The prompt says it once, so its
bytes change once and not per call, and the provider's cache holds (§6).

### Rejected

- The time in the system prompt (`experimental.chat.system.transform`, as aide adds memory under OpenCode): it changes
  the prompt on every call, so the provider's cache would miss the whole prefix. A tool's result is the end of the
  context, so a line there costs only itself.
- Refusing tools past a soft deadline, as aide's hook does: a refused push loses the work the warning is for, and the
  kill already ends the run.
- A file the agent is told to check: it spends a call to learn nothing, and a model under way forgets to.

TRUST_MODEL T3 and T4 hold it: canopy's own code runs inside the agent process, from a snapshot no run can write
through its permissions or its sandbox, reading one variable; the timeout in code stays the limit.

### What a run that winds down reports

A worker or planner the clock stops short reports `failed`, its summary naming what remains, which raises
`worker_failed` (§14) and waits for a human's reply as any failure does; a review reports `failed` as one it could not
finish. No status of its own: one that let a `resume` continue a pushed branch without a reply waits for real use to
ask for it. The overseer is warned as every agent is, in its last 3 minutes by default, to record what it owes first
(§6 step 5).

### Open

- Whether the overseer's last 3 minutes are enough to record what it owes.
- How long a run waits on a repository's `.opencode/` install when the registry is refused, as under the sandbox: the
  source does not say, and the live check times one.
