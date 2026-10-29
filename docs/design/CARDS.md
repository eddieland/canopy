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
print, as with its spend: a call the server refused, or one that does not validate, records nothing. A run without the
runtime's events keeps no card, nor does a one-off task's run (§36), which is never given the server. The run counts the
tool calls its agent ends, so a card is as old as the time and the calls since it, and the run keeps its last card once
it ends.

The card is shown to the operator and never put in another agent's prompt, so neither the overseer's cache (§6) nor
its trust in worker text changes (TRUST_MODEL T1). Nothing on a card extends a run or holds a slot (T3).

### Rejected

- A model summarising the transcript every few minutes: a run per summary, and it can misread what the agent knows.
- A file in the worktree the agent writes: it can be committed, and a sandboxed run's writes outside it are refused.
- The final line alone, as before: it says nothing while the run goes.
