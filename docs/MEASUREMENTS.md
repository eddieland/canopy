# canopy measurements

Live measurements of canopy against the operator's real queue, which ROADMAP milestones cite as their reason or their
acceptance. Each section is dated and is not edited after: a re-measurement is a new section, so a milestone can say
what it changed. Sections name no ticket keys, PR numbers, people, or tools of the operator's employer; they say what
kind of thing each was.

## 2026-10-12: overseer spend over the first live session

What a tick's overseer costs, what it spends it on, and whether a deterministic probe (a script that fingerprints
tickets and PRs and wakes the overseer only on a change) would save enough to be worth building. Cited by M11, M21,
and M28 to M30.

### Setup

- One workspace, Jira through Atlassian's remote MCP, GitHub through its MCP server, OpenCode as the runtime.
- Ticks 1 to 41 over about two hours (20:52Z to 22:53Z) of active use: the operator started tickets from the web UI,
  answered questions, and pressed "tick now". `loop.interval_minutes = 15`, `loop.idle_max_minutes` at its default
  (120).
- Five tickets, all private (started from the web UI, so none came from the tracker query), and six agent PRs.
- Sources: the journal opened read-only, `canopy.log`, and each tick's overseer output in `ticks/<id>.log`, parsed
  per step (tokens, cost) and per tool call (tool, result size). The analysis was an OpenCode session given the
  prompt [below](#re-measuring).

### Spend

| | runs | cost |
|---|---|---|
| Overseer (ticks; one abandoned dry run recorded none) | 40 | $14.19 |
| Workers | 14 | $6.27 |
| Reviews (record no cost yet) | 7 | none recorded |

Per tick: mean $0.355, median $0.345, from $0.177 to $0.670. A tick averaged 6 model steps and 8.6 MCP calls.

| a tick's cost went to | share | tokens |
|---|---|---|
| The prompt and state block, re-sent each step | 56% | about 51k at the first step; about 0.7k per ticket |
| Tool results: re-reading the tracker and GitHub | 29% | about 19k added per tick (from 1k to 43k) |
| The model's own output and reasoning | 15% | |

Cache reads were 87% of processed tokens. The first 32k tokens (system prompt and tool schemas) are a prefix the
provider caches for about five minutes, so 12 of 40 ticks started cold. Cold ticks averaged $0.44 and warm ones $0.32;
the difference is the cache write. Any change that spaces ticks out makes every remaining tick a cold one.

### Ticks by what they did

A tick was **productive** if it dispatched a run or review, changed a ticket's or unit's phase or cursor, or changed
the attention list; **idle** otherwise.

| class | ticks | spend | share |
|---|---|---|---|
| Productive, acting on new state | 25 | $8.79 | 62% |
| Productive only by churn or bookkeeping (F5) | 4 | $1.97 | 14% |
| Idle | 6 | $1.83 | 13% |
| Idle because the overseer could not run `canopy` (F1) | 5 | $1.60 | 11% |

What ended the wait before each tick (ticks 2 to 41): a run or review run ending 18, an operator message 8, a loop
start 8, "tick now" 4, a `fix-ci` cooldown coming due 1, the timer 1. **38 of 40 ticks were woken by a harness or
operator event.**

### Findings

- **F1. Five ticks paid full price with no working CLI.** Two found no `canopy` on the overseer's PATH; three found
  the launcher's cached environment gone (ENOENT) while the loop kept running. Each read the whole world and could
  record nothing; two still closed `ok`. A $0 check before the overseer runs would have saved all five. → M28.
- **F2. Five of eight `overseer_failed` ticks did their work.** They recorded their decisions and then wrote a summary
  after `tick complete`, so the last line was not the done line. Each raised a failing-loop notification and, not
  being `ok`, cannot count as idle. The prompt already says to print only that line. → M28.
- **F3. A ticket started from the web UI does not wake the loop.** Only operator messages and runs ending do
  (`loop/repeat.py`). Three starts waited for a manual "tick now"; one waited 11 minutes for the timer. → M28.
- **F4. All seven review runs ended `unknown`** within about 15 seconds: the reviewer's last line was not a valid
  result. The overseer's retry and give-up ticks for them cost $2.21. Not diagnosed. → M11.
- **F5. The overseer churns.** With nothing external changed, one tick relabelled three phases, one dropped an
  attention item, and one re-added an item an earlier tick dropped. A tick that changes a phase or the attention list is
  not idle, so churn resets idle pacing's count. → M28.
- **F6. Most tool-result volume is re-reading unchanged things.** PR reads were 35% of tool-result characters (119
  calls, mostly PR bodies), tracker searches 29%, and PR status lists 19% (30 or more CI contexts each). The approved
  PR was read 79 times over 23 ticks with no change after its approval. The provider skill was loaded by a tool call
  on every tick: 8.5% of the volume. → M30.
- **F7. Idle pacing was never tested by this session.** Only ticks 2 to 5 were idle by the loop's rule. The analysis
  read that as re-recorded `wait` and attention decisions resetting the count; they do not (`loop/pacing.py` counts
  both as quiet). Every later tick followed a run ending, an operator message, or a failed overseer, each of which is
  not idle by design (DESIGN §6). Reaching the cap in a steady state, about 13 cold ticks or $6 a day, is still M21's
  overnight check. → M21, M29.
- **F8. A probe gate would have saved little in an active session.** Gating the overseer on a fingerprint change or a
  harness event would have skipped 0 to 5 of the 40 ticks, $0 to $1.94 (up to 14%), with no action delayed. It would
  have seen two PRs go green about 12 minutes before the timer tick did. Its value is latency and the steady state,
  where it matches idle pacing's cost at the cap and polls cheaply in between. → M29.
- **F9. What a probe must and must not fingerprint.** GitHub's combined status `state` stayed `pending` on every green
  PR: two contexts on this repository stay pending until a human acts, and the combined list stops at 30 contexts, so
  some reads dropped the main CI context. A probe on the combined state would have missed every transition to green.
  CI needs named contexts per repository. Draft to ready is worth a field. PR issue comments are not: a bot edited its
  summary comment repeatedly, and the overseer read issue comments 7 times without acting. Private tickets never
  appear in the tracker query, so a start is a harness wake (F3), not a probe field. → M29.
- **F10. Latency from an external event to the first tick that saw it:** median about 2 minutes, because events rode
  along on run-ending wakes; worst about 13 minutes (the timer). A probe polled every 2 minutes, one GraphQL call for
  all open PRs plus one tracker search, matches the median. → M29.

### Re-measuring

Re-run after M28, and after M21's overnight run, with the same prompt in a plain OpenCode session at the workspace
root (not one canopy started). It is read-only and calls no MCP tool. The idle classification it asks for should
follow `loop/pacing.py`, not its own reading of the log (F7).

```text
I'm evaluating whether canopy should gate overseer runs on a cheap deterministic "probe". Analyze this workspace's
canopy history. This is read-only analysis.

Rules:
- Do not run any canopy command that writes. Do not call any MCP tool or touch GitHub or the tracker. Do not modify
  any file except the report below.
- Open the journal read-only: `sqlite3 -readonly .canopy/canopy.db`. Start with `.schema`.
- Sources: the journal, `.canopy/canopy.log` (JSON lines with tick ids; `loop waits` lines carry `idle`,
  `idle_count`, `wait_seconds`), and each overseer's output in `.canopy/ticks/<tick id>.log` (OpenCode JSON events).
- Classify idle ticks by canopy's own rule in src/canopy/loop/pacing.py (`idle`), not by your own reading.

Answer, with numbers and the queries you used:
1. Spend: overseer cost and tokens per day, live vs dry run; how many ticks have NULL cost.
2. Productive vs idle ticks, count and spend for each, and the share of spend on idle ticks.
3. Per tick: tool calls by tool, tool-result tokens vs prompt and state tokens, cache-read share, cold vs warm cost.
4. For every productive tick, what change made it productive (run ended, operator message, ticket started, CI, review,
   new head, PR closed or merged, tracker comment or label, gate due, or nothing external).
5. For each of those, whether a probe fingerprinting tickets (updated, latest comment id, labels, state, query keys)
   and PRs (head SHA, named CI contexts, latest review id, mergeable, draft, state) plus harness wake events would
   have noticed it; list every miss.
6. If the overseer ran only on a probe change or harness event, plus every 2 hours: ticks run, cost, delays.
7. Overseer failures and their causes, the most expensive ticks and why, and anything re-read every tick unchanged.

Write the report to `.canopy/probe-analysis.md` and end with a ten-line summary.
```

## 2026-10-13: overseer spend over the first day

The same questions over a day: what a tick costs, what woke it, and what a probe would have to watch. It re-measures
the 2026-10-12 section, which it contains (its ticks 1 to 41 are this section's first 41). Cited by M11, M21, M28 to
M30, and M34.

### Setup

- The workspace, tracker, and runtime of 2026-10-12, now with tickets from the tracker query too: ticks 1 to 158, from
  2026-10-12 20:52Z to 2026-10-13 18:13Z. The loop was down from 03:32Z to 13:12Z, so this is no overnight run.
- The loop now records each tick's `idle` and `woken_by` (M33), from tick 69 on.
- The per-token price roughly halved from tick 100 on: the median first step fell from $0.124 to $0.066 for the same
  context, so a model or price change. The done-line fix (`CANOPY_TICK_DONE`, M28) landed at 18:16Z, just after the
  window, so every failure on the old line is in it.
- The analysis was an OpenCode session given the [2026-10-12 prompt](#re-measuring), read-only. Its classifications
  are its own; the findings below correct them where the code says otherwise.

### Spend

| | runs | cost |
|---|---|---|
| Overseer (ticks; one abandoned dry run recorded none) | 157 | $52.53 |
| Workers | | $21.06 |
| Reviews | 11 | $1.33 |
| Chores | | $0.78 |

The overseer was about 70% of agent spend. Median tick $0.345 over the day: $0.41 for ticks 1 to 99, $0.18 for ticks
100 to 158.

| a tick's cost went to | share |
|---|---|
| The first step: about 32k cached tokens of system prompt and tools read, about 23k to 25k of prompt and state written fresh to the cache | 41% |
| The tool loop: each step re-reads the growing context from cache, each tool result is written once | 59% |

A median tick took 6 steps and 12 tool calls and added about 14k tokens of tool results (8k from tick 100 on). An idle
tick and a productive tick cost the same: the decision is a few hundred tokens of output.

| tool-result tokens came from | share |
|---|---|
| GitHub PR reads (`get` 586 calls, status 207, reviews 154, comments and check runs 72) | 62% |
| Tracker searches (239 calls) and issue reads | 28% |
| The provider skill, loaded by a tool call on 141 ticks | 7.5% |
| canopy's own commands | 1% |

### Ticks by what they did

Classed as in 2026-10-12, with one more class: an attention-only change is a **flap** when every item it added or
removed had also toggled within the 6 ticks before.

| class | ticks | spend | share |
|---|---|---|---|
| Productive (a dispatch, `done`, `mirror`, or a phase or cursor change) | 99 | $35.94 | 68% |
| Attention-only, real | 9 | $1.91 | 4% |
| Attention-only, flap | 13 | $2.72 | 5% |
| Idle | 36 | $11.96 | 23% |

Of the 36 idle ticks, 11 were idle by the loop's rule (`pacing.idle`). The other 25 followed a run ending or an
operator message, which is not idle by design (DESIGN §6), and did nothing. 21 ticks ($8.64) closed `overseer_failed`;
16 of them ($7.41) only because a summary followed the old done line, and most of those did their work.

What woke the 157 ticks: a run ending 66, an operator message 49, the loop starting 14, the timer 13, "tick now" 12,
a gate 3. Mean gap between ticks 7.5 minutes; 103 of 158 gaps under 2 minutes.

### Findings

- **F11. The fixed overseer prompt is rewritten to the cache every tick.** canopy passes `overseer.md` (45 KB, about
  13k tokens) and the state block as one message (`prompts.render_overseer`); the agent definition's own body is a
  stub. The state block changes every tick, so the message never hits the cache and the fixed part is paid as a cache
  write each time. That is most of F12's fresh 23k to 25k, read from the code, not yet measured by moving it. About
  13k tokens a tick from cache write to cache read is about $0.06 at the early price and $0.03 at the later, 15 to 20%
  of a median tick, with no probe and no trust change. → M34.
- **F12. The first step is 41% of overseer spend ($21.47).** 32k tokens of system prompt and tool schemas hit the
  cache; the prompt and state do not (F11). → M34.
- **F13. A probe gate would still save little.** 144 of 157 ticks were woken by a harness or operator event and would
  run anyway. Of the 13 timer ticks, 9 found nothing changed; skipping them, and 5 idle ticks after loop restarts,
  saves $3.32 to $4.76 (6 to 9%), with no action delayed. The 2-hour safety net never fires: the longest gap while the
  loop was up was 77 minutes. → M29.
- **F14. Most tool results are still re-reads of unchanged things.** The PR approved on 2026-10-12 was read 170 times
  before a human merged it the next afternoon; a green draft waiting on the operator 167 times; two more PRs 119 each.
  A ticket the operator stopped was in the tracker search on 92 ticks and recorded `wait: stopped` each time. The
  analysis models facts supplied in the state block (M30) at about 40% less overseer spend; that model drops every
  GitHub and tracker read, which a productive tick that needs a review's findings or a failure's detail cannot, so
  take it as an upper bound until measured. → M30.
- **F15. What the loop does not wake for.** A ticket started or stopped (`starts`), attempts granted
  (`canopy grant`), and a config reload all wait for the next timer tick: `Woken` is a message, a run, or the key
  (`loop/repeat.py`). The analysis read `woken_by = "start"` as a ticket start; it is the loop starting. Run, chore
  run, and review run endings already wake it (`db.runs_moved_after`). → M28.
- **F16. What a probe must also watch** (beyond 2026-10-12 F9): the latest build or check-run id per named CI
  context, since a re-run at the same head goes red to red and a probe polled outside the pending window sees no
  change; and every PR the journal records on an unfinished unit, merged and closed included, since a list of open
  PRs drops a merged one instead of reporting it. Six merges and one close were seen only because a run ending woke
  the loop nearby. A reload that changes the tracker query changes what the probe lists. → M29.
- **F17. The overseer flaps attention items.** 13 ticks ($2.72) changed the attention list only by leaving out an
  item and restoring it a tick later, one item toggling over 29 ticks with nothing underneath. A tick without the
  tracker's MCP wiped the list (`skip mcp_unavailable`) and the next restored it. A flap is not idle, so it resets
  idle pacing's count, as churn does (2026-10-12 F5). → M28.
- **F18. Review runs still mostly fail:** 8 of 11 ended `unknown` within seconds, driving 8 retry or give-up ticks.
  → M11.
- **F19. Backoff works when the loop is left alone.** Four ticks in a row (66 to 69) were idle by the loop's rule,
  and waits of 1800, 3600, and 7200 seconds appear. Most waits (117 of 157) were the 900-second base, because events
  kept arriving. → M21.
- **F20. Done-line failures cost no extra spend.** The 16 ticks that failed only on the old done line did their work;
  fixing the line (M28) makes them count as `ok`, so they raise no failing-loop notification and can be idle. It does
  not make them cheaper. The analysis counted their $7.41 as a saving; it is not one.
