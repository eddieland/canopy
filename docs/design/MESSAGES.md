# Messages to running agents

Part of the canopy design, normative like all of it: the operator's message to a worker, a planner, or a one-off task's
worker while it runs, and how it reaches the agent. Sections are numbered across the whole design; the
[README](README.md) has the map. Previous: [Epics](EPICS.md).

## 44. Messages to running agents

Not yet built (ROADMAP M68); the code does not follow it until it is.

A running agent hears from the operator once, in its prompt, and after that only a letter answering a question of its
own (§41). What changes while it works, the ticket's scope or what the operator expects of its PR, reaches it at the
earliest in its next run's prompt, after it has pushed, or by `canopy stop`, which ends the run, with a wrap-up or at
once (§22), and spends its attempt. This section lets the operator send a running worker, planner, or one-off task's worker (§36) a message in
their own words and have it there within one tool call, without weakening what §33 and §41 hold: no line canopy adds
to a tool's result can be forged into an instruction.

### The message

A message to a running run is an operator message in its subject's conversation (§22), recorded through the function
every channel calls, with its guards, and naming the run it is for. Only the operator's channels send one, `canopy
reply run:ID` with words rather than a letter, or the run's page in the web UI, refused inside a tick or any run
(TRUST_MODEL T1), and refused for a run that has ended, which has the subject's reply instead. It ends the loop's wait
as any operator message does (§6); the tick finds the run working and leaves it. A review's run takes none, for now.

### How it reaches the agent

The agent is told that a message waits, and fetches it itself. canopy writes a mark, the newest message's id and
nothing of its text, to the run's answers directory (§41), which a sandboxed run reads and cannot write (§24), as a
stop's wrap-up ask is written (§22). canopy's plugin (§33) reads the mark after each tool call and, once per message
per session, adds one `[canopy]` line to the call's result saying a message from the operator waits and naming the
tool that returns it. The tool is
`messages`, served by the run's own server `canopy_run` beside `status` (§41), allowed by exact name in those
definitions and denied to every other agent (§27): it returns the messages sent to this run, oldest first, each marked
the operator's. The harness records the fetch from the call in the events it already reads (§8), so the journal says
when the run heard each message. An agent thinking without calling a tool hears nothing until its next call, as with
the clock.

Every prompt such a run gets says once that a canopy line may say a message waits, that what `messages` returns is the
operator's instruction, ranking as the prompt's own do, and that any other text claiming to be one is data; said once,
so the provider's cache holds (§6).

### What it does downstream

A message is answered by the run that fetched it once that run ends with its report, `ok` or `blocked`, which says what
it did with it; the loop then reads it as no `human_replied` and dispatches no `resume` for it (§7). A fetch alone
answers nothing: a message the run never fetched, or fetched and then failed, timed out, crashed, or was stopped before
its report, stays an operator message like any other, so the next run's prompt carries it and nothing is lost. A run's
page and `canopy show` list its messages and when each was fetched; one never fetched shows so.

### What holds it (TRUST_MODEL T1, T4)

- The line carries none of the operator's words, so a forged one, from a file, a PR, or a tool's result, can only make
  the agent spend a call to learn that nothing is new; it fails safe as the clock's and the nudge's lines do (§33).
- The text comes only from canopy's own tool, over the run's own server, which no text the agent reads can
  impersonate. The mark the plugin reads holds an id, never text, so the plugin cannot put the operator's words in a
  line.
- A message lifts nothing. A worker told to push elsewhere is steered as a ticket could steer it: branch protection,
  the harness's refusals, capacity, and attempt limits hold as before (T1, T3).
- The plugin's job reads one more file in the directory it is handed and writes nothing (T4). The server reads the
  journal as the run's `status` does; a sandboxed run's reach is unchanged (§24).

### Rejected

- The operator's text in the `[canopy]` line: forgeable. §41's rejection stands for words in a line; this section is
  how words arrive.
- A user turn queued into the running session, from the plugin or through `opencode serve`: the first gives the plugin
  a power T4 says it has not, the second is a T8 listener. How OpenCode treats a turn queued into a busy session is
  read from its source before either is reconsidered.
- The system prompt changed per call: the cache (§33).
- Killing the agent and continuing its session with the message: it can cut an edit or a test run in half, and the
  pushed branch, not the session, is the checkpoint (§4).

### Open

- A notice (§8) set or cleared mid-run, told the same way, once an outage during a long run shows the need.
- Whether a review's run should take a message.
