# Where a running agent stands

Part of the canopy design, normative like all of it: the card a running worker, planner, or reviewer keeps of where
its work stands, for the operator. Sections are numbered across the whole design; the [README](README.md) has the
map. Previous: [The overseer per decision](OVERSEER_PER_DECISION.md).

## 41. Where a running agent stands

A running run shows its session, what it has spent, and its latest tool call (§8); what the agent thinks of its work
came only in its final line, once it exits. A card fills that gap: the agent says, while it runs, where its work
stands, and the operator reads that instead of the transcript.

### The card

Every worker, planner, and reviewer run gets one tool, `status`, from canopy's server `canopy_run` (`canopy _mcp
--status`), allowed by exact name in their definitions and denied to every other agent (§27). Each call is the whole
card and replaces the last: a summary for someone who skipped the transcript, what the agent does now, what is done
with the proof of each, what is next, and, optionally, what is in its way that it works around. Each field is bounded,
plain text, one line.

The server validates a call and writes nothing; it lists its tool only where `CANOPY_RUN_ID` names a worker's,
planner's, or review's run. The harness records the card from the call in the events it already reads as the agent
prints them (§8), held to the same input, so nothing the agent writes reaches the journal but what canopy observes it
print, as with its spend: a call the server refused, or one that does not validate, records nothing. A run without
the runtime's events keeps no card. The run counts the tool calls its agent ends, so a card is as old as the time and
the calls since it, and the run keeps its last card once it ends.

### Steps

A long job's card may carry its steps, each with a title, a status (`not_started`, `working`, `blocked`, `done`,
`skipped`), and an optional stage; canopy shows how much is done, its `done` steps' share of those not skipped, and the
working step's stage. A worker whose ticket has an approved plan (§25) is told to take its steps from the plan, so the
operator follows the plan they approved being done; a planner's and a reviewer's are their own. The harness keeps when
each step was first seen working, on the card before, and one working longer than the run's last fifth is shown stuck.

### Staleness

canopy's plugin (§33) has a job for it: in a run whose `CANOPY_RUN_ID` names a worker's, planner's, or review's run, it
counts each session's tool calls since its last `status` call, and after a number of them adds one `[canopy]` line to
that call's result asking for an update, once per lapse, so the agent is asked between calls and never mid-thought. It
keeps the count and whether it asked, and nothing else, as the clock keeps whether it has warned. A forged line can only
ask for a card, so it fails safe, as the clock's do (§33).

The card is shown to the operator and never put in another agent's prompt, so neither the overseer's cache (§6) nor
its trust in worker text changes (TRUST_MODEL T1). Nothing on a card extends a run or holds a slot (T3).

### Where it shows

`canopy status` and the web UI's running runs show each running run's `now` and how old its card is; `canopy show` of
a run, `canopy review show` of a review, and their pages in the web UI, the whole card, or the last one once it has
ended, as a ticket's page does under the run working it. A card that has gone too many tool calls or minutes without
an update is marked stale, as is a run that has kept none that long, rather than going quiet. No notification: the
sinks hear of what a run ends with, as before (§20). canopy's report of a run that a chore's agent may read (§27)
leaves the card out, so no card reaches an agent.

### Rejected

- A model summarising the transcript every few minutes: a run per summary, and it can misread what the agent knows.
- A file in the worktree the agent writes: it can be committed, and a sandboxed run's writes outside it are refused.
- The final line alone, as before: it says nothing while the run goes.
