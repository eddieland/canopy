# M38. The harness decides what needs no judgment

DESIGN §37. Needs M37, and for each row it takes, M36's measurement (or a later one) showing the derivation right on
it. D008's revisit: a rule moves into code only with that evidence, one row at a time. The overseer acts through
canopy's tools (§27), so `decided` and `reserved` refuse a tool call as they refuse its command.

- Before the overseer runs, the harness records the decisions that need no judgment, each marked as the harness's in
  `decisions`, so the corpus, `canopy decisions`, and the tick's page show who made it: `done` for a closed ticket and
  for `merged` (unless a `multi_repo` item is open on it), `skip` for a non-candidate the query returned; `wait` for
  `running`, `ci_running`, `needs_human`, a CI-only `resume` in cooldown, a failed latest run no human has answered,
  and `blocked` with no blocker to stack on; `resume` for `pushed_no_pr` and `conflicted`, with their fixed contexts;
  `resume` for `ci` on `ci_red`, naming the failed checks, only for a check whose run started while no notice (M35)
  was in force, and `wait` while its blocker's PR is red; `review run` for `review_pending`, the review query's PRs,
  and the operator's requests, with their waits and ends; `chore run` for a due chore with no `when`. A ticket is the
  harness's only when every row holding for it and its units is, and none is stale; one row of judgment leaves it
  whole to the overseer, so one `resume` still carries everything (§8). Plans' rows stay the overseer's.
- The evidence gate: rows are enabled in code one at a time, each by a PR citing the MEASUREMENTS section that shows
  the derivation right on it, every disagreement read and none the derivation's; no config switch. What the harness
  reads from its own journal alone needs no measurement. `ci_red`'s `resume` was the row the overseer overruled most,
  on facts outside it: a PR humans had shelved with labels, an outage, a stacked ticket's open blocker, a build still
  running (2026-10-15 F27). It moves only on a measurement with PR labels and every context observed; until then the
  harness takes only its cooldown's `wait`. A check that ran during a notice stays the overseer's even after the
  notice ends, since whether the notice explains the failure is judgment, which M35 keeps out of code.
- The priority order across both deciders, the overseer prompt's step 6 today, goes into §7: a requested review, a
  human waiting (`human_replied`, `changes_requested`, `review_findings`), `conflicted` and `ci_red`, `pushed_no_pr`,
  the loop's own and the query's reviews, then `ready`. The harness records its decisions before the overseer and
  makes its dispatches after, whatever the overseer's run ended as; the state block names them and the capacity they
  hold, and an overseer dispatch that would leave too little for the harness's that rank above it is refused
  `reserved`.
- The attention list from observations: `needs_reviewer`, `ready_to_merge`, `untrusted_review`, `attempt_limit`,
  `review_failed`, `review_limit`, `plan_review`, and `plan_changed` are the harness's, open while their cause holds in
  the journal, like the run reasons (§14), and kept while an observation is stale. No re-recording rule, which M28's
  prompt fix (the overseer's open items in its state block) works around and this removes, so an item cannot flap
  (2026-10-13 F17) or go because the overseer left it out on partial data. This is the fix for issue #219, an outage
  tick that closed `ok` and resolved items it could not read: no item hangs on the overseer recording it again, so
  nothing needs to tell a partial tick from a whole one. The overseer keeps the three that are judgment,
  `needs_author`, `multi_repo`, and `notice_rerun`: it records each once, naming what it is about, and the harness
  holds it until the cursor passes that item, a newer run of the held check is observed, or a human answers after it,
  or the ticket is done or stopped.
- The overseer's state block lists only the tickets left to it, each with the rows that hold: `ready`, `blocked` with
  a blocker to stack on, `changes_requested` and `review_findings`, `human_replied`, a row not enabled, a plan's rows,
  a check held for a notice, a stale or unobserved subject (M37), a ticket whose observations fit no row; and each due
  chore with a `when`. Of the rest it names only the harness's dispatches to come. Anything the overseer records about
  another ticket is refused `decided`, and the duties check (§6) owes decisions only for the tickets listed. A dispatch
  moves each cursor of its reasons to the newest item of that kind the block showed, short of the first it may not
  cover (M37's checks), so the overseer passes a cursor only to stop shorter; the harness moves cursors past what its
  decisions handle and what needs no handling.
- The prompt shrinks to the judgment: the procedure's holds and order, and the candidates, phase table, cursors, and
  attention list sections go (M37 retires mirroring); the reviews and chores sections keep only what is judgment.
  Its size in `.agents/sizes.toml` drops with it.
- TRUST_MODEL T1 (text on a ticket the harness decided reaches no model; the overseer cannot overrule the harness or
  drop an item it holds; the residual of a derivation's mistake starting a run), T3 (the harness's dispatches under
  every limit; `reserved`), T5 (who made each decision); DESIGN §6, §7, §8, §14, §19, §21, with §37 cut to what is
  left; D008 and D020 edited in place.
- Tests with the fakes: the harness's decisions over journals written by hand, one per row it takes, each marked as
  its own, and its dispatches' fixed contexts; a ticket with one row of judgment left whole to the overseer with the
  harness's reading; a row not enabled left to the overseer; `ci_red` with its check run during a notice left to the
  overseer after the notice ends, and in cooldown waited by the harness; `merged` with `multi_repo` open not marked
  done; the harness's dispatches made after the overseer, in order, after a failed overseer run too, and none in a dry
  run; `reserved` for a `ready` dispatch into the harness's capacity and none for a `human_replied` one; `decided` for
  a decision, dispatch, attention item, and ticket change on a ticket the harness decided, through both the tool and
  its command; each harness item kept across a `skipped` tick, an `overseer_failed` tick, and a stale observation, and
  gone when an observation shows its cause gone; each item the overseer keeps held until what ends it; a dispatch's
  default cursors and one passed shorter; the state block, a snapshot, listing only the tickets left with their rows
  and the dispatches to come; a fake overseer that handles only the listed tickets closes the tick `ok`.

Accept: the tests above pass, each enabled row cites its measurement, and the design (§37) is folded into the sections
it names. Live, once built, over a day: the overseer's decisions are only on the tickets listed to it; the attention
list changes only when an observation or the operator did; `loop waits` reports no churn; a median tick at half of
M37's; and no action missed, checked against the derivation as in M36.

Status: not started. Designed 2026-10-21 (DESIGN §37); the build waits on M37, and each row on its measurement. Open
for the operator: the bar a row clears in the measurement (recommended: at least three distinct situations, each
disagreement the overseer's mistake), and whether `ci_red`'s `resume` needs a shared list of PR labels that hold a PR
(recommended: yes).
