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
