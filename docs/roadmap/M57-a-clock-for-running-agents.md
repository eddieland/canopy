# M57. A clock for running agents

DESIGN §8 and §13, TRUST_MODEL T3 and T4, issue #775, PRIOR_ART (A running worker hears nothing after its prompt).
Asked for by the operator (2026-10-18): warn a running agent before canopy's timeout kills it, as aide warns its
subagents before a soft deadline, so that a worker near the end pushes what it has rather than losing it with the slot,
and an overseer records its decisions. Today an agent is told `{{TIMEOUT_MINUTES}}` once, in its prompt, and has no
clock after that. Sketch only; the design comes first, in §13 beside what a run prints.

- **Stage 0, evidence and a source read.** A `measure` pass over the journal and run logs, in `MEASUREMENTS.md`: how
  many runs ended `timeout`, by kind, and for each whether its transcript shows edits after its last commit, so work
  the slot took with it. And a source read of the pinned OpenCode (1.19.3): that it loads plugins from
  `OPENCODE_CONFIG_DIR` (`{plugin,plugins}/*.{ts,js}`), that `tool.execute.after` runs for every tool a canopy agent
  calls (bash, edits, MCP tools) under `opencode run`, and that text added to its output is what the model reads next;
  that a plugin with no imports loads with no network, inside the sandbox (§24); and that the sandbox wrappers pass the
  variable below. Recorded on the `Status:` line; the operator decides whether to go on (2026-10-18), rather than a bar
  set now.
- **The deadline.** Every agent run canopy starts with a timeout (the overseer, workers of every kind, plans, splits,
  reviews, chores) gets `CANOPY_DEADLINE`, the moment its timeout fires, as Unix seconds, from the same clock `procs`
  kills it by. The kill stays the only guard (T3): the agent's own clock is advice.
- **The plugin.** canopy ships one OpenCode plugin with its definitions, snapshotted with `agents/` and `skills/` (§13,
  D040), so every run that loads canopy's definitions loads it, and its digest splits the runs into before and after.
  Plain JavaScript with no imports. On `tool.execute.after`, once the last fifth of the timeout has begun (at most its
  last 10 minutes), it adds one line to the tool's output: the minutes left, and, the first time in a session, to
  finish what keeps the work (commit and push, or record its decisions) and print the result line. After a built-in
  tool's `output`; first in an MCP tool's `content`, which is what its hook gets and which OpenCode truncates after the
  hook, keeping the head (§13, What OpenCode does with a plugin), so the tracker's, GitHub's, and the overseer's own
  tools (M48) carry it too. No variable, no line. It catches every error, since a hook that throws fails a call that
  has already run. It reads nothing else, writes nothing, refuses no call, and grants no tool. An agent thinking
  without calling a tool hears nothing until its next call; the prompt's time limit still covers that.
- **The snapshot, unwritable.** Any plugin makes OpenCode wait, before the session, for the `@opencode-ai/plugin`
  install it starts in each config directory it can write (§13), so the first run on a new snapshot would wait on the
  registry. canopy takes the snapshot's write permission away once it is written, owner's included, so OpenCode
  installs nothing there, and removes it as before. A repository's `.opencode/` is still installed into and waited
  for, inside the sandbox too.
- **Rejected:** `experimental.chat.system.transform`, which aide uses under OpenCode for memory: it changes the system
  prompt on every call, so the provider's cache would miss the whole prefix (M34); a tool's output is the end of the
  context, so a line there costs only itself. Refusing tools past a soft deadline, as aide's hook does: a refused push
  loses the work the warning is for, and the kill already ends the run. A file the agent is told to check: it spends a
  call to learn nothing, and a model under way forgets to.
- **Forged lines.** A file or PR the agent reads can print a line that looks like canopy's. One can only tell the agent
  to wrap up early, so it fails safe, as §21's reviewer marker does; the prompts say a canopy line asks for nothing
  else.
- **Prompts.** Each prompt's time limit line says the agent will hear the minutes left on its tool calls near the end,
  once, so the prompt's bytes change once and not per call.
- **Open for the design.** What a worker that winds down reports: `failed` with its summary naming what remains, which
  raises `worker_failed` as today (§14), or a status of its own, so that its pushed branch is continued without a
  reply. And whether the overseer, whose timeout is 15 minutes, warns early enough to record anything. And how long a
  sandboxed run in a repository with a `.opencode/` waits on that install when the registry is refused, which the
  source does not say; the live check times one.
- **TRUST_MODEL**, in the PR that builds it: T4 (canopy's own code now runs inside the agent process, from the
  snapshot a sandboxed run cannot write, reading one variable; a repository's own plugins already load there, T7's
  residual); T3 (unchanged: the timeout in code is the limit, and nothing an agent does with the clock extends it).
- Tests with the fakes: every role's run gets `CANOPY_DEADLINE` equal to its start plus its timeout; the snapshot
  holds the plugin and its digest changes with it, and is unwritable; the plugin's own tests, under Node's test runner
  from `make check`, for no line before the last fifth, the first line's wording, later lines' minutes, the line's
  place in a built-in and in an MCP result, no throw on an output of either shape or none, and nothing without the
  variable.
- **Later, on the same channel, not built here.** A notice (M35) set while runs are going reaches only runs started
  after it. A plugin that read the notice in force could tell runs already going. So could a request to wind down, from
  `canopy stop` without `--now` or a ticket closed or unlabeled mid-run (PRIOR_ART, Open design questions). Each needs
  a file the harness writes and a sandboxed run reads, so each waits for real use to ask.

Accept: Stage 0 recorded and the operator's go-ahead. Live, once built: a worker given a 5-minute timeout on a toy
ticket shows canopy's line in its transcript in its last minute and pushes before the kill; over the next week of
real use, `MEASUREMENTS.md` records how many `timeout` runs had pushed after a warning, against Stage 0's count.

Status: in progress. Stage 0's source read is done (2026-10-19, OpenCode 1.19.3 and `srt` 0.0.79, §13 What OpenCode
does with a plugin). Plugins load from `OPENCODE_CONFIG_DIR` as assumed, `tool.execute.after` runs after every call
that succeeds, MCP tools' included, and `CANOPY_DEADLINE` reaches a sandboxed agent with no change to the wrapper. It
changed the plan in three places: an MCP tool's hook gets the MCP result, whose text OpenCode truncates after the hook
keeping the head, so the line goes first in its `content`; any plugin makes every run wait for the
`@opencode-ai/plugin` install OpenCode starts in each config directory it can write, so the snapshot is made
unwritable; and a hook that throws fails the call, so the plugin catches everything. The measure pass over the
operator's journal and run logs, and the operator's go-ahead, remain.
