# M40. The overseer per decision

DESIGN §40. Two stages, in order, each in its own PRs. Stage 1 needs nothing from M39, and goes ahead of it only at the
operator's word. Stage 2 needs M39 whole, the overseer
reading the journal alone and its open question on a `tracker` source settled (a run given one ticket can neither run
the query nor read a ticket no source observes), and is taken only if M39's re-measurement shows the state block's
size still dominating what the overseer spends: M34's cache hit needs ticks minutes apart, which M39 makes rarer, so
each remaining run may be cold.

**Stage 1, the tick starts every run.** What issue #454 needs to sandbox the overseer: `srt` ends a `setsid` process
when its sandbox ends (found in M26), so a run spawned from inside a sandboxed overseer would die with it, and would
inherit its sandbox.

- A dispatch, review, or chore run the overseer asks for, through a tool (M48) or its command, is recorded, not
  spawned: every guard of §8 step 1 checked at the ask, the refusal returned as today, the run's id returned, no slot
  leased. The recorded run counts as running: its ticket's one run, its capacity in every count, `reserved`'s too, and
  asks serialized through the record as they are through the spawn today.
- The tick spawns every recorded run once the overseer's run ends, with the harness's own dispatches, in §7's order,
  each under every guard again; a refusal then is recorded like any other. Then it leases and `_run` starts as before.
  `canopy _mcp`'s spawn through an intermediate (M48) goes, since no run is the server's descendant.
- A recorded run belongs to its tick: one not spawned by the tick's close, or by its process's death, is closed
  unstarted then or by the next tick's step 2, counting toward no limit, never spawned by a later tick. A dry run
  records and spawns none.
- Tests with the fakes: a dispatch through a tool and through its command spawned only after the fake overseer exits,
  in §7's order with the harness's, its `_run` no descendant of the overseer's process and outliving it; a review and
  a chore run the overseer starts, the same; a second dispatch for the ticket refused while one is recorded, one past
  `max_workers` refused, and `reserved` counting a recorded run; a recorded run whose ticket the operator stops, or
  whose notice changes, before the spawn refused at the spawn and recorded; a tick that dies after the ask, its record
  closed unstarted by the next tick with no attempt counted; and none recorded in a dry run.

**Stage 2, one run per subject.**

- The harness runs the overseer once for each subject left to it (M38's list): each ticket, each PR whose review is
  still its to start, and the due chores with a `when` in one run, last. A run's message is the block's shared part,
  rendered once a tick and the same in every run, then that subject alone, its capacity left after it; text on one
  ticket cannot steer a decision about another, and a cold run writes a few thousand tokens, not fifty. A decision,
  dispatch, attention item, or change about another subject is refused `decided`, through a tool and its command.
- Runs go one at a time in §7's order, which today the one overseer keeps, each told the capacity left after the
  harness's dispatches ranked above it and the runs recorded before it. With none left, a subject of new work only
  (`ready`, a `blocked` to stack) gets the harness's `wait`, naming capacity, and no run. No run sees the queue: the
  `tracker` source reads it (M39), and a ticket it finds is a subject like any other.
- §6 step 5's checks run once, before the first run. Each run owes its done line and its subject's duty. A run that
  fails, or leaves its duty undone, leaves its subject undecided, what it recorded standing, and the next run goes on;
  the tick closes `overseer_failed` naming each such subject. No subject gets a second run in a tick.
- A tick records each run with its subject, status, session, cost, and models; `canopy spend`, its `--json`, and the
  spend page count an overseer run's cost toward its ticket (M33), and `canopy decisions` lists a tick's decisions by
  run. `ticks.overseer_ran` becomes how many runs a tick made.
- TRUST_MODEL T1 (one subject's text per run, and nothing about another), T3 (at most one run per subject a tick, one
  at a time; a recorded run held from the ask to the spawn and closed with its tick), T4 (no run is the overseer's
  descendant), and T6; DESIGN §5, §6, §8, §11, §13, §15, and §27, with §40 cut to what is left.
- Tests with the fakes: through `scenario`, a tick with three tickets left runs three overseer runs in §7's order,
  each message holding its ticket alone, and the shared part the same in each, a snapshot; a run's tool call about
  another ticket refused `decided`; with one worker free, a `human_replied` ticket's run dispatches and a `ready`
  ticket after it is waited by the harness, naming capacity, with no run; due chores with a `when` in a run of their
  own, last; one ticket's run failing, and one leaving its duty undone, while the others' decisions and dispatches
  stand and spawn, the tick closing `overseer_failed` naming it; the checks made once for the tick; and each run's cost
  counted toward its ticket in `canopy spend --json`.

Accept: the tests above pass, and the design (§40) is folded into the sections it names. Live, once stage 1 is built:
over a day of `canopy loop`, every run the overseer asked for started after its run ended, none in its process tree,
and none lost. Live, once stage 2 is built, a day and a night of `canopy loop` against the real queue, a dated section
of MEASUREMENTS: every overseer run given one subject, no decision in any about another; the runs after a tick's first
reading its prefix from the cache; overseer spend per day below M39's re-measurement for the same queue; and no action
missed, checked against the derivation as in M36.

Status: in progress. Designed 2026-10-24 (DESIGN §40); stage 2's build waits on M39 and is still taken only if M39's
re-measurement shows the state block's size dominating what the overseer spends. The design settles what the sketch
left open: one run per subject, a PR whose review is left to the overseer among them, and the due chores with a `when`
in one run of their own; the prefix kept cacheable by a shared part rendered once a tick ahead of the subject; no run
sees the queue, since the `tracker` source reads it; the duties checked per run, a failed run leaving only its subject
undecided; each run's cost counted toward its ticket; and every run the overseer asks for recorded and spawned by the
tick, never from the overseer's process tree, which settles issue #454's point 2. Chosen conservatively, for the
operator to change: runs one at a time, every run on the overseer's one model, a subject of new work waited by the
harness with no run once capacity is out, the tick's spawns all after its last run, and a tick with a failed run closing
`overseer_failed`. Stage 1 needs neither M39 nor the measurement, so taking it ahead of them, which unblocks #454, is the
operator's call (recommended). Open for the operator: spawning a run's asks as soon as it ends (recommended: not until
a tick's length is measured to delay work); runs in parallel (recommended: not before a long queue is measured to hold
up the next tick); a model per run by phase (recommended: a private key from phase to model beside `runtime.models`,
with the ticket's override for the overseer applying to its runs); and whether a tick with a failed run closes `ok` with
an item on that subject (recommended: yes, once M38's attention list is held in code).
