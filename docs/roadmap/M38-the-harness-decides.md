# M38. The harness decides what needs no judgment

Needs M37. Sketch only; the design comes first. D008's revisit, taken for the rows of §7 that measurement (M36)
showed the derivation getting right: a rule moves into code only with that evidence.

- Before the overseer runs, the harness records the decisions that need no judgment, as it records `awaiting_reply`
  today: `wait` for `running`, `ci_running`, `needs_human`, a cooldown, a failed latest run, and `blocked` with no
  stackable blocker; `done` for a closed ticket and for `merged`; `dispatch resume` for `pushed_no_pr` and `conflicted`,
  with their fixed contexts; `dispatch resume --reason ci` for `ci_red`, naming the failed checks (after `triage-ci`,
  with M25), only for a check whose run started while no notice (M35) was in force: for one that ran during a notice,
  the row stays the overseer's, even after the notice ends, since whether the notice explains the failure is judgment,
  which M35 keeps out of code; `review run` for `review_pending` and for `review.query`'s PRs. Each is a `decisions` row
  with `by = harness`, so the corpus, `canopy decisions`, and the tick's page show every decision and who made it.
  `ci_red` was the row the overseer overruled most, on facts outside it: a PR humans had shelved with labels, an outage,
  a stacked ticket's open blocker, a build still running (2026-10-15 F27). Its `resume` moves only if M36's day, with PR
  labels observed, shows the derivation right; until then it stays the overseer's.
- The priority order across both deciders is the overseer prompt's step 4 today (a human waiting, then conflicts and
  red CI, then a pushed branch with no PR, then `ready`) and nowhere in the design: it goes into §7, and the
  harness keeps it. The harness records its decisions before the overseer and makes its dispatches after it; the
  state block names them and the capacity they take, so the overseer dispatches its human-waiting tickets first and
  its `ready` tickets only into what remains, and a `ready` dispatch past that is refused `reserved`.
- The attention list from observations: `green_unreviewed`, `approved`, `untrusted_review`, `attempt_limit`,
  `review_failed`, and `review_limit` are the harness's, open while their
  cause holds in the journal, like the run reasons (§14). No re-recording rule, which M28's prompt fix (the
  overseer's open items in its state block) works around and this removes, so an item cannot flap (2026-10-13 F17)
  or go because the overseer left it out on partial data. This is the fix for issue #219, an outage tick that closed
  `ok` and resolved items it could not read: no item hangs on the overseer recording it again, so nothing in `tick.py`
  needs to tell a partial tick from a whole one, and a tick that did work during an outage keeps it. The
  overseer keeps the two that are judgment, `needs_author` and
  `multi_repo`: it records each once, naming the item it is about, and the harness holds it until the cursor passes
  that item or the cause is gone.
- The overseer's state block lists only the tickets left to it, each with why: `ready` (choose the repository, slug,
  title, and context), `blocked` with a stackable blocker, `changes_requested` and `review_findings` (classify),
  `human_replied` (what the reply asks), a due chore with a `when`, and a ticket whose observations fit no row. A
  decision about any other ticket is refused `decided`. A dispatch for new items advances the cursors to the items
  the block showed, so the overseer passes `--cursor` only to leave feedback alone.
- The prompt shrinks to the judgment sections: candidates, the phase table, cursors, mirroring, and the attention
  list section go.
- Tests with the fakes: the harness's decisions over journals written by hand, one per row; a decision on a ticket
  not left to the overseer refused; a fake overseer that handles only the listed tickets closes the tick `ok`.

Accept: written with the design, before work starts. Live, once built, over a day: the overseer's decisions are only
on the tickets listed to it; the attention list changes only when an observation or the operator did; `loop waits`
reports no churn; a median tick at half of M37's.

Status: not started.
