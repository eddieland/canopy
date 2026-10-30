# M65. Running agents say where they stand

REQUIREMENTS R6, DESIGN §8, §13, §21, §25, §27, and §33, TRUST_MODEL T1, T3, and T4. Asked for by the operator
(2026-10-28): workers, planners, and reviewers report where their work stands while they run, as two Paseo plugins
have agents do, so the operator reads a card instead of the transcript. [Status][status] gives each agent a short card
it rewrites whole: a summary, its state, what it is doing now, what is done with the proof of each, and what is next,
marked stale once the agent stops updating it. [Progress][progress] gives a long job a dashboard of steps, each with a
status and stage, percent done, what is stuck, and questions with lettered options and a recommendation that the agent
works around while it waits.

Today a running run shows its session, what it has spent, and its latest tool call, read from the events it prints
(§8); what it thinks of its work comes only in its final line, once it exits. A card fills that gap for every role
canopy runs with a timeout, on the same channel: the agent's printed events, which canopy already reads line by line.
Three stages, in order, each in its own PRs; stage 3 waits for its own go-ahead.

- **Stage 0, a source read.** Of the pinned OpenCode (1.19.3, and 2's 2.1.x): that a tool call's input reaches the
  events `opencode run` prints when the call is made, not only at the session's end, for an MCP tool as for a built-in;
  how long that input may be; and whether OpenCode's own `todowrite` would serve for steps instead of a tool of
  canopy's. Recorded on the `Status:` line; it may change the shape of stage 1.
- **Stage 1, the card.** One tool, `status`, served by `canopy _mcp --status` over stdio to every worker, planner, and
  reviewer run, allowed by exact name in their definitions. The server validates the call and writes nothing: the
  harness records the card from the call's input in the events it already reads (`_Progress`), so nothing the agent
  writes reaches the journal but through what canopy observes it print, as its spend does now (§27's "Workers are out
  of scope" sentence changes with it). Each call replaces the run's whole card:
  - **summary**, one or two sentences for someone who skipped the transcript;
  - **now**, what it is doing this moment;
  - **done**, finished steps, each with its proof ("tests pass: 42/42", "pushed abc123", "not pushed" when true);
  - **next**, what is left, in order;
  - **stuck**, optional: what is in its way that it is working around, such as CI down or a flaky test (§23).

  Each field is bounded and plain text. The card is shown to the operator, never put in another agent's prompt in this
  milestone, so neither the overseer's cache (§6) nor its trust in worker text changes (T1). The run keeps its last card
  after it ends, beside its summary.
- **Staleness, seen and nudged.** The card says how old it is, in minutes and tool calls. canopy's plugin (§33) gets a
  job: after a number of tool calls with no `status` call, it adds one `[canopy]` line to the next tool's result asking
  for an update, once per lapse, so the agent is asked between calls and never mid-thought. It counts in its session
  and keeps nothing else, as the clock keeps whether it has warned. A forged line can only ask for a card, so it fails
  safe (§33's Forged lines).
- **Where it shows.** The web UI's running runs and the ticket's page show the card and its age, and a review's page
  its own; `canopy status` shows each running run's `now` and age; `canopy show-run` the whole card. A stale card turns
  amber rather than going quiet. No notification: the sinks hear of what a run ends with, as today (§20).
- **Stage 2, steps.** A card may carry steps, each with a title, a status (`not_started`, `working`, `blocked`,
  `done`, `skipped`), and an optional stage, and canopy shows percent done and the working step's stage. A worker
  whose ticket has an approved plan (§25) is told to take its steps from the plan, so the operator follows the plan
  they approved being done; a planner's and a reviewer's steps are their own. A working step with no update for longer
  than the run's last fifth is shown stuck. Estimates per step wait for real use to ask for them.
- **Stage 3, questions while working (its own go-ahead).** A question on the card, with lettered options and the
  agent's recommendation, that the agent works around while the operator decides, as Progress's "Work around" mode
  does; the operator answers from the web UI or `canopy reply`, and the answer reaches the running agent on its next
  tool call, through the plugin. That needs a file the harness writes and a sandboxed run reads (§24), the channel M57
  left for later, and it is the first operator word to reach a running agent, so it gets T1 and T4 of its own. A
  question the agent cannot work around stays what it is today: a `blocked` final line (§8). The operator decides
  whether to build this once stages 1 and 2 have been in real use.
- **Rejected:** a model summarising the transcript each few minutes, as Status rejects it: a run per summary, and it
  can misread what the agent knows. A file in the worktree the agent writes: it can be committed, and a sandboxed run's
  writes outside the worktree are refused. The agent's final line alone, as now: it says nothing while the run goes.
- **TRUST_MODEL**, in the PR that builds stage 1: T1 (the card is agent text that may echo a ticket's or a PR's, shown
  to the operator as data and given to no agent); T4 (the plugin's new job counts tool calls in its session and writes
  nothing); T3 (unchanged: nothing on a card extends a run or holds a slot).
- Tests with the fakes: a fake worker, planner, and reviewer that call `status` mid-run show their card on the running
  run before they exit, and keep the last one after; an invalid or overlong call is a tool error and records nothing;
  the server lists the tool only where `CANOPY_RUN_ID` names a worker's, planner's, or review's run; the plugin's own
  tests for the nudge's count, its wording, and its place in a built-in and an MCP result.

Accept: Stage 0 recorded. Live: a worker on a toy ticket with a plan shows a card in the web UI within its first
minutes, its steps the plan's, and its last card on the ended run; a reviewer's card shows on its review while it
runs; over a week of real use, `MEASUREMENTS.md` records how often a running card was stale, by role. Stage 3, once
built: a worker on a toy ticket, sandboxed and not, that asks a question on its card hears the letter given on its run's
page on its next tool call, as its transcript shows, and goes on with that option.

Status: in progress. Stage 0 read 2026-10-29, from the builds npm ships (`opencode-linux-x64` 1.19.3 and
`@opencode/cli-linux-x64` 2.1.4), and leaves stage 1's shape as it is. `opencode run --format json` prints a tool
call's `tool_use` event, its whole input in `part.state.input`, as the call ends (`completed` or `error`), from the
session's live event stream, not at the session's end: 1 when the part's state turns `completed` or `error`, 2 on
`session.tool.success` or `session.tool.failed`; an MCP tool's part is a built-in's, named `<server>_<tool>`. So a
`status` call reaches `_Progress` the moment its server answers, which for a server that writes nothing is at once.
Neither version cuts a tool's input before printing it, only its output; the bound is the tool's own, so the server
and the harness both hold the card to it, and the harness reads only a `completed` call. OpenCode's own `todowrite`
(both versions: `content`, `status` of `pending`, `in_progress`, `completed`, or `cancelled`, and 1's `priority`)
would not serve for steps: it has no `blocked`, no stage, no proof of what is done, and no summary or `now`, and
every worker already has it; so steps go on canopy's card in stage 2, and `todowrite` is left as it is.
Stages 1 and 2 built 2026-10-29 and checked against the fakes: the card is DESIGN §41, the `status` tool served by
`canopy _mcp --status`, the nudge a job of canopy's plugin, and the card shown in `canopy status`, `canopy show`, and
the web UI; steps, their share done, their stage, and a stuck step on top. Stage 3 built 2026-10-29, at the
operator's go-ahead that day, and checked against the fakes: a card's question, with lettered options and the one the
agent recommends, answered with a letter from `canopy reply run:ID` or `review:ID` or the card in the web UI, and
written to the run's answers directory, which the sandbox lets the run read and not write, where canopy's plugin tells
the agent on its next tool call. An answer is a letter, never words, so a forged `[canopy]` line can choose only one of
the agent's own options (TRUST_MODEL T1). The live checks above, stage 3's among them, and the week of
`MEASUREMENTS.md` wait on the operator.

[status]: https://github.com/fullstackhouse/paseo-status
[progress]: https://github.com/stevecastaneda/paseo-plugins/tree/main/progress
