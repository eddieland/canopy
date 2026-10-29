# A tick without the overseer

Part of the canopy design, normative like all of it: the tick that runs no overseer when the harness has left it
nothing to judge, and the loop that ticks when the connectors see something change. Sections are numbered across the
whole design; the [README](README.md) has the map. Previous: [Artifacts](ARTIFACTS.md). Next: [The overseer per
decision](OVERSEER_PER_DECISION.md).

## 39. A tick without the overseer

Being built (ROADMAP M39). It waits on §37, and on the overnight run that tests idle pacing (SCENARIOS S27). Built, in
§6, §11, and TRUST_MODEL T3: "When the tick runs no overseer", the query no source read and the reviews the overseer
starts still left to it until they are the harness's; and the poll's comparison and a failed poll's wake, the latest
tick read as it ended, so what it started wakes nothing. Built too, in TRUST_MODEL T1: "What the overseer reads", but
for every server but canopy's denied: the harness's `wait` on a ticket the `tracker` or `vcs` source left stale, or
with a PR no source reads, no query owed, the reviews' PRs read for the overseer, no tick-wide skip, and the `tracker`
source config requires (§30). The rest is designed, not built: until it is, §5, §6, §11, §13, §15, §30, §37, and
TRUST_MODEL describe canopy as it is; this section says what changes, and the PR that finishes it changes those
sections and cuts this one to what is left.

Once the harness decides what needs no judgment (§37), most ticks leave the overseer nothing: overnight, while PRs wait
on a human, after a run ends with nothing to classify. The connectors' polls (§6) already read the world every few
minutes, so the loop can tick when they see a change rather than when a timer runs out. So the overseer runs only when
the journal leaves it something to judge, and an event in the world is acted on within a poll.

### When the tick runs no overseer

A tick does §6's steps 1 to 3 whole, as today: reconcile, the operator's tasks (§36), the sources, the harness's
items. The harness then records its decisions (§37). When they leave the overseer nothing, no ticket and no due chore
with a `when`, the tick makes the harness's dispatches and closes `ok` with the attention list as it stands, without
running it. A tick the operator asks for is no different: the overseer would be handed an empty block.

- The disk check still holds the harness's dispatches, which fill a disk as the overseer's do. The check that
  `canopy` runs is the overseer's and is skipped with it, and nothing is owed: the duties (§6) are owed only for what
  the overseer was listed (§37).
- The attention list is §37's: the harness's items open and close with their causes on every tick, this one too, and
  the overseer's stand until what ends them. That is why this waits on §37: with the list the latest `ok` tick's
  (§14), a tick that closed `ok` without the overseer would clear every item the overseer records.
- Each tick records whether it ran the overseer (§11). One that did not costs nothing, and `canopy spend` and the web
  UI's spend page count it at nothing, never among the runs that reported no cost. They split ticks by whether the
  overseer ran, beside what woke them, so what an idle tick costs is the overseer's runs that bought nothing.

### What the overseer reads, and what it may call

The overseer reads the journal and nothing else. Its definition loses the tracker's and GitHub's MCP servers and the
provider skill in its body (§13), and denies every MCP server but canopy's, whatever the operator's runtime config
grants: it has canopy's tools (§27), or its `canopy` commands until those reach it, and nothing else.

- A stale or unobserved subject (§30) gets the harness's `wait`, naming what is old or that no source covers it,
  instead of a live read, and leaves §37's list of what the overseer is left. A stale one's source has raised
  `connector_failed` (§30), and the ticket moves again once a read is whole; an unobserved one is no outage, and the
  wait says so. A dispatch resting on a stale one is still refused `stale` (§7).
- The tracker query is read by the `tracker` source alone, on its polls as M36 built them, and the harness records the
  latest whole read when §7 says the query is due, so no tick owes `canopy queried`. A query the source failed to read
  is `connector_failed`, and a ticket it would have found waits for the read that finds it.
- With nothing to read, the overseer has no outage to skip a tick over: its tick-wide `skip` and §15's case for an MCP
  server down go. A source down is `connector_failed`, and what it left stale waits.
- An overseer that cannot read a ticket can do nothing with one no source observes, so config requires a `tracker`
  source (§30).

### Ticking when the observations change

Between ticks the loop polls every source every `connect.every_minutes`, as it does (§6). After a poll that read every
source whole, the harness works out what a tick would now record and list, records nothing, and ends the wait when it
differs from the latest tick: a decision that tick did not record, or something it did not list to the overseer, a
ticket, a row on one, an item past a cursor (§7), or a due chore. They are compared by what is decided and listed,
never by wording, so a poll that only reads again what the latest tick saw wakes nothing, and a ticket the overseer
waited on wakes nothing until something new is on it; an edit to an item already handled is not new, and the next
run sees its text. A gate coming due, a run ending, and the operator's acts end the wait as today, and
`loop.min_gap_minutes` holds every wake. The tick records the poll as what woke it (§11). An event
in the world is then acted on within a poll, or the minimum gap after the latest tick if that is later, not up to
`loop.idle_max_minutes` later: the trade §6 states is lifted.
Rejected: a tick on every poll, which writes a tick's rows every few minutes to learn what one comparison answers.

Idle pacing paces only the overseer's runs. A ticket the overseer waited on stays listed to it while its row holds
(§37), so the polls wake nothing for it, and the tick the timer brings runs the overseer on it again: the timer is the
overseer's second look at what it waited on, since the polls see the rest. The wait lengthens after each idle tick
that ran the overseer, as today, and a tick that ran none leaves the count as it was, having cost nothing.

A poll whose source fails, or reads less than it was asked, ends the wait once, so a tick runs the sources again at
once and raises `connector_failed` if they still fail (§30); a flake that the tick's read clears raises nothing. Until
a run reads every source whole, the polls go on but wake nothing, since what they would compare may rest on what was
not read, and the loop ticks on today's pacing. The poll that reads every source whole again ends the wait, so the
tick that resolves the item comes within a poll.

Runs that come rarely come cold: the provider's cache that holds the overseer's prompt (§6 step 4) lasts minutes, and
a quiet queue now runs the overseer hours apart. A run per subject, each paying for one ticket when cold, is §40.

### If the derivation is not trusted

Should §30's measurement leave the derivation untrusted, so §37 takes no row, the gate can be taken from the
observations alone, without the overseer deciding from them or the harness deciding (§37): the loop ticks only when an
observation changed since the last tick, a gate came due, a run ended, or the operator acted, with
`loop.idle_max_minutes` as its backstop. Every tick still runs the overseer, with its MCP servers: this buys the
latency, not the ticks with nothing to judge nor the trust change. Rejected, either way: a probe program that
fingerprints the world, a second reader of what the sources observe.

### Trust model changes, when built

- T1: the overseer is steered only by text the journal holds, bounded and labeled by source in code, and calls no
  tracker or VCS tool at all: §30's narrowing by prompt becomes its definition. Residual: what a connector printed
  (§30). Workers, planners, and reviewers still read the world live, as before.
- T3: an early tick is held by `loop.min_gap_minutes` as every wake is, and a poll that changes nothing wakes nothing,
  so the polls cannot spin the loop. A tick that runs no overseer spends nothing, and a poll costs what its sources
  cost.
- T6: the overseer reaches no server but canopy's.

### Open

- Whether `runtime.allow_bash`'s overseer entry, which lets it run commands the operator names, such as a
  tracker's CLI while its MCP server is down, goes with the MCP servers. Recommended: it goes, that entry with it, since
  an overseer that calls no tracker or VCS tool has nothing left to run; the workers' entries stay.
