# The overseer per decision

Part of the canopy design, normative like all of it: the overseer run once for each subject left to its judgment, and
the runs it asks for, which the tick starts. Sections are numbered across the whole design; the [README](README.md) has
the map. Previous: [A tick without the overseer](WITHOUT_THE_OVERSEER.md). Next: [Where a running agent
stands](PROGRESS.md).

## 40. The overseer per decision

Built in part (ROADMAP M40): the tick starts every run (below), and §6, §8, §27, and TRUST_MODEL T3 and T4 say so. The
runs per subject are designed, not built; until they are, §5, §6, §8, §11, §13, §15, and TRUST_MODEL
describe canopy as it is, this section says what changes, and the PR that finishes it changes those sections and cuts
this one to what is left.

Once the harness decides what needs no judgment (§37) and the overseer runs only when something is left (§6), its
runs on a quiet queue come hours apart, past the provider's cache of its prompt (§6 step 4), and each is handed every
ticket left. One run per ticket makes a cold run pay for the prompt and one ticket, not the queue, and keeps text on one
ticket out of the context of every decision about another (TRUST_MODEL T1).

### One run per subject

The harness runs the overseer once for each subject left to it (§37): each ticket, each PR whose review is still its to
start (§21), and the due chores with a `when`, together, since none needs a ticket. A run's message is the state block
cut to its subject: the part every run of the tick shares, then that subject's observations, items, and messages, and
nothing of any other, its key included. A decision, dispatch, attention item, or change it records about anything but
its subject is refused `decided`, as §37 refuses one about a ticket not listed to the overseer, through a tool and its
command alike. Rejected: one session given the subjects one message at a time, whose context keeps every earlier
ticket's text; and two standing overseers split by job, which buys only the cheaper model's price, since finding new
work was a fraction of a percent of overseer spend (MEASUREMENTS 2026-10-15).

- **The prefix stays cacheable.** The definition (§13) and the shared part come first, rendered once a tick and the
  same byte for byte in each of its runs; the subject, and the capacity it may use, come after. A tick's runs go one
  after another, so the first writes the cache and the rest read it, and a run cold after a long gap writes the prompt
  and one subject.
- **No run sees the queue.** The `tracker` source reads the query (§7), and a ticket it finds is a subject like any
  other, given its own run or the harness's `skip`. This rests on an overseer that reads the journal alone, and on the
  `tracker` source config requires (§30): a run given one ticket can neither run a query nor read a ticket no source
  observes.
- **One at a time, in §7's order.** Runs go by the first row each subject holds, the chores' last. Each is told the
  capacity left after the harness's dispatches ranked above it (§37) and the runs those before it recorded. Once none
  is left, a subject whose rows are all new work (`ready`, a `blocked` to stack) gets the harness's `wait`, naming
  capacity, and no run: a slug and context for a run that cannot start buy nothing. The rest still run, since their
  answer may be attention rather than a run. Chosen conservatively, for the operator to change: one at a time, since
  each run's capacity rests on those before it and the cache on the first.
- **One model.** Every run takes the overseer's model (§13), whatever its subject. Chosen conservatively, for the
  operator to change (Open).

### What each run owes

§6 step 5's checks, the disk, the tools' server, and the model, are made once, before the first run, and one that fails
closes the tick as today with no run. Each run then owes its done line and its subject's duty (§6): a decision for its
ticket, a review verb for its PR, and from the chores' run a run, wait, or refusal for each due chore. A run that fails,
or leaves its duty undone, leaves its subject undecided: what it recorded stands, as an undone duty's dispatches do
(§15), and the next run goes on, so one subject's failing run, whatever its text, holds up no other's. The tick closes
`overseer_failed`, naming each subject whose run failed, and the next tick gives it a run again. No subject gets more
than one run a tick.

A tick records each run: the subject it was given, how it ended, its session, what it cost, and the models that served
(§13); whether it ran the overseer (§6 step 5) becomes how many runs it made. A run's cost counts toward its ticket, so
`canopy spend` and the spend page read what the overseer spent on a ticket from that ticket's runs (§11), not from a
share of each tick that decided it.

### The tick starts every run

A run the overseer asks for, a dispatch, a review, or a chore's, is recorded, never spawned from the overseer's process
tree: the tick spawns it once the overseer's runs have ended, with the harness's own (§37), in §7's order. This holds
whether a tick makes one overseer run or many, so it can be built first.

- At the ask, every guard of §8 step 1 is checked, and a refusal goes back to the run as it does today. The recorded
  run counts as running: it is its ticket's one run and holds its capacity in every guard's count, `reserved`'s among
  them. Asks are serialized through the record as spawns are, so two cannot both pass a limit. It leases no slot (§9).
  The tool returns the recorded run's id; the run it starts as has an id of its own.
- At the spawn the guards are checked again, as the harness's own are, and a refusal is recorded like any other. Then
  it leases and `_run` starts (§8 step 4); cursors still move only once the worker starts. Its decision is recorded as
  it starts, or its refusal then, so a tick's decisions name the run each dispatch started. Within a rank of §7's
  order the harness's go first, as it planned them before the overseer ran, and every chore goes after every run, the
  overseer's before the harness's.
- A recorded run belongs to its tick. One the tick did not spawn, because it ended early or its process died, is
  closed unstarted when the tick closes or when step 2 closes the tick abandoned, and counts toward no limit; no later
  tick spawns it, since that tick decides again from what it reads. A dry run records and spawns none (D036).

Why: with no run in the overseer's process tree, nothing it asked for dies when it ends, whether the runtime kills its
server's descendants (§27) or a sandbox around the overseer ends what it holds, and no run, its setup, or the harness's
git and treehouse calls inherit that sandbox. So `overseer_cmd` can be wrapped apart from its runs (§24). Rejected:
spawning through an intermediate, as §27's server did, which escapes the runtime but not a sandbox.

### Trust model changes, when built

- T1: a run's message holds one subject's text and nothing of any other, and its tools refuse anything about another
  subject, so text on one ticket cannot steer a decision about another, nor its failing run hold up another's.
  Residual: it still steers its own ticket's run, bounded as any overseer decision is; the standing instructions and
  the notice, in the shared part, reach every run, as they do today.
- T3: a tick makes at most one run per subject, each with the overseer's timeout, one at a time. The recorded run's
  bounds are T3's already.
- T6: a steered run holds one subject's text, so what it records can carry nothing of another ticket's.

### Open

- Spawning a run's asks as soon as that run ends, not after the last. Recommended: not until a tick's length is
  measured to delay work, since one spawn point keeps §7's order whole.
- Runs in parallel. Recommended: not before a queue is measured long enough that a tick's runs hold up the next tick.
- A model per run, by the subject's rows: the strongest for `ready`, review feedback, and a reply, a cheaper one for the
  rest. Recommended: a private key from phase to model beside `runtime.models`, the operator's alone (T7), with the
  ticket's override for the overseer (§13) applying to that ticket's runs, so a model tried on a ticket covers its
  overseer too.
- Whether a tick with a failed run closes `ok`, with an item on that subject. Recommended: yes, once §37's attention
  list is held in code, so one subject's failing run does not hold the list for the rest.
