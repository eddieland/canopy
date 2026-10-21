# The harness decides

Part of the canopy design, normative like all of it: the decisions the harness records in code before the overseer
runs, and what it leaves to the overseer's judgment. Sections are numbered across the whole design; the
[README](README.md) has the map. Previous: [One-off tasks](TASKS.md).

## 37. The harness decides what needs no judgment

Designed, not built (ROADMAP M38). It waits on §35, and each row on a measurement (below). Until it is built, §6, §7,
§8, §14, §19, §21, and TRUST_MODEL describe canopy as it is; this section says what changes, and the PR that builds it
changes those sections and cuts this one to what is left.

Once the overseer reads the journal (§35), most of what it decides follows from the observations alone: applied by
hand, §7's rows that are facts agreed with it on all but six of 943 decisions, and an overseer given only the tickets
that need judgment would cost a third less than one given every ticket (MEASUREMENTS 2026-10-15). So the harness
records those decisions itself, before the overseer runs, and the overseer sees only what is left: D008's revisit, one
row at a time.

### What the harness decides

Each is recorded as the harness's decision, so `canopy decisions`, the corpus, and a tick's page say who made it. Its
dispatches carry fixed contexts, never model-written text, and pass §8's guards as the overseer's do.

- `done` for a closed ticket, and for `merged` unless a `multi_repo` item is open on it (below); `skip` for a ticket the
  query returned that is not a candidate (§35).
- `wait` for `running`, `ci_running`, `needs_human`, a `resume` for CI alone in its cooldown (§8), a failed latest run
  no human has answered since (§14), and `blocked` with no blocker to stack on (§10) and none whose PR closed unmerged.
- `resume` for `pushed_no_pr` and for `conflicted`, each with its fixed context.
- `resume` for `ci` on `ci_red`, naming the failed checks, only for a check whose run started while no notice was in
  force; `wait` while the unit is stacked on a blocker whose own PR is red. A check that ran during a notice stays the
  overseer's even after the notice ends: whether the notice explains it is judgment, which §8 keeps out of code.
- `review run` for `review_pending`, and for the review query's PRs and the operator's requests at an unreviewed head;
  `review wait` for a draft or pending checks; a request's end when its PR merged or closed, or is in no repository of
  the workspace (§21).
- `chore run` for a due chore with no `when` (§19).

A ticket is the harness's only when every row that holds for it and for each of its units is one the harness decides,
and none rests on a stale observation. One row of judgment anywhere leaves the whole ticket to the overseer, with the
harness's reading of the rest, so one `resume` still carries everything a unit needs (§8). A ticket whose next run a
plan gates (§25, §32) is left to it too. A subject's phase is the first row of §7 that holds, so the table's order
becomes normative, and the harness records it for the tickets it decides.

### The evidence gate

A row moves into code only when a measurement shows the derivation (§30) right on it: a day of the loop in shadow,
recorded in MEASUREMENTS, each disagreement on the row read and attributed, and none the derivation's. Rows are enabled
one at a time, in code, each by a PR citing its measurement; a row not enabled stays the overseer's, listed to it with
the derivation's reading. What the harness reads from its own journal alone (a run's status, attempt counts, a review's
outcome, a plan's status) needs no measurement. Rejected: a switch per row in config, which would keep the prompt's
procedure for every row in case one is off, the procedure this section removes.

`ci_red`'s `resume` is the row the overseer overruled most, on facts outside the table: a PR humans had shelved with
labels, an outage, a stacked ticket's open blocker, a build still running (MEASUREMENTS 2026-10-15). It moves only if a
measurement with PR labels and every context observed shows the derivation right (Open); until then only its cooldown's
`wait` is the harness's.

### Order and capacity

§7 gains the order dispatches take across tickets, whoever decides them, which only the prompt states today: a review
the operator requested; a human waiting (`human_replied`, `changes_requested`, `review_findings`); `conflicted` and
`ci_red`; `pushed_no_pr`; the loop's own and the query's reviews; then `ready`, a blocker before what it blocks. Work in
flight comes before new work, and a person waiting before a machine. Tasks start first, within their share (§36).

The harness records its decisions before the overseer runs and makes its dispatches after, in that order, whatever the
overseer's run ended as; a tick that closes before running it (§6 step 5) starts none, and a dry run none (D036). The
state block names them and the capacity they hold. A dispatch of the overseer's that would leave too little for the
harness's that rank above it is refused `reserved`: a human waiting goes ahead of a conflict, and `ready` gets what is
left. Rejected: the harness dispatching first and reserving for the overseer, whose dispatches it cannot foresee.

### The attention list, held in code

Every item the overseer records today but three is the harness's, open while its cause holds in the journal, as the run
reasons are (§14): `needs_reviewer`, `ready_to_merge`, `untrusted_review`, `attempt_limit`, `review_failed`,
`review_limit`, `plan_review`, and `plan_changed`. An item goes only when an observation or the operator shows its cause
gone; a stale observation keeps it. No item hangs on a tick recording it again, so the list stops being the latest `ok`
tick's (D020): an item cannot flap (MEASUREMENTS 2026-10-13) or go because a tick could not read its cause, and nothing
needs to tell a partial tick from a whole one.

The overseer keeps the three that are judgment: `needs_author`, `multi_repo`, and `notice_rerun` (§8). It records each
once, naming what it is about, and the harness holds it until that is handled (the cursor passes the item it names, a
newer run of the held check is observed, or a human answers after it), or the ticket is done or stopped. The block
lists them with what each names, so none is recorded twice.

### What the overseer is left

The state block lists only the tickets left to the overseer, each with the rows that hold: `ready` (a repository, slug,
title, and context to choose), `blocked` with a blocker to stack on, `changes_requested` and `review_findings` (to
classify), `human_replied` (what the reply asks), a row not enabled, a plan's rows, a check held for a notice, a stale
or unobserved subject (§35), and a ticket whose observations fit no row; and each due chore with a `when`. Of the rest
it names only the harness's dispatches to come. Anything the overseer records about another ticket, a decision,
dispatch, attention item, or change, is refused `decided`, and its duties (§6) are owed only for what it was listed.

A dispatch moves each cursor of its reasons, once the worker starts, to the newest item of that kind the block showed,
short of the first it may not cover (§35); the overseer passes a cursor only to stop shorter. The harness moves the
cursors past what its own decisions handle and what needs no handling: a worker's comment, a reply the operator sent.

The prompt keeps the judgment: repositories, slugs, titles, and contexts; classifying feedback; what a reply asks;
stacking; a chore's `when`; a notice's hold; stale and unobserved subjects. Its holds, order, candidates, phase table,
cursors, and attention list go.

### Trust model changes, when built

- T1: text on a ticket the harness decided reaches no model in the tick, and the harness's dispatches carry no
  model-written context. A steered overseer cannot overrule the harness (`decided`) or drop an item it holds. Residual:
  a harness `resume` follows an observation without judgment, so a derivation's mistake starts a run, which the
  evidence gate and T3's limits bound.
- T3: the harness's dispatches count against every limit, cooldown, and capacity; `reserved` keeps new work behind work
  in flight. T5: each decision says whether the harness or the overseer made it.
- D008 and D020 are edited in place: rows move into code on a measurement, and the attention list is held in code.

### Open

- The bar a row clears in the measurement. Recommended: at least three distinct situations, each disagreement the
  overseer's mistake; a row seen less often waits for a re-measurement that sees it.
- Whether `ci_red`'s `resume` also needs a list of PR labels that hold a PR, for the shelved PR the measurement found.
  Recommended: yes, shared, since such a label only holds and authorizes nothing.
