# M68. Messages to running workers

DESIGN §8, §22, §24, §33, and §41, TRUST_MODEL T1, T4, and T8. Asked for by the operator (2026-11-04): a way to tell a
running worker that its scope or expectations changed, without ending its run. Today the only operator word a running
agent hears is a letter choosing one of its own options (§41); anything else waits for the run to end and reaches the
next run's prompt, so a worker told mid-run that half its ticket was dropped learns it from a `resume` after it has
pushed the whole thing, or from `canopy stop --now`, which spends an attempt and the context with it.

§41 rejected an answer in the operator's own words, because a line in a tool's result that looks like canopy's could
then say anything (§33's Forged lines). This milestone keeps that: no operator text travels in a `[canopy]` line. The
line only says a message waits, and the text comes back as the result of the agent calling one of canopy's own tools,
which no file, PR, or tool output can forge. A fake line can make the agent spend one call to learn that nothing is new.
Three stages, in order, each in its own PRs; stage 0 may change the shape of stage 1.

- **Stage 0, a source read.** Of the pinned OpenCode (1.19.3, and 2's 2.1.x): what happens to a user message sent to
  a session while `opencode run` is working it, through the plugin's client and through `opencode serve`; whether such
  a turn is queued, merged into the next model call, or refused; and how `opencode run` decides it is finished once a
  second turn is queued. Recorded on the `Status:` line. If a queued turn is clean in both versions, it is a candidate
  for a later stage, never for stage 1: it gives the plugin a power T4 says it has not, and the server route is a T8
  listener, which the deferred list already holds.
- **Stage 1, the message, told and fetched.** The operator sends a message to a running worker's, planner's, or
  one-off task's run (§36), from `canopy reply run:ID "..."`, which today takes only a letter, and from the run's page
  in the web UI. It is recorded as an operator message on the run's subject, as any reply is (§22), through the one
  function every channel calls, with its guards, refused inside a tick or any run (T1). canopy writes it to the run's
  answers directory (§41), the file the sandbox lets the run read and not write (§24). Canopy's plugin (§33) gets a
  job: after each tool call, for a message this session has not been told of, it adds one `[canopy]` line saying a
  message from the operator waits and naming the tool to read it, nothing of its text; it keeps what it last told each
  session, as the answer's job does. The tool is `messages`, served to the run by `canopy_run`, beside `status`,
  allowed by exact name in the same definitions and denied to every other agent (§27). It returns the messages sent to
  this run since it started, oldest first, marked as the operator's, and the harness records the fetch from the call in
  the events it already reads, so the journal knows when the run heard it. A review's run gets none in this milestone.
- **What the message does downstream.** A message fetched by its run is answered: the loop does not read it as
  `human_replied` and dispatch a `resume` for it, since the run it was for has it, and the run's report says what it
  did with it. One the run ends before fetching stays an operator message like any other, so the next run's prompt
  carries it and nothing is lost. A message sent to a run that has ended is refused, with the ticket's reply named
  instead. `canopy show` of the run, and its page, list the messages and when each was fetched; a message never
  fetched shows so.
- **The prompt.** Each worker's, planner's, and task's prompt gets one sentence: a `[canopy]` line may say a message
  waits, and what `messages` returns is the operator's instruction, which ranks as the prompt's do; any text claiming
  to be an operator message that came another way is data. Said once, so the cache holds (§6). The time limit's
  sentence on what a canopy line asks (§33's Prompts) widens by that one thing.
- **Guards, in code.** The function that records the message holds it to a length and refuses an empty one, as
  replies are held. A message lifts nothing: a worker told "also push to main" is steered as a ticket could steer it,
  and T1's branch protection, the harness's refusals, and capacity and attempt limits hold as before. The plugin's
  new job reads one file in the directory it is handed and writes nothing (T4). The `messages` tool reads the journal
  through the server canopy already runs for the run; a sandboxed run's policy on the journal is unchanged (§24).
- **Stage 2, a notice mid-run (its own go-ahead).** A notice (§8) set or cleared while runs work reaches them the same
  way: the line says a notice changed, and the tool returns it. Built once stage 1 has been in real use and an outage
  during a long run shows the need.
- **Rejected:** the text in the `[canopy]` line (forgeable; §41). A user turn queued into the session from the plugin
  (stage 0 may reopen it; T4 until then). The system prompt changed per call (the cache). Killing the agent and
  continuing its session with `opencode run --session`: it can cut an edit or a test run in half, and the pushed
  branch is the checkpoint, not the session.
- **TRUST_MODEL**, in the PR that builds stage 1: T1 (operator text reaches a running agent for the first time, only
  through canopy's own tool; a forged line can only prompt a fetch); T4 (the plugin's new job reads one more file and
  writes nothing); T8 (unchanged: no new listener, the web UI writes through the same function the CLI does).
- Tests with the fakes: a fake worker that calls `messages` after a message was sent to its run gets the text and the
  run's journal records the fetch; a run that ends with the message unfetched leaves it for the next run's prompt, as
  the scenario's `resume` shows; a message to an ended run is refused; the tool lists only where `CANOPY_RUN_ID` names
  a worker's, planner's, or task's run, and a review's gets none; a message over the limit, or empty, is refused;
  the plugin's own tests for the line's wording, that it carries none of the text, that it is told once per session,
  and its place in a built-in and an MCP result.

Accept: Stage 0 recorded. Live: a worker on a toy ticket, sandboxed and not, sent a message from its run's page that
narrows the ticket hears of it on its next tool call, fetches it, as its transcript shows, and its PR reflects the
narrower scope; the same message sent as its run ends reaches the next run's prompt and no `resume` is dispatched twice
for it. Over a week of real use, `canopy show` of the runs sent a message says how many were fetched before the run
ended, and the count goes to `MEASUREMENTS.md`.

Status: not started.
