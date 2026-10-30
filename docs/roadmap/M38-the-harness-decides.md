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

Status: in progress. Designed 2026-10-21 (DESIGN §37); each row waits on its measurement. Started 2026-10-22 ahead of
M37's end, at the operator's word, with the rows that need none. Built (2026-10-22): the first bullet's machinery and
the fourth's `decided`. Before the overseer runs, the harness takes a ticket whole when every row the derivation finds
for it and its units is enabled, none stale, and records its decision marked as its own (`decisions.decider`, which
`canopy decisions` and the web UI's API show; the harness's attention items are marked too, older rows unmarked), with
the phase that row names (`loop/harness.py`); the state block names each such ticket in `harness` and leaves it out of
`tickets` and `observations`; the duties check owes nothing for one; and a decision, dispatch, attention item, or
`ticket set` about one is refused `decided` through the tool and its command; D008 is edited in place. Rows enabled,
read from the journal alone: `wait` for `running`, and for `needs_human` on a private ticket (its latest run `blocked`,
no operator message since); a public ticket's `needs_human` rests on the tracker's label, so it waits on a measurement.
Chosen conservatively, for the operator to change: a ticket that is not a fresh, open candidate stays the overseer's;
the cooldown's and a failed run's `wait` are not enabled, since each rests on rows the derivation reads from connectors
(`ci_red`, and the rows a failed run leaves);
review verbs and `mirror` are not refused `decided`, since an operator's review request on a ticket the harness took is
still the overseer's to run, and a ticket the harness took has its comments mirrored once the overseer is given it
again; and the tick's derivation comparison leaves out a ticket the harness decided. Built (2026-10-22, stage 2): the
third bullet. The priority order is in §7. Before the overseer the harness plans its dispatches, read from the journal
wherever they are needed (the tick's derivation, the attention list, the chores' runs; `loop/harness_dispatches.py`),
and the state block names them in `dispatches_to_come` with the workers they hold, leaving their tickets out. After the
overseer's run, whatever it ended as, it makes them, runs in §7's order and then chores, each under every guard and
recorded as its own; a tick halted before the overseer starts none, and a dry run checks the guards and starts none. An
overseer's dispatch that would leave fewer workers free than the harness's runs ranked above it hold is refused
`reserved`, through the tool and its command. Row enabled: `chore run` for a due chore with no `when`, read from the
config and the journal. No ticket's dispatch row is, since each rests on an observation: `ROWS` is empty, wired, and
tested with rows enabled by hand. Chosen conservatively, for the operator to change: a chore with no `when` is the
harness's whether due or not, so `chores` lists only those with one, the overseer's `chore run` and `chore wait` about
one are refused `decided`, and it runs with no context; the harness takes a ticket's run only when exactly one of its
units holds rows, every one enabled, and its own row none, and not when a feedback plan gates the `resume` or is
current; a `feedback-plan` ranks with a human waiting and a `retarget` with a repair, so neither is held behind a
conflict; `reserved` holds `canopy dispatch` only, not a review the overseer starts, until a review row is the
harness's; and the harness moves no cursor, so a row enabled later brings its cursors with it. Built (2026-10-23): the
fifth bullet's hold, which a tick without the overseer (M39) needs, narrowed on 2026-10-24 to the overseer's items it
does not keep (below) and a guard's. An item the overseer recorded stands through every `ok` tick that did not give the
overseer its subject, a ticket it recorded no decision about there, such as one the harness decided, and goes the first
tick that gives it the subject and leaves it out, or once its ticket is done or stopped (`attention.current`); the
harness's own items still stand only while the latest `ok` tick records them. So a ticket with an item the overseer
holds is the harness's for a `wait`, the item standing, and the block lists the item only once the overseer is given the
ticket again; D020 is edited in place. Chosen conservatively, for the operator to change: the harness's run is still
held off a ticket with an item the overseer holds, since what the item says may be why not to run; an item about a PR or
the workspace stands only through a tick that ran no overseer; and done and stopped are the only ends decided in code.
Built (2026-10-24): the fifth bullet's first half. None of the eight was raised by code before; guards recorded
`attempt_limit` and `review_limit` on refusing the overseer, and still do. Each tick, after the derivation and before
the overseer, the harness raises the eight from their causes, marked as its own (`loop/harness_items.py`):
`needs_reviewer` and `ready_to_merge` for a unit whose first row is `green_unreviewed` or `approved` (`review_limit`
with it at its review limit), `untrusted_review` while that row holds, `attempt_limit` for the run a ticket's rows want
past its limit, `review_failed` while a PR's latest review run in the state block's window failed, and `plan_review` and
`plan_changed` from the plans' rows and files. One resting on an observation is recorded again, as the latest `ok` tick
listed it, while that observation is stale or the derivation raised, and goes once a fresh read shows its cause gone or
the journal shows a limit lifted; a ticket seen closed or unlabeled, done, or stopped holds none. So an outage tick that
closes `ok` resolves nothing (#219). The overseer's attention tool and its command refuse the eight (`raised`); the
prompt records `wait` where a row names one, and its re-recording rule covers only its own items; the comparison takes a
`wait` beside the harness's item as agreeing; and garbage collection keeps the overseer's older rows of the eight as
corpus. The derivation now reads untrusted `canopy:review` findings as `untrusted_review`, as the prompt's table does.
D020 and TRUST_MODEL T1 are edited. Chosen conservatively, for the operator to change: a public ticket whose own row is
stale, such as every one where no `tracker` source runs, still gets its units' items from their fresh PRs, and keeps its
plan's and a branchless unit's `attempt_limit`; an `attempt_limit` is raised for each unit the rows want resumed, every
unit of a `ready` ticket (or the workspace's one repository), and every unit on `human_replied`, never for `blocked` or
a running ticket; a PR the review query found gets its `review_limit` only from the guard, since no source reads its
head; a guard's item is held as the overseer's is. Built (2026-10-24): the fifth bullet's second half. The overseer
records `needs_author`, `multi_repo`, and `notice_rerun` once, marked `kept` and naming in `item` the journal number of
what it is about (`decisions.kept` and `item`, migration 0104), and the harness holds each from the `ok` tick that
recorded it, whatever later ticks record, until what it names ends it (`core/kept_items.py`): the ticket's comment
cursor, or the review cursor of the unit whose PR it is on, passes the item a `needs_author` names; the operator answers
on the ticket after a `needs_author` or a `multi_repo`; a newer run of the check a `notice_rerun` names is observed; or
the ticket is done or stopped. The tool and its command refuse one that names nothing that could end it (`unnamed`): one
about no ticket, a `notice_rerun` with no check run, an item not of its ticket or of one of its units' PRs, and `item`
on any other reason. The block lists each held record `kept` with its `item`, the prompt records each once and `wait`
beside it, and a ticket with a `merged` row and a `multi_repo` open is left to the overseer. D020, §14, §37, and
TRUST_MODEL T1 are edited. Chosen conservatively, for the operator to change: the overseer ends none but by moving a
cursor past what a `needs_author` names; only the operator's message, through any channel, is a human's answer, not a
reply on the tracker or a comment on an artifact, since the list is read without the config that says who may reply; a
`notice_rerun` ends only on a newer run, not on an answer, and stays too once the journal no longer holds its check run;
a dry run's record counts only while its tick is the latest `ok` one (D036); an item the overseer recorded every tick
before is not listed to it, so it records one once if its cause still holds, and no sink hears it ended, though its age
starts again; `flaky_rerun` stays recorded every tick (§23, Open); and the derivation comparison does not yet take a
`wait` beside a held item as agreeing. Built (2026-10-25): the sixth bullet's cursors past what needs no handling. Each
live tick, after the connectors and before the derivation, the harness moves a ticket's `comment` cursor and each unit's
`review` cursor across the items directly after it that carry the workers' marks or that the operator sent through
canopy (and an empty review holding only such comments, as GitHub wraps a reply), stopping at the first item that is
anything else, never moving back; each move is its decision `cursor`, marked as its own, which decides nothing about the
ticket (`loop/harness_cursors.py`); a dry run moves none. Chosen conservatively, for the operator to change: only a
subject the block shows fresh moves, a fresh candidate's comments and a fresh PR's reviews, not a stale or unobserved
one's; a ticket's draft the operator sent is a tracker comment in their name, left to the overseer; and a canopy review
run, with findings or none, stops the `review` cursor. Built (2026-10-25): the sixth bullet's default cursors. A
`resume` moves each cursor of its reasons it leaves out, once its worker starts, to the newest item of that kind the
state block showed (the newest comment shown, operator message the tick had read, failed check at the head, review item
shown, or the end of the review run it names), short of the first it may not cover: one past the block's bound, or an
untrusted reviewer's feedback with no go-ahead it carries (`claims.default_cursors`). A cursor passed is kept, and M37's
checks bound it as before. A `resume` for `reply` is now checked to cover an authorized reply, as one for `review` is,
rather than to name it, so a default at a newer comment by someone else still passes; TRUST_MODEL T1 is edited. The
prompt names a `resume`'s cursors only to stop shorter. Chosen conservatively, for the operator to change: no default on
a private ticket, for a joint `resume`, or for another kind (an `implement` carrying a message still names its cursor);
no `comment` or `message` default unless the ticket is observed a fresh candidate, and no `ci` or `review` default
unless its PR is observed fresh; a message sent after the tick read the journal is not passed; no `ci` default while a
notice is in force or lately ended, since whether it holds a check is judgment; and a `review` cursor stops short of
untrusted feedback with feedback plans on too. Built (2026-10-29): the sixth bullet's cursors past what the harness's
own decisions handle. A `resume` the harness makes is checked against the claims (§35), as the overseer's is at its
spawn, and moves the cursors of its reasons as the overseer's does, to its default cursors, once its worker starts and
never back; each move is its decision `cursor`, marked as its own and naming the run that handles what it passes
(`harness_cursors.handled`); a refused run moves none, and a dry run moves none and names them in its decision (D036).
So stage 2's harness that moved no cursor is gone. No row enabled moves one, since `ROWS` is empty: it is tested with
`ci_red`'s and `changes_requested`'s rows enabled by hand. Chosen conservatively, for the operator to change: the
harness's other decisions move no cursor, since a `wait` leaves what came meanwhile new for the run after it; and its
`resume` moves only the defaults the overseer's would, so none on a private ticket, none for `ci` while a notice is in
force or lately ended, and none past untrusted feedback with no go-ahead. Left: every other row, each on its
measurement; the prompt cut to the judgment; and the design folded into the sections it names.
Open for the operator: the bar a row clears in the measurement (recommended: at least three distinct situations, each
disagreement the overseer's mistake), and whether `ci_red`'s `resume` needs a shared list of PR labels that hold a PR
(recommended: yes).
