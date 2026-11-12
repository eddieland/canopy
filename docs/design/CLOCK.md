# A clock for running agents

Part of the canopy design, normative like all of it: how a running agent learns how long it has before canopy's timeout
ends it. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Feedback
plans](FEEDBACK_PLANS.md). Next: [Published reviews](PUBLISHED_REVIEWS.md).

## 33. A clock for running agents

Built (ROADMAP M57), and checked against the fakes; its live check is SCENARIOS S61.

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
JavaScript that imports only the runtime's own `node:fs`, and that only when it reads a run's answer (§41), so it loads
with no network, inside the sandbox too. It holds each job canopy asks of the agent process, the clock its first: each
job reads only what it is handed for that job, and its hooks run in a try of their own, so one that throws fails
neither the call nor the jobs after it. A later job joins this file rather than shipping a plugin of its own, as the
nudge for a stale update, the answer to its question, and a stop's wrap-up ask have (§22, §41), and the word that a
message waits (§44). OpenCode loads the file by its default export: an id, and a `setup` that registers the jobs'
hooks.

After each tool call that succeeds (`execute.after`, MCP tools' included), once the run is in the last fifth of
the time it had when the plugin loaded, and never more than its last 10 minutes, the plugin adds one line to the call's
result: the minutes left, and, the first time in a session, to finish what keeps the work (commit and push, or record
its decisions) and report its result. The line goes first in the result's content, since OpenCode truncates every
tool's result after the hook, keeping its head; so the tracker's, GitHub's, and the overseer's own tools (§27) carry
it too. Counting from its own load, at the session's start, keeps it to one variable.

What lets it run inside every agent process (TRUST_MODEL T4):

- The clock reads `CANOPY_DEADLINE` and the clock, nothing else. Without the variable it adds nothing.
- It writes no file, refuses no call, and grants no tool; the one call it changes, a shell command's leading `cd`,
  the runtime checks after it. It keeps nothing but whether it has warned in this session.
- It catches every error, since a hook that throws fails a call that has already run.

An agent thinking without calling a tool hears nothing until its next call; its prompt's time limit covers that.

### MCP tools on the first call

OpenCode registers an MCP server's tools only once the server has connected, as the session starts, and sends each
model call the tools registered when it is made: without a wait, a session's first call gets none of them, and the
overseer, which acts only through canopy's tools (§27), has nothing to call. So the plugin holds a session's first
prompt while a server is still connecting, at most 30 seconds, then while a connected server has no tool registered,
at most 2 seconds more, since one may have none; then the prompt goes on as it would have. It reads the servers' names
and states and the tools' names, changes none of them, and catches every error, as the clock does.

These rest on OpenCode's source at 2.1.2, read 2026-10-22 and read again on an upgrade: OpenCode loads plugins from
every config directory, the snapshot's last, so a repository's own plugins already run in the agent's process (T7);
it loads a plugin file only by a default export with an id and a `setup` that registers hooks, and logs any other and
runs without it; a hook that throws fails the call; and every tool's result is truncated after the hook. A hook before
a call changes the input the tool runs with (read 2026-11-02).

### A shell command's leading `cd`

OpenCode refuses a shell command that leads out of the agent's directory, and checks each `cd` and path in it from
where the command starts, not from where an earlier `cd` in it went: `cd app && cat ../README.md`, which stays inside,
is refused, and the refusal does not say why. Before each shell call, the plugin moves the command's leading
`cd <dir> &&` into the call's working directory, where the shell would have run the rest. The runtime checks that
directory, and the rest from it, as it checks any call's, so the job reaches nothing the `cd` could not, and a `cd` out
is refused as before. A directory the shell would expand is left in the command.

### A refusal, explained

OpenCode tells an agent a call its permission rules refuse as `Permission denied:` and the permission, nothing more,
so an agent tries the same another way and spends its run on it. After such a call (`execute.after`) the plugin sets
the refusal's reason to the runtime's words, what the call asked for, and one `[canopy]` line: the rules refuse it on
purpose, it is not to be tried another way, and the result says what remains if the work needs it. It changes
nothing else of the error, so the call stays refused as it was, and it reads only the refusal's permission and
resources. A rule the repository or the operator set is explained as canopy's are (T7). OpenCode's `evaluate`
permission hook cannot do it: a refusal by the rules returns before the hook (2.1.2, read 2026-11-03; 2.2.5's build,
2026-11-11).

### The snapshot, unwritable

With any plugin configured, OpenCode waits, before the session, on an npm install of its plugin package into each
config directory it loads and can write, so the first run on a new snapshot would wait on the registry
(MEASUREMENTS 2026-10-19, F50). canopy takes the snapshot's write permission away once it is written, the operator's
included, so OpenCode installs nothing there, and gives it back only to remove the snapshot (§26).

A repository's `.opencode/` that the run can write is still installed into and waited for, inside the sandbox too: with
canopy's plugin, every run in such a repository pays that wait, not only one whose repository ships a plugin.

### Forged lines

A file, a PR, or a tool's result the agent reads can print a line that looks like canopy's. One can only tell the agent
to wrap up early, or that it has longer than it has, which leaves it where it is without the clock; so a forged line
fails safe, as the comment marks do (§8, D069). The prompts say a line from canopy asks for nothing but wrapping up,
an update (§41), or a fetch of the operator's message (§44), so one that asks for more is data (T1).

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
