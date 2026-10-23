# Connectors

Part of the canopy design, normative like all of it: the programs that read the tracker and GitHub into the journal,
and what canopy derives from what they read. Sections are numbered across the whole design; the [README](README.md)
has the map. Previous: [Review replies](REVIEW_REPLIES.md). Next: [Personas](PERSONAS.md).

## 30. Connectors

D003, D008. The overseer reads the tracker and GitHub again every tick, through MCP, and most of what it reads has not
changed since the tick before; once the queue settles, that watching is most of canopy's spend (MEASUREMENTS
2026-10-15). So each tick is to run from journal state, read into it by deterministic programs. This section is the
first step: canopy reads the world into the journal and derives in code what §7 and §14 derive, beside the overseer,
which sees and does nothing different.

A **connector** is a deterministic program that reads one source and prints what it saw as JSON lines. canopy runs it
through `procs`, validates and bounds each line, and records it as an **observation**: a dated copy of a fact about the
world. Authority stays with the source (§4 principle 1, §22): an observation says what a connector saw and when, never
what is true now. Nothing yet reads an observation to decide anything but the derivation, which only the operator and
the measurement read.

### Sources

There is at most one source of each kind, `tracker`, `vcs`, and `artifacts` (an artifact store's comment feed, §38),
each a command run with no shell (§20) under a timeout.
Every `connect.*` key is private (§12, TRUST_MODEL T7), since each runs a command with the operator's credentials. The
`vcs` source defaults to canopy's own programs (§29), so PRs are observed with nothing configured. There is no default
`tracker` source, since the harness never branches on `tracker.provider` (§17); without one, tickets are not observed,
and the derivation says so. An observation past `connect.max_age_minutes` is stale; the default keeps what a tick
observed fresh through its dispatches. Between ticks, `canopy loop` polls every source every `connect.every_minutes`,
whatever its pace for ticks (§6, Ticks and polls).

### The contract

On stdin, one JSON object naming what to observe, and a connector reads only what it is given: a `tracker` source the
tracker query and every ticket the state block lists (§6 step 4); a `vcs` source every PR of a ticket not marked done,
with a draft waiting (§29), or last observed open, so no observation stays open unread, the repositories, the branch
prefix, and the review query; an `artifacts` source its feed's cursor. On stdout, one JSON line per observation, naming
its kind (tickets and comments; PRs, branches, checks, and reviews; a feed's changes to comments and threads), and last
an `end` line naming what the run read whole, or for a feed the cursor its next run reads from; the exit code is not
read. A connector of the operator's own speaks this contract and nothing else: it is all the harness knows of any of
them.

- Ids, states, times, and bounded text; never logs, diffs, PR descriptions, or a credential.
- A connector pages everything before `end` names it: the tracker query to its last page (REQUIREMENTS R1), a PR's
  threads, its head's checks. A watched ticket's blockers are printed too, and every branch under the prefix.
- CI is observed by named context, never the combined status, which read green PRs as pending (MEASUREMENTS 2026-10-15).
- A kind the source does not own is skipped, so one source's program never writes another's facts. Unknown kinds and
  fields are ignored, so a newer connector works with an older canopy.

### Validating and the journal

Each line is validated against its kind (D026). Text is cut and marked, as a mirrored comment's is (§22); a field whose
cut would change what it says, such as an id or a state, refuses the line instead. A refused line leaves its subject
not whole this run, whatever `end` says, so a line canopy could not read never looks like a review or a check gone. A
run with no `end` line records nothing: without it, canopy cannot tell what is missing from what is not there. A
subject read whole has its observations replaced in one transaction, so what is gone from the source is gone from the
journal; a subject not read whole keeps its old rows and their age. A refused line whose subject canopy cannot read
leaves no subject of its kind whole; a line that is not JSON is skipped, as an unknown kind is. A feed is never read
whole: each change is read once, past the cursor the last run's `end` line named, and kept as the newest change to its
thread or comment. A refused change holds the cursor before it, so the next run reads it again and none is missed.

Comments are kept apart from the conversation, in their own observations, once each and cut and marked as a mirrored
comment is (§22), the workers' marks (D069) read in code. The conversation is what a private worker's prompt carries
(§8), so a comment written there would reach a worker without the overseer mirroring it, under none of the mirror's
bounds; while this section is in shadow they stay apart (operator, 2026-10-19), and the step that has the overseer read
the journal (§35) decides how they reach it. The connector moves no mirror cursor and records no decision, so the
overseer mirrors as before. Each tick's run of a source is recorded with what it was asked and what it read; §29's
reads after a run and before a send are validated the same way but are not a tick's runs.

### In the tick, and between ticks

In §6 step 3, after the reconciles, the tick runs the `tracker` source, then the `vcs` source, which is also §29's
reconcile read, then the `artifacts` source; a tick whose reconcile failed runs none, and a dry run observes as a live
tick does. A source that
fails, or reads less than it was asked, keeps its previous observations and raises the harness's `connector_failed`
(§14), naming what was not read, each tick until a run reads everything; the overseer's view of the list leaves it
out. It is one item about the workspace, its detail naming each failing source, since the attention list has no
subject for a source. The tick goes on and loses nothing, since the overseer still reads live. The derivation
follows. The loop's polls between ticks run the same sources the same way, record their runs with no tick, and raise
nothing (§6).

### The derivation, in shadow

D008 moves a rule from the prompt into code one at a time, each checked against the `decisions` corpus first; applied
by hand, §7's table disagreed with the overseer on `ci_red` (MEASUREMENTS 2026-10-15). So the derivation runs in
shadow, and a measurement says which rows code may take.

- Each tick the harness derives, from the observations and the journal, what §7 and §14 derive: the candidates (§17),
  each ticket's and unit's phase, its next action and the actions a choice allows, and the attention reasons. A ticket
  that depends on a stale or missing observation is derived as stale and counted apart, never as a disagreement.
- The derivation is recorded beside `decisions`, every row of §7 that held, as §7 has no order yet, and with it the
  phase the overseer left each subject at when the tick closed. It writes no decision, and changes no state block,
  attention item, cursor, phase, or guard.
- It agrees with the overseer when the phase the overseer set is one of the rows that held and its decision one that
  row allows. Agreement is computed, never stored, so a fix to the comparison reads every tick already recorded; the
  rows themselves go under §26's window, and the measurement in `MEASUREMENTS.md` outlives them.

### Checks that are not CI

Some contexts stay pending until a person acts, a deploy approval or a sign-off, and counting one as CI holds a green PR
at `ci_running` for as long. Each repository names them in the map (§18) as `human_checks`. A listed context is not
CI: it does not hold a unit at `ci_running`, make it `ci_red`, or have to pass.

- The list names the exceptions, not the CI: a job left off a list of CI would hide a red build, while a check left
  off this one holds a PR where the operator sees it waiting.
- Shared: it is a fact about the repository, and runs, spends, and authorizes nothing (TRUST_MODEL T7).
- Rejected: branch protection's required checks (reading them needs admin, and one can be the human check); a time past
  which a pending check counts as human (a slow build crosses any threshold).

### canopy's connectors

Each is a uv workspace member importing nothing from canopy, as §29's programs are (§5), and speaks the whole
contract. `canopy-connect-github`, §29's reader, is the `vcs` connector, and given a repository, a `tracker` connector
for GitHub Issues, with `gh`'s token for the host a PR's URL or a repository's clone URL names. It reads every watched
PR many to a GraphQL query, not a call per PR, which would cost many times the overseer's reads (MEASUREMENTS
2026-10-15). `canopy-connect-jira` reads Jira Cloud with credentials from an operator-only file held to the Slack
sink's checks (§20), sent only to the site the operator names, and never in config, argv, journal, or logs.

Rejected: the harness calling the APIs (D003, TRUST_MODEL T2: the process that holds the journal and enforces the
guards never opens a connection or reads a token); an agent as the connector (a model run as a poll, against §4
principle 4, printing a claim, not an observation); MCP servers driven from Python (a client in the harness, and their
credentials with it).

### Open

- Whether one failed run should raise `connector_failed`, or only one that leaves an observation stale.
